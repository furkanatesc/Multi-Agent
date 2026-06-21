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


# --------------------------------------------------------------------------- #
# HITL run lifecycle: POST /api/projects + POST /api/hitl/{id}/approve
#
# The autouse stub fixtures (conftest.py) make the graph run offline, and a
# single TestClient is reused per test so both requests share the app's
# in-memory checkpointer (same thread_id state).
# --------------------------------------------------------------------------- #


def test_start_project_pauses_at_deploy_gate() -> None:
    client = _client()
    resp = client.post("/api/projects", json={"prompt": "Build a todo app"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"]
    assert body["awaiting_hitl"] is True
    assert body["hitl"]["gate_type"] == "deploy"
    assert body["status"] != "completed"


def test_approve_deploy_resumes_to_completion() -> None:
    client = _client()
    start = client.post("/api/projects", json={"prompt": "app"}).json()
    pid = start["project_id"]

    resp = client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["awaiting_hitl"] is False
    assert body["status"] == "completed"


def test_reject_deploy_aborts_run() -> None:
    client = _client()
    pid = client.post("/api/projects", json={"prompt": "app"}).json()["project_id"]

    body = client.post(
        f"/api/hitl/{pid}/approve", json={"decision": "reject", "feedback": "no"}
    ).json()
    assert body["awaiting_hitl"] is False
    assert body["status"] == "failed"


def test_resolve_unknown_project_returns_404() -> None:
    resp = _client().post(
        "/api/hitl/does-not-exist/approve", json={"decision": "approve"}
    )
    assert resp.status_code == 404


def test_resolve_when_not_awaiting_returns_409() -> None:
    client = _client()
    pid = client.post("/api/projects", json={"prompt": "app"}).json()["project_id"]
    # First approval completes the run.
    client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
    # Second approval has nothing to resume.
    resp = client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
    assert resp.status_code == 409
