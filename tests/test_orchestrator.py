"""End-to-end graph flow tests (stub nodes) and conditional-edge unit tests.

The HITL gates pause the graph via dynamic ``interrupt()``; ``_drive`` resumes
each one with ``Command(resume=...)`` so the flow tests can run to completion.
HITL DB persistence is disabled for graph tests by the autouse fixture in
``conftest.py`` (it is unit-tested against SQLite in ``test_hitl.py``).
"""

from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.integrations.github_client import GitHubError
from src.orchestrator import edges, nodes
from src.orchestrator.graph import build_graph
from src.orchestrator.state import AgentState, UserRequest, create_initial_state

# Note: the autouse stub fixtures (tests/conftest.py) replace the graph's agents
# with offline stubs and disable HITL persistence for every test here.


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _drive(
    graph: Any,
    config: dict[str, Any],
    initial: Any,
    *,
    security: str = "approve",
    deploy: str = "approve",
    max_steps: int = 12,
) -> dict[str, Any]:
    """Invoke the graph and resume each HITL interrupt with a decision."""
    result = graph.invoke(initial, config=config)
    steps = 0
    while "__interrupt__" in result and steps < max_steps:
        gate_type = result["__interrupt__"][0].value.get("gate_type")
        decision = security if gate_type == "security" else deploy
        result = graph.invoke(Command(resume={"decision": decision}), config=config)
        steps += 1
    return result


def _run() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Compile the graph and run one project to completion (graph, cfg, final)."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-thread-1"}}
    initial = create_initial_state(
        UserRequest(prompt="Build a todo app"), project_id="p1"
    )
    final = _drive(graph, config, initial)
    return graph, config, final


# --------------------------------------------------------------------------- #
# Graph compilation & end-to-end flow (stub nodes + in-memory checkpointer)
# --------------------------------------------------------------------------- #


def test_graph_compiles_with_stub_nodes() -> None:
    """The graph compiles without error when given a checkpointer."""
    graph = build_graph(checkpointer=InMemorySaver())
    assert graph is not None


def test_graph_runs_to_completion() -> None:
    """The happy path reaches the deployer (after deploy approval) and completes."""
    _graph, _config, final = _run()
    assert final["status"] == "completed"


def test_graph_accumulates_reducer_channels() -> None:
    """operator.add channels accumulate across the traversed nodes."""
    _graph, _config, final = _run()
    # supervisor->architect->coder->inner_loop->security->test_gen->reviewer
    # ->deploy_gate->deployer (gates add an iteration/message but no cost)
    assert final["iteration_count"] == 9
    assert final["total_cost_usd"] == pytest.approx(8 * 0.01)
    assert len(final["messages"]) == 9


def test_graph_populates_domain_state() -> None:
    """Stub nodes populate architecture, code, security, and review channels."""
    _graph, _config, final = _run()
    assert final["platform"] == "react-native"
    assert final["architecture_spec"]["tech_stack"]["platform"] == "react-native"
    assert "src/App.stub.txt" in final["source_code"]
    assert final["security_score"] == 90
    assert final["review_decision"] == "PASS"


def test_checkpointing_persists_and_restores_state() -> None:
    """PostgresSaver/InMemorySaver checkpointing: state is retrievable by thread."""
    graph, config, final = _run()
    snapshot = graph.get_state(config)
    assert snapshot.values["status"] == "completed"
    assert snapshot.values["iteration_count"] == final["iteration_count"]


def test_two_threads_are_isolated() -> None:
    """Separate thread_ids maintain independent checkpointed state."""
    graph = build_graph(checkpointer=InMemorySaver())
    cfg_a = {"configurable": {"thread_id": "a"}}
    cfg_b = {"configurable": {"thread_id": "b"}}
    _drive(graph, cfg_a, create_initial_state(UserRequest(prompt="app A")))
    _drive(graph, cfg_b, create_initial_state(UserRequest(prompt="app B")))

    state_a = graph.get_state(cfg_a).values
    state_b = graph.get_state(cfg_b).values
    assert state_a["messages"][0].content.startswith("[supervisor]")
    assert state_b["messages"][0].content.startswith("[supervisor]")
    assert state_a["iteration_count"] == state_b["iteration_count"] == 9


