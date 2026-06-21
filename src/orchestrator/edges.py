"""Conditional edge functions for the orchestration graph.

Each function is a *pure* router: it reads the current :class:`AgentState` and
returns a short string key. ``graph.py`` maps those keys to concrete target
nodes (or ``END``). Keeping the decision logic here — separate from the nodes —
makes the routing independently unit-testable with hand-built mock states
(see ``tests/test_orchestrator.py``).

Iteration/budget thresholds are owned by :class:`GuardrailsEngine`
(``guardrails.py``); these routers delegate to it so the limits stay
configuration-driven (no magic numbers in the flow).
"""

from __future__ import annotations

from src.orchestrator.guardrails import GuardrailsEngine
from src.orchestrator.state import AgentState

# Minimum acceptable security posture score (gate-local, not an iteration cap).
_MIN_SECURITY_SCORE = 80


def cost_check(state: AgentState) -> str:
    """Halt the run if the accumulated spend has hit the budget ceiling.

    Returns ``"halt"`` when ``total_cost_usd`` exceeds the configured project
    budget, otherwise ``"continue"``.
    """
    return "halt" if GuardrailsEngine().budget_exceeded(state) else "continue"


def should_continue_inner_loop(state: AgentState) -> str:
    """Decide whether the inner lint/test self-fix loop should iterate again.

    * ``"proceed"`` — lint **and** tests pass, or the inner-loop iteration cap
      has been reached (give up locally and let downstream gates handle it).
    * ``"fix"`` — there is still a failure and budget of iterations remains;
      route back to the Coder for another self-fix attempt.
    """
    passed = bool(state.get("lint_passed")) and bool(state.get("tests_passed"))
    if passed:
        return "proceed"
    if GuardrailsEngine().inner_loop_exhausted(state):
        return "proceed"
    return "fix"


def should_escalate(state: AgentState) -> bool:
    """Return True when the outer (review->coder) loop has exhausted its budget."""
    return GuardrailsEngine().outer_loop_exhausted(state)


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


def hitl_route(state: AgentState) -> str:
    """Route on the most recent HITL gate verdict.

    Returns ``"approve"`` only when the human explicitly approved; any other
    value (including a missing decision) routes to ``"reject"`` so a gate never
    proceeds on ambiguous state. Both the security and deploy gates share this
    router (``graph.py`` maps the two outcomes to gate-specific targets).
    """
    return "approve" if state.get("hitl_decision") == "approve" else "reject"


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
