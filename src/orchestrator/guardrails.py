"""Centralized guardrail thresholds and decisions for the orchestration graph.

The :class:`GuardrailsEngine` is the single source of truth for the run-safety
caps — project budget, inner/outer loop iteration limits, and per-agent token
limits. The conditional edge routers (:mod:`orchestrator.edges`) delegate their
threshold checks here so the limits stay configuration-driven and there are no
magic numbers scattered across the flow.

Thresholds come from ``config/guardrails.yaml`` via ``settings.guardrails``; an
explicit ``guardrails`` dict can be injected for deterministic unit tests.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.config import settings
from src.orchestrator.state import AgentState

# Defaults applied when guardrails.yaml omits a key.
_DEFAULT_MAX_INNER = 3
_DEFAULT_MAX_OUTER = 5
_DEFAULT_MAX_COST = 10.0
_DEFAULT_HITL_TIMEOUT_SECONDS = 3600


class GuardrailsEngine:
    """Reads guardrail thresholds and answers run-safety questions about state.

    Args:
        guardrails: Optional explicit thresholds mapping. When ``None`` the
            engine reads ``settings.guardrails`` (loaded from
            ``config/guardrails.yaml``).
    """

    def __init__(self, guardrails: Optional[dict[str, Any]] = None) -> None:
        self._g: dict[str, Any] = (
            guardrails if guardrails is not None else settings.guardrails
        )

    # --- threshold accessors ----------------------------------------------- #

    def _get(self, key: str, default: Any) -> Any:
        return self._g.get(key, default)

    @property
    def max_project_cost_usd(self) -> float:
        """Hard ceiling on total accumulated USD spend for a project run."""
        return float(self._get("max_project_cost_usd", _DEFAULT_MAX_COST))

    @property
    def max_inner_loop_iterations(self) -> int:
        """Max lint/test self-fix iterations before giving up locally."""
        return int(self._get("max_inner_loop_iterations", _DEFAULT_MAX_INNER))

    @property
    def max_outer_loop_iterations(self) -> int:
        """Max review->coder iterations before escalating to a human."""
        return int(self._get("max_outer_loop_iterations", _DEFAULT_MAX_OUTER))

    @property
    def hitl_timeout_seconds(self) -> int:
        """Seconds a pending HITL approval may wait before it is timed out."""
        return int(self._get("hitl_timeout_seconds", _DEFAULT_HITL_TIMEOUT_SECONDS))

    # --- state predicates -------------------------------------------------- #

    def budget_exceeded(self, state: AgentState) -> bool:
        """True when accumulated spend has reached/passed the project budget."""
        spent = float(state.get("total_cost_usd", 0.0) or 0.0)
        return spent >= self.max_project_cost_usd

    def inner_loop_exhausted(self, state: AgentState) -> bool:
        """True when the inner self-fix loop has hit its iteration cap."""
        count = int(state.get("inner_loop_count", 0) or 0)
        return count >= self.max_inner_loop_iterations

    def outer_loop_exhausted(self, state: AgentState) -> bool:
        """True when the outer review loop has hit its iteration cap."""
        count = int(state.get("outer_loop_count", 0) or 0)
        return count >= self.max_outer_loop_iterations

    def token_limit(self, model: str) -> Optional[int]:
        """Return the configured per-invocation token cap for ``model``.

        Reads the ``agent_token_limits`` mapping; returns ``None`` when no limit
        is configured for the given route.
        """
        limits = self._get("agent_token_limits", {}) or {}
        value = limits.get(model)
        return int(value) if value is not None else None
