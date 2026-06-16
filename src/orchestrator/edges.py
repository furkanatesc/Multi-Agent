"""Conditional edge functions for the orchestration graph.

Each function is a *pure* router: it reads the current :class:`AgentState` and
returns a short string key. ``graph.py`` maps those keys to concrete target
nodes (or ``END``). Keeping the decision logic here — separate from the nodes —
makes the routing independently unit-testable with hand-built mock states
(see ``tests/test_orchestrator.py``).

Thresholds come from ``config/guardrails.yaml`` via ``settings.guardrails`` so
the limits stay configuration-driven (no magic numbers in the flow).
"""

from __future__ import annotations

from typing import Any

from src.core.config import settings
from src.orchestrator.state import AgentState

# Default thresholds, used when guardrails.yaml omits a key.
_DEFAULT_MAX_INNER = 3
_DEFAULT_MAX_OUTER = 5
_DEFAULT_MAX_COST = 10.0
_MIN_SECURITY_SCORE = 80


def _guardrail(key: str, default: Any) -> Any:
    """Read a single guardrail value, falling back to ``default``."""
    return settings.guardrails.get(key, default)


def cost_check(state: AgentState) -> str:
    """Halt the run if the accumulated spend has hit the budget ceiling.

    Returns ``"halt"`` when ``total_cost_usd`` exceeds the configured project
    budget, otherwise ``"continue"``.
    """
    budget = float(_guardrail("max_project_cost_usd", _DEFAULT_MAX_COST))
    spent = float(state.get("total_cost_usd", 0.0) or 0.0)
    return "halt" if spent >= budget else "continue"


def should_continue_inner_loop(state: AgentState) -> str:
    """Decide whether the inner lint/test self-fix loop should iterate again.

    * ``"proceed"`` — lint **and** tests pass, or the inner-loop iteration cap
      has been reached (give up locally and let downstream gates handle it).
    * ``"fix"`` — there is still a failure and budget of iterations remains;
      route back to the Coder for another self-fix attempt.
    """
    max_inner = int(_guardrail("max_inner_loop_iterations", _DEFAULT_MAX_INNER))
    passed = bool(state.get("lint_passed")) and bool(state.get("tests_passed"))
    if passed:
        return "proceed"
    if int(state.get("inner_loop_count", 0)) >= max_inner:
        return "proceed"
    return "fix"


def should_escalate(state: AgentState) -> bool:
    """Return True when the outer (review->coder) loop has exhausted its budget."""
    max_outer = int(_guardrail("max_outer_loop_iterations", _DEFAULT_MAX_OUTER))
    return int(state.get("outer_loop_count", 0)) >= max_outer


def security_gate(state: AgentState) -> str:
    """Route based on the Security agent's verdict.

    * ``"block_hitl"`` — a critical/HIGH finding requires human approval.
    * ``"fix"`` — score below the minimum acceptable threshold; back to Coder.
    * ``"proceed"`` — secure enough; continue to test generation.
    """
    if bool(state.get("security_critical")):
        return "block_hitl"
    score = state.get("security_score")
    if score is not None and int(score) < _MIN_SECURITY_SCORE:
        return "fix"
    return "proceed"


def review_decision(state: AgentState) -> str:
    """Route on the Reviewer verdict, respecting the outer-loop escalation cap.

    * ``"approve"`` — Reviewer returned ``PASS``; proceed to deploy.
    * ``"escalate"`` — Reviewer returned ``FAIL`` but the outer-loop cap is hit;
      stop iterating and end the run (a HITL/operator must intervene).
    * ``"reject"`` — ``FAIL`` with iterations remaining; back to Coder.
    """
    if state.get("review_decision") == "PASS":
        return "approve"
    if should_escalate(state):
        return "escalate"
    return "reject"
