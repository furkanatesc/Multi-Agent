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


def test_cors_headers_present() -> None:
    resp = _client().get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --------------------------------------------------------------------------- #
# Sprint 8 — async-start run lifecycle + streaming.
#
# POST /api/projects now returns {project_id, mode} immediately and runs in the
# background. Tests use mode=demo with delay=0 (deterministic, keyless) and drive
# the flow over the WebSocket, approving each HITL gate via POST.
# --------------------------------------------------------------------------- #


def _demo_client() -> TestClient:
    client = TestClient(create_app())
    # Hold a persistent event-loop portal across every call this client makes.
    # Without this, Starlette's TestClient spins up a *new* ephemeral portal
    # (and event loop) per HTTP/WS call. The background run started by
    # POST /api/projects lives on asyncio.Condition/Task objects that bind to
    # whichever loop first touches them; a later POST /api/hitl/.../approve
    # would schedule its resume task on a *different* ephemeral loop and hit a
    # "bound to a different event loop" RuntimeError, silently killing the
    # resume task and hanging the WS stream forever. A single persistent
    # portal (entered here, never exited — acceptable for test-process
    # lifetime) matches real single-event-loop uvicorn behavior, where this
    # never happens.
    client.__enter__()
    client.app.state.demo_delay = 0.0  # type: ignore[attr-defined]
    return client


def test_start_demo_returns_project_id_and_mode() -> None:
    client = _demo_client()
    resp = client.post("/api/projects?mode=demo", json={"prompt": "todo app"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"]
    assert body["mode"] == "demo"


def test_list_projects_includes_started_run() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()[
        "project_id"
    ]
    runs = client.get("/api/projects").json()["runs"]
    assert any(r["project_id"] == pid for r in runs)


def test_ws_streams_full_demo_run_through_both_gates() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "todo"}).json()[
        "project_id"
    ]

    seen_types: list[str] = []
    with client.websocket_connect(f"/api/projects/{pid}/stream") as ws:
        approvals = 0
        while True:
            ev = ws.receive_json()
            seen_types.append(ev["type"])
            if ev["type"] == "hitl_request":
                resp = client.post(
                    f"/api/hitl/{pid}/approve", json={"decision": "approve"}
                )
                assert resp.status_code == 200  # a 409 here would hang the stream
                approvals += 1
            if ev["type"] == "completed":
                break
    assert seen_types[0] == "run_started"
    assert seen_types.count("hitl_request") == 2  # security + deploy
    assert approvals == 2
    assert seen_types[-1] == "completed"


def test_snapshot_reports_awaiting_after_first_gate() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()[
        "project_id"
    ]
    # Drive to the first gate over WS, then check the snapshot mid-run.
    with client.websocket_connect(f"/api/projects/{pid}/stream") as ws:
        while ws.receive_json()["type"] != "hitl_request":
            pass
        snap = client.get(f"/api/projects/{pid}").json()
        assert snap["awaiting_hitl"] is True
        assert snap["hitl"]["gate_type"] == "security"


def test_resolve_unknown_project_returns_404() -> None:
    resp = _demo_client().post(
        "/api/hitl/does-not-exist/approve", json={"decision": "approve"}
    )
    assert resp.status_code == 404


def test_resolve_when_not_awaiting_returns_409() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()[
        "project_id"
    ]
    # Immediately after start (before any gate) there is nothing to resolve yet;
    # give the run a moment by reading the snapshot until it settles at a gate,
    # then approve twice — the third approve has nothing pending.
    with client.websocket_connect(f"/api/projects/{pid}/stream") as ws:
        while True:
            ev = ws.receive_json()
            if ev["type"] == "hitl_request":
                client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
            if ev["type"] == "completed":
                break
    resp = client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
    assert resp.status_code == 409
