"""Prometheus metrics for the multi-agent pipeline.

All collectors live on a **dedicated** :class:`CollectorRegistry` (not the global
default) so the exposition served at ``/metrics`` contains only this app's
metrics and unit tests stay isolated from process-global state. The rest of the
codebase records through the small ``record_*`` / ``observe_*`` helpers rather
than touching the collectors directly, keeping the instrumentation points
one-liners and decoupled from the Prometheus client API.

Metrics (mirroring the Sprint 7 plan):

* ``agent_tokens_total{model,kind}``   — prompt/completion tokens per model.
* ``agent_cost_usd_total{model}``      — accumulated USD spend per model.
* ``llm_requests_total{model,status}`` — LLM call outcomes (success/error).
* ``agent_loop_count{loop}``           — inner/outer self-fix loop iterations.
* ``review_rejections_total``          — Reviewer FAIL verdicts.
* ``ci_build_duration_seconds``        — inner-loop / CI build wall-clock.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

#: Dedicated registry — keeps app metrics isolated from the global default.
REGISTRY = CollectorRegistry()

agent_tokens_total = Counter(
    "agent_tokens_total",
    "LLM tokens consumed, partitioned by model and kind (prompt/completion).",
    labelnames=("model", "kind"),
    registry=REGISTRY,
)

agent_cost_usd_total = Counter(
    "agent_cost_usd_total",
    "Accumulated LLM spend in USD, partitioned by model.",
    labelnames=("model",),
    registry=REGISTRY,
)

llm_requests_total = Counter(
    "llm_requests_total",
    "LLM completion requests, partitioned by model and outcome.",
    labelnames=("model", "status"),
    registry=REGISTRY,
)

agent_loop_count = Counter(
    "agent_loop_count",
    "Self-fix loop iterations, partitioned by loop (inner/outer).",
    labelnames=("loop",),
    registry=REGISTRY,
)

review_rejections_total = Counter(
    "review_rejections_total",
    "Number of Reviewer FAIL verdicts (changes sent back to the Coder).",
    registry=REGISTRY,
)

ci_build_duration_seconds = Histogram(
    "ci_build_duration_seconds",
    "Wall-clock duration of an inner-loop / CI build in seconds.",
    registry=REGISTRY,
)

hitl_requests_total = Counter(
    "hitl_requests_total",
    "Human-in-the-loop gate requests, partitioned by gate (security/deploy).",
    labelnames=("gate",),
    registry=REGISTRY,
)

hitl_resolutions_total = Counter(
    "hitl_resolutions_total",
    "HITL gate resolutions, partitioned by gate and decision (approve/reject).",
    labelnames=("gate", "decision"),
    registry=REGISTRY,
)


# --------------------------------------------------------------------------- #
# Recording helpers (the instrumentation surface used elsewhere)
# --------------------------------------------------------------------------- #


def record_llm_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Record token counts and cost for a single successful LLM call."""
    if prompt_tokens:
        agent_tokens_total.labels(model=model, kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        agent_tokens_total.labels(model=model, kind="completion").inc(
            completion_tokens
        )
    if cost_usd:
        agent_cost_usd_total.labels(model=model).inc(cost_usd)


def record_llm_request(model: str, status: str) -> None:
    """Record the outcome of an LLM completion request (``success``/``error``)."""
    llm_requests_total.labels(model=model, status=status).inc()


def record_loop(loop: str, iterations: int = 1) -> None:
    """Record self-fix loop iterations for the given loop (``inner``/``outer``)."""
    if iterations:
        agent_loop_count.labels(loop=loop).inc(iterations)


def record_review_rejection() -> None:
    """Record a Reviewer FAIL verdict."""
    review_rejections_total.inc()


def observe_ci_build(seconds: float) -> None:
    """Observe the duration of an inner-loop / CI build."""
    ci_build_duration_seconds.observe(seconds)


def record_hitl_request(gate: str) -> None:
    """Record that a HITL gate (``security``/``deploy``) requested approval."""
    hitl_requests_total.labels(gate=gate).inc()


def record_hitl_resolution(gate: str, decision: str) -> None:
    """Record a HITL gate resolution (``approve``/``reject``) for ``gate``."""
    hitl_resolutions_total.labels(gate=gate, decision=decision).inc()


def render() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
