"""Unit tests for the :class:`GuardrailsEngine` (cost/iteration/token caps).

The engine centralizes every guardrail threshold and decision so the edge
routers (``edges.py``) stay thin. Tests construct the engine with an explicit
guardrails dict (no YAML/settings dependency) for determinism.
"""

from typing import Any, cast

from src.orchestrator.guardrails import GuardrailsEngine
from src.orchestrator.state import AgentState

_GUARDRAILS = {
    "max_project_cost_usd": 10.0,
    "max_inner_loop_iterations": 3,
    "max_outer_loop_iterations": 5,
    "hitl_timeout_seconds": 1800,
    "agent_token_limits": {"coder-model": 150000},
}


def _engine() -> GuardrailsEngine:
    return GuardrailsEngine(guardrails=dict(_GUARDRAILS))


def _state(**kwargs: Any) -> AgentState:
    return cast(AgentState, dict(kwargs))


# --- thresholds ------------------------------------------------------------ #


def test_thresholds_read_from_config() -> None:
    engine = _engine()
    assert engine.max_project_cost_usd == 10.0
    assert engine.max_inner_loop_iterations == 3
    assert engine.max_outer_loop_iterations == 5


def test_thresholds_fall_back_to_defaults_when_missing() -> None:
    engine = GuardrailsEngine(guardrails={})
    assert engine.max_project_cost_usd == 10.0
    assert engine.max_inner_loop_iterations == 3
    assert engine.max_outer_loop_iterations == 5
    assert engine.hitl_timeout_seconds == 3600


def test_hitl_timeout_reads_from_config() -> None:
    assert _engine().hitl_timeout_seconds == 1800


# --- budget ---------------------------------------------------------------- #


def test_budget_exceeded_at_or_over_ceiling() -> None:
    engine = _engine()
    assert engine.budget_exceeded(_state(total_cost_usd=10.0)) is True
    assert engine.budget_exceeded(_state(total_cost_usd=10.01)) is True


def test_budget_not_exceeded_under_ceiling() -> None:
    engine = _engine()
    assert engine.budget_exceeded(_state(total_cost_usd=9.99)) is False
    assert engine.budget_exceeded(_state()) is False  # missing -> 0.0


# --- inner / outer loops --------------------------------------------------- #


def test_inner_loop_exhausted_at_cap() -> None:
    engine = _engine()
    assert engine.inner_loop_exhausted(_state(inner_loop_count=3)) is True
    assert engine.inner_loop_exhausted(_state(inner_loop_count=2)) is False
    assert engine.inner_loop_exhausted(_state()) is False  # missing -> 0


def test_outer_loop_exhausted_at_cap() -> None:
    engine = _engine()
    assert engine.outer_loop_exhausted(_state(outer_loop_count=5)) is True
    assert engine.outer_loop_exhausted(_state(outer_loop_count=4)) is False


# --- token limits ---------------------------------------------------------- #


def test_token_limit_known_and_unknown_model() -> None:
    engine = _engine()
    assert engine.token_limit("coder-model") == 150000
    assert engine.token_limit("nonexistent-model") is None
