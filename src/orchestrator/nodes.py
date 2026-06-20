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
from src.agents.coder.agent import CoderAgent
from src.agents.coder.inner_loop import InnerLoopRunner
from src.agents.reviewer.agent import ReviewerAgent
from src.agents.security.agent import SecurityAgent
from src.agents.test_generator.agent import TestGeneratorAgent
from src.observability import metrics
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
    """Coder node: generates source code via :class:`CoderAgent` (tool-loop).

    Real LLM-backed agent (Sprint 4). Returns a partial state update with the
    generated ``source_code`` map and the inner-loop routing.
    """
    return CoderAgent().run(state)


def inner_loop_check(state: AgentState) -> dict[str, Any]:
    """Inner-loop node: runs lint/test in Docker and self-fixes (Sprint 4).

    Delegates the whole lint→test→self-fix cycle to :class:`InnerLoopRunner`
    (bounded by the guardrail iteration cap), then writes the final verdicts and
    (possibly fixed) source back to state. ``inner_loop_count`` is set to the
    number of self-fix iterations spent so the downstream edge proceeds once the
    cap is reached.
    """
    result = InnerLoopRunner().run(
        state.get("source_code") or {}, state.get("platform")
    )
    verdict = "passed" if result.passed else "failed"
    metrics.record_loop("inner", result.iterations)
    return {
        "messages": [
            AIMessage(
                content=(
                    f"[inner_loop] {verdict} after {result.iterations} self-fix "
                    f"iter(s) (lint={result.lint_passed}, tests={result.tests_passed})"
                ),
                name="inner_loop",
            )
        ],
        "source_code": result.files,
        "lint_passed": result.lint_passed,
        "tests_passed": result.tests_passed,
        "inner_loop_count": result.iterations,
        "total_cost_usd": result.cost,
        "iteration_count": 1,
    }


def security_scan(state: AgentState) -> dict[str, Any]:
    """Security node: scans the generated code via :class:`SecurityAgent` (S5).

    Real LLM-backed agent. Returns a partial state update with the computed
    ``security_score`` and ``security_critical`` flag that the ``security_gate``
    edge routes on (proceed / fix / block_hitl).
    """
    return SecurityAgent().run(state)


def hitl_gate(state: AgentState) -> dict[str, Any]:
    """Stub HITL gate: auto-approves (real interrupt/approval wiring in Sprint 7)."""
    return _step(
        "hitl",
        "[hitl] stub gate auto-approved",
        status="awaiting_hitl",
    )


def test_generator(state: AgentState) -> dict[str, Any]:
    """Test Generator node: generates tests via :class:`TestGeneratorAgent` (S5).

    Real LLM-backed agent. Generates unit/widget/integration tests, merges them
    into ``source_code``, and (when Docker is available) sets ``tests_passed``
    from the ≥70% coverage check.
    """
    return TestGeneratorAgent().run(state)


def reviewer(state: AgentState) -> dict[str, Any]:
    """Reviewer node: SOLID/Clean-Code review via :class:`ReviewerAgent` (S6).

    Real LLM-backed agent. Returns a partial state update with the deterministic
    ``review_decision`` (PASS/FAIL) + ``review_notes`` and an incremented
    ``outer_loop_count`` that the ``review_decision`` edge routes on
    (approve→deploy, reject→coder, escalate→END once the outer cap is hit).
    """
    update = ReviewerAgent().run(state)
    metrics.record_loop("outer", 1)
    if update.get("review_decision") == "FAIL":
        metrics.record_review_rejection()
    return update


def deployer(state: AgentState) -> dict[str, Any]:
    """Stub Deployer: marks the run complete (terminal node)."""
    return _step(
        "deployer",
        "[deployer] stub deploy complete",
        status="completed",
        next_agent=None,
    )
