"""Unit tests for the Prometheus metrics module (Sprint 7, PR#12).

Reads counter/histogram values straight off the dedicated registry via
``get_sample_value`` so the tests don't depend on the exposition text format.
"""

from __future__ import annotations

from src.observability import metrics


def _sample(name: str, labels: dict[str, str] | None = None) -> float | None:
    return metrics.REGISTRY.get_sample_value(name, labels or {})


def test_record_llm_usage_increments_tokens_and_cost() -> None:
    before_prompt = _sample(
        "agent_tokens_total", {"model": "m-test", "kind": "prompt"}
    ) or 0.0
    before_cost = _sample("agent_cost_usd_total", {"model": "m-test"}) or 0.0

    metrics.record_llm_usage(
        "m-test", prompt_tokens=10, completion_tokens=4, cost_usd=0.5
    )

    assert _sample("agent_tokens_total", {"model": "m-test", "kind": "prompt"}) == (
        before_prompt + 10
    )
    assert _sample(
        "agent_tokens_total", {"model": "m-test", "kind": "completion"}
    ) == 4
    assert _sample("agent_cost_usd_total", {"model": "m-test"}) == before_cost + 0.5


def test_record_llm_usage_skips_zero_values() -> None:
    # Zero tokens/cost must not create label series with 0 (no-op).
    metrics.record_llm_usage(
        "m-zero", prompt_tokens=0, completion_tokens=0, cost_usd=0.0
    )
    assert _sample("agent_tokens_total", {"model": "m-zero", "kind": "prompt"}) is None
    assert _sample("agent_cost_usd_total", {"model": "m-zero"}) is None


def test_record_llm_request_outcomes() -> None:
    metrics.record_llm_request("m-req", "success")
    metrics.record_llm_request("m-req", "success")
    metrics.record_llm_request("m-req", "error")

    assert _sample("llm_requests_total", {"model": "m-req", "status": "success"}) == 2
    assert _sample("llm_requests_total", {"model": "m-req", "status": "error"}) == 1


def test_record_loop_partitions_by_loop() -> None:
    # Counter names not ending in "_total" get the suffix in the time series.
    before_inner = _sample("agent_loop_count_total", {"loop": "inner"}) or 0.0
    before_outer = _sample("agent_loop_count_total", {"loop": "outer"}) or 0.0
    metrics.record_loop("inner", 3)
    metrics.record_loop("outer", 1)
    assert _sample("agent_loop_count_total", {"loop": "inner"}) == before_inner + 3
    assert _sample("agent_loop_count_total", {"loop": "outer"}) == before_outer + 1


def test_record_loop_zero_is_noop() -> None:
    before = _sample("agent_loop_count_total", {"loop": "inner"})
    metrics.record_loop("inner", 0)  # should not raise / change anything
    assert _sample("agent_loop_count_total", {"loop": "inner"}) == before


def test_record_review_rejection() -> None:
    before = _sample("review_rejections_total") or 0.0
    metrics.record_review_rejection()
    assert _sample("review_rejections_total") == before + 1


def test_record_hitl_request_and_resolution() -> None:
    before_req = _sample("hitl_requests_total", {"gate": "deploy"}) or 0.0
    before_appr = (
        _sample("hitl_resolutions_total", {"gate": "deploy", "decision": "approve"})
        or 0.0
    )
    before_rej = (
        _sample("hitl_resolutions_total", {"gate": "security", "decision": "reject"})
        or 0.0
    )
    metrics.record_hitl_request("deploy")
    metrics.record_hitl_resolution("deploy", "approve")
    metrics.record_hitl_resolution("security", "reject")
    assert _sample("hitl_requests_total", {"gate": "deploy"}) == before_req + 1
    assert (
        _sample("hitl_resolutions_total", {"gate": "deploy", "decision": "approve"})
        == before_appr + 1
    )
    assert (
        _sample("hitl_resolutions_total", {"gate": "security", "decision": "reject"})
        == before_rej + 1
    )


def test_observe_ci_build_records_histogram() -> None:
    metrics.observe_ci_build(2.5)
    assert (_sample("ci_build_duration_seconds_count") or 0.0) >= 1
    assert (_sample("ci_build_duration_seconds_sum") or 0.0) >= 2.5


def test_render_returns_exposition_and_content_type() -> None:
    metrics.record_review_rejection()
    payload, content_type = metrics.render()
    assert isinstance(payload, bytes)
    assert b"review_rejections_total" in payload
    assert "text/plain" in content_type