# --------------------------------------------------------------------------- #
# HITL gates (deploy + security) — interrupt / resume behavior
# --------------------------------------------------------------------------- #


def test_deploy_gate_interrupts_before_deployer() -> None:
    """The graph pauses for human deploy approval before reaching the deployer."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "deploy-1"}}
    initial = create_initial_state(UserRequest(prompt="app"), project_id="p1")
    result = graph.invoke(initial, config=config)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["gate_type"] == "deploy"
    assert result["status"] != "completed"


def test_deploy_gate_reject_aborts_run() -> None:
    """Rejecting the deploy gate ends the run as failed without deploying."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "deploy-2"}}
    initial = create_initial_state(UserRequest(prompt="app"), project_id="p1")
    final = _drive(graph, config, initial, deploy="reject")
    assert final["status"] == "failed"
    assert not any(
        "[deployer]" in getattr(m, "content", "") for m in final["messages"]
    )


def test_security_critical_routes_through_hitl_then_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A critical security finding pauses at the security gate; approval proceeds."""

    class _CriticalSecurity:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        def run(self, state: AgentState) -> dict[str, Any]:
            from langchain_core.messages import AIMessage

            return {
                "messages": [AIMessage(content="[security] critical", name="security")],
                "security_score": 30,
                "security_critical": True,
                "total_cost_usd": 0.01,
                "iteration_count": 1,
            }

    monkeypatch.setattr("src.orchestrator.nodes.SecurityAgent", _CriticalSecurity)
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "sec-1"}}
    initial = create_initial_state(UserRequest(prompt="app"), project_id="p1")

    first = graph.invoke(initial, config=config)
    assert first["__interrupt__"][0].value["gate_type"] == "security"

    final = _drive(graph, config, Command(resume={"decision": "approve"}))
    assert final["status"] == "completed"


def test_security_gate_reject_loops_back_to_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejecting the security gate routes back to the coder and re-hits the gate."""

    class _CriticalSecurity:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        def run(self, state: AgentState) -> dict[str, Any]:
            from langchain_core.messages import AIMessage

            return {
                "messages": [AIMessage(content="[security] critical", name="security")],
                "security_score": 30,
                "security_critical": True,
                "total_cost_usd": 0.01,
                "iteration_count": 1,
            }

    monkeypatch.setattr("src.orchestrator.nodes.SecurityAgent", _CriticalSecurity)
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "sec-2"}}
    initial = create_initial_state(UserRequest(prompt="app"), project_id="p1")

    graph.invoke(initial, config=config)
    # Reject once: should loop coder->inner->security and pause at security again.
    after_reject = graph.invoke(Command(resume={"decision": "reject"}), config=config)
    assert "__interrupt__" in after_reject
    assert after_reject["__interrupt__"][0].value["gate_type"] == "security"


# --------------------------------------------------------------------------- #
# Conditional edges (pure routing logic with hand-built mock states)
# --------------------------------------------------------------------------- #


def _state(**kwargs: Any) -> AgentState:
    """Build a minimal mock AgentState for edge tests."""
    return cast(AgentState, dict(kwargs))


def test_cost_check_halts_when_over_budget() -> None:
    assert edges.cost_check(_state(total_cost_usd=999.0)) == "halt"


def test_cost_check_continues_under_budget() -> None:
    assert edges.cost_check(_state(total_cost_usd=0.0)) == "continue"


def test_inner_loop_proceeds_when_passing() -> None:
    state = _state(lint_passed=True, tests_passed=True, inner_loop_count=1)
    assert edges.should_continue_inner_loop(state) == "proceed"


