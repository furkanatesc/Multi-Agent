"""Placeholder node functions for the orchestration graph.

These are **stubs** for Sprint 2: they make the graph compile and run end-to-end
(so checkpointing and conditional routing can be exercised) without calling any
real LLM. Each future sprint replaces the relevant stub with a real agent:

* ``architect``       -> Sprint 3 (ArchitectAgent)
* ``coder`` / ``inner_loop_check`` -> Sprint 4
* ``security_scan`` / ``test_generator`` -> Sprint 5
* ``reviewer``        -> Sprint 6
* ``hitl_gate``       -> Sprint 7

Contract: a node never mutates state in place. It returns a *partial* dict; the
reducers declared on :class:`AgentState` merge it (``operator.add`` accumulates
cost/iteration, ``add_messages`` appends, ``merge_source_code`` folds files).
Every node adds ``iteration_count: 1`` and a small ``total_cost_usd`` so the
accumulator channels are observably exercised.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.agents.architect.agent import ArchitectAgent
from src.orchestrator.state import AgentState

# Nominal per-step stub cost so the cost accumulator is visibly non-zero.
_STUB_STEP_COST = 0.01


def _step(agent: str, content: str, **updates: Any) -> dict[str, Any]:
    """Build a standard partial state update for a stub node.

    Args:
        agent: Name used as the message author (for trace readability).
        content: Human-readable log line appended to the message history.
        **updates: Additional state channels this node writes.

    Returns:
        A partial ``AgentState`` dict (reducers merge it into running state).
    """
    update: dict[str, Any] = {
        "messages": [AIMessage(content=content, name=agent)],
        "iteration_count": 1,
        "total_cost_usd": _STUB_STEP_COST,
    }
    update.update(updates)
    return update


def supervisor(state: AgentState) -> dict[str, Any]:
    """Entry node: initializes the run and hands off to the Architect."""
    return _step(
        "supervisor",
        "[supervisor] run started; dispatching to architect",
        status="architecting",
        next_agent="architect",
    )


def architect(state: AgentState) -> dict[str, Any]:
    """Architect node: generates a structured ADR via :class:`ArchitectAgent`.

    Real LLM-backed agent (Sprint 3). The remaining nodes below are still stubs
    until their respective sprints. The agent returns a partial state update
    (architecture_spec + platform + incremental cost).
    """
    return ArchitectAgent().run(state)


def coder(state: AgentState) -> dict[str, Any]:
    """Stub Coder: emits a placeholder source file and resets lint/test flags."""
    return _step(
        "coder",
        "[coder] stub module generated",
        source_code={"src/App.stub.txt": "// stub generated module"},
        lint_passed=None,
        tests_passed=None,
        status="inner_loop",
        next_agent="inner_loop_check",
    )


def inner_loop_check(state: AgentState) -> dict[str, Any]:
    """Stub inner loop: simulates a lint/test run that passes on this pass.

    Increments ``inner_loop_count`` (overwrite channel) so the iteration cap in
    :func:`edges.should_continue_inner_loop` is respected on real failures.
    """
    iteration = int(state.get("inner_loop_count", 0)) + 1
    return _step(
        "inner_loop",
        f"[inner_loop] lint+test run #{iteration}: passed",
        inner_loop_count=iteration,
        lint_passed=True,
        tests_passed=True,
    )


def security_scan(state: AgentState) -> dict[str, Any]:
    """Stub Security agent: emits a passing security score, no critical findings."""
    return _step(
        "security",
        "[security] stub scan: score=90, no critical findings",
        security_score=90,
        security_critical=False,
        status="security_scan",
    )


def hitl_gate(state: AgentState) -> dict[str, Any]:
    """Stub HITL gate: auto-approves (real interrupt/approval wiring in Sprint 7)."""
    return _step(
        "hitl",
        "[hitl] stub gate auto-approved",
        status="awaiting_hitl",
    )


def test_generator(state: AgentState) -> dict[str, Any]:
    """Stub Test Generator: marks generated tests as passing."""
    return _step(
        "test_generator",
        "[test_generator] stub tests generated and passing",
        tests_passed=True,
        status="test_generation",
    )


def reviewer(state: AgentState) -> dict[str, Any]:
    """Stub Reviewer: returns PASS and increments the outer-loop counter."""
    outer = int(state.get("outer_loop_count", 0)) + 1
    return _step(
        "reviewer",
        "[reviewer] stub review: PASS",
        review_decision="PASS",
        review_notes="LGTM (stub review)",
        outer_loop_count=outer,
        status="review",
    )


def deployer(state: AgentState) -> dict[str, Any]:
    """Stub Deployer: marks the run complete (terminal node)."""
    return _step(
        "deployer",
        "[deployer] stub deploy complete",
        status="completed",
        next_agent=None,
    )
