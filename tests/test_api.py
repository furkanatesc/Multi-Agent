"""Unit tests for the FastAPI app skeleton (Sprint 7, PR#12).

Covers the observability surface: ``/health`` and the Prometheus ``/metrics``
endpoint. Uses Starlette's ``TestClient`` (no running server).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.observability import metrics


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_ok() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "tracing" in body


def test_metrics_endpoint_serves_prometheus_exposition() -> None:
    # Record something so the exposition is non-trivial.
    metrics.record_llm_request("api-test-model", "success")

    resp = _client().get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "llm_requests_total" in resp.text
    assert "api-test-model" in resp.text


def test_metrics_endpoint_includes_all_collectors() -> None:
    body = _client().get("/metrics").text
    for name in (
        "agent_tokens_total",
        "agent_cost_usd_total",
        "agent_loop_count",
        "review_rejections_total",
        "ci_build_duration_seconds",
    ):
        assert name in body