def test_inner_loop_fixes_on_failure_under_cap() -> None:
    state = _state(lint_passed=False, tests_passed=False, inner_loop_count=1)
    assert edges.should_continue_inner_loop(state) == "fix"


def test_inner_loop_proceeds_when_cap_reached() -> None:
    """At/over the iteration cap, stop looping even if still failing."""
    state = _state(lint_passed=False, tests_passed=False, inner_loop_count=3)
    assert edges.should_continue_inner_loop(state) == "proceed"


def test_should_escalate_respects_outer_cap() -> None:
    assert edges.should_escalate(_state(outer_loop_count=5)) is True
    assert edges.should_escalate(_state(outer_loop_count=1)) is False


def test_security_gate_blocks_on_critical() -> None:
    state = _state(security_critical=True, security_score=95)
    assert edges.security_gate(state) == "block_hitl"


def test_security_gate_fixes_on_low_score() -> None:
    state = _state(security_critical=False, security_score=50)
    assert edges.security_gate(state) == "fix"


def test_security_gate_proceeds_when_secure() -> None:
    state = _state(security_critical=False, security_score=90)
    assert edges.security_gate(state) == "proceed"


def test_review_decision_approves_on_pass() -> None:
    assert edges.review_decision(_state(review_decision="PASS")) == "approve"


def test_review_decision_rejects_on_fail_under_cap() -> None:
    state = _state(review_decision="FAIL", outer_loop_count=1)
    assert edges.review_decision(state) == "reject"


def test_review_decision_escalates_on_fail_at_cap() -> None:
    state = _state(review_decision="FAIL", outer_loop_count=5)
    assert edges.review_decision(state) == "escalate"


def test_hitl_route_approve_and_reject() -> None:
    assert edges.hitl_route(_state(hitl_decision="approve")) == "approve"
    assert edges.hitl_route(_state(hitl_decision="reject")) == "reject"
    assert edges.hitl_route(_state()) == "reject"  # default: no auto-approve


# --------------------------------------------------------------------------- #
# Deployer: best-effort PR auto-merge after deploy approval
# --------------------------------------------------------------------------- #


def test_deployer_auto_merges_when_pr_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merged: dict[str, Any] = {}

    class _FakeGH:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        def auto_merge(self, repo: str, pr_number: int) -> None:
            merged["repo"] = repo
            merged["pr"] = pr_number

    monkeypatch.setattr("src.orchestrator.nodes.GitHubClient", _FakeGH)
    monkeypatch.setattr("src.orchestrator.nodes.settings.GITHUB_TOKEN", "ghp_x")

    update = nodes.deployer(_state(repo="furkanatesc/app", pr_number=42))
    assert merged == {"repo": "furkanatesc/app", "pr": 42}
    assert update["status"] == "completed"
    assert "auto-merged PR #42" in update["messages"][0].content


def test_deployer_skips_auto_merge_without_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.orchestrator.nodes.settings.GITHUB_TOKEN", "ghp_x")
    monkeypatch.setattr(
        "src.orchestrator.nodes.GitHubClient",
        lambda *a, **k: pytest.fail("GitHubClient must not be built without a PR"),
    )
    update = nodes.deployer(_state())  # no repo/pr_number
    assert update["status"] == "completed"


def test_deployer_auto_merge_failure_is_graceful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeGH:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        def auto_merge(self, repo: str, pr_number: int) -> None:
            raise GitHubError("merge conflict")

    monkeypatch.setattr("src.orchestrator.nodes.GitHubClient", _FakeGH)
    monkeypatch.setattr("src.orchestrator.nodes.settings.GITHUB_TOKEN", "ghp_x")

    update = nodes.deployer(_state(repo="furkanatesc/app", pr_number=7))
    assert update["status"] == "completed"  # failure does not break the run
    assert "auto-merge failed" in update["messages"][0].content
