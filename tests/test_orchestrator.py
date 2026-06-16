"""End-to-end graph flow tests (stub nodes) and conditional-edge unit tests."""

from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.orchestrator import edges
from src.orchestrator.graph import build_graph
from src.orchestrator.state import AgentState, UserRequest, create_initial_state

# Note: the autouse `_stub_architect_agent` fixture (tests/conftest.py) replaces
# the graph's ArchitectAgent with an offline stub for every test here.


# --------------------------------------------------------------------------- #
# Graph compilation & end-to-end flow (stub nodes + in-memory checkpointer)
# --------------------------------------------------------------------------- #


def _run() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Compile the graph and run one project to completion. Returns (graph, cfg, final)."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-thread-1"}}
    initial = create_initial_state(UserRequest(prompt="Build a todo app"), project_id="p1")
    final = graph.invoke(initial, config=config)
    return graph, config, final


def test_graph_compiles_with_stub_nodes() -> None:
    """The graph compiles without error when given a checkpointer."""
    graph = build_graph(checkpointer=InMemorySaver())
    assert graph is not None


def test_graph_runs_to_completion() -> None:
    """The happy path reaches the deployer and marks the run completed."""
    _graph, _config, final = _run()
    assert final["status"] == "completed"


def test_graph_accumulates_reducer_channels() -> None:
    """operator.add channels accumulate across the traversed nodes."""
    _graph, _config, final = _run()
    # supervisor->architect->coder->inner_loop->security->test_gen->reviewer->deployer
    assert final["iteration_count"] == 8
    assert final["total_cost_usd"] == pytest.approx(8 * 0.01)
    # messages appended by every node
    assert len(final["messages"]) == 8


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
    graph.invoke(create_initial_state(UserRequest(prompt="app A")), config=cfg_a)
    graph.invoke(create_initial_state(UserRequest(prompt="app B")), config=cfg_b)

    state_a = graph.get_state(cfg_a).values
    state_b = graph.get_state(cfg_b).values
    assert state_a["messages"][0].content.startswith("[supervisor]")
    assert state_b["messages"][0].content.startswith("[supervisor]")
    # Each thread accumulated its own (equal) iteration count independently.
    assert state_a["iteration_count"] == state_b["iteration_count"] == 8


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
    assert edges.security_gate(_state(security_critical=True, security_score=95)) == "block_hitl"


def test_security_gate_fixes_on_low_score() -> None:
    assert edges.security_gate(_state(security_critical=False, security_score=50)) == "fix"


def test_security_gate_proceeds_when_secure() -> None:
    assert edges.security_gate(_state(security_critical=False, security_score=90)) == "proceed"


def test_review_decision_approves_on_pass() -> None:
    assert edges.review_decision(_state(review_decision="PASS")) == "approve"


def test_review_decision_rejects_on_fail_under_cap() -> None:
    state = _state(review_decision="FAIL", outer_loop_count=1)
    assert edges.review_decision(state) == "reject"


def test_review_decision_escalates_on_fail_at_cap() -> None:
    state = _state(review_decision="FAIL", outer_loop_count=5)
    assert edges.review_decision(state) == "escalate"
