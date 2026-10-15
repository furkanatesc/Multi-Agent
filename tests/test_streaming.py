"""Tests for event conversion + background stream drivers (Sprint 8, PR-A)."""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from src.api.run_manager import RunManager
from src.api.streaming import chunk_to_events, resume_pipeline, run_pipeline
from src.orchestrator.demo import build_demo_graph
from src.orchestrator.state import UserRequest, create_initial_state


def test_chunk_to_events_node_chunk() -> None:
    chunk = {
        "architect": {
            "messages": [AIMessage(content="[architect] hi", name="architect")],
            "architecture_spec": {"project_name": "X"},
            "total_cost_usd": 0.01,
            "iteration_count": 1,
            "status": "coding",
        }
    }
    events = chunk_to_events(chunk)
    types = [e["type"] for e in events]
    assert "log" in types and "node" in types
    node_ev = next(e for e in events if e["type"] == "node")
    assert node_ev["node"] == "architect"
    assert node_ev["state_delta"]["status"] == "coding"
    log_ev = next(e for e in events if e["type"] == "log")
    assert log_ev["line"] == "[architect] hi"


def test_chunk_to_events_interrupt_chunk() -> None:
    class _I:
        value = {"gate_type": "security", "question": "?"}

    events = chunk_to_events({"__interrupt__": (_I(),)})
    expected = [
        {
            "type": "hitl_request",
            "gate_type": "security",
            "payload": {"gate_type": "security", "question": "?"},
        }
    ]
    assert events == expected


def test_run_and_resume_pipeline_drives_demo_to_completion() -> None:
    async def scenario() -> list[dict]:
        mgr = RunManager()
        graph = build_demo_graph(delay=0.0)
        rec = mgr.create("s1", "demo", "demo app")
        cfg = {"configurable": {"thread_id": "s1"}}
        initial = create_initial_state(UserRequest(prompt="demo app"), project_id="s1")

        await run_pipeline(mgr, rec, graph, initial, cfg)
        assert rec.awaiting_hitl is True
        assert rec.hitl_payload["gate_type"] == "security"

        await resume_pipeline(mgr, rec, graph, {"decision": "approve"}, cfg)
        assert rec.awaiting_hitl is True
        assert rec.hitl_payload["gate_type"] == "deploy"

        await resume_pipeline(mgr, rec, graph, {"decision": "approve"}, cfg)
        assert rec.closed is True
        assert rec.status == "completed"
        return rec.events

    events = asyncio.run(scenario())
    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert "hitl_request" in types
    assert "hitl_resolved" in types
    assert types[-1] == "completed"


def test_resume_pipeline_reject_at_deploy_gate_reaches_failed_terminal() -> None:
    async def scenario() -> tuple[bool, str, dict]:
        mgr = RunManager()
        graph = build_demo_graph(delay=0.0)
        rec = mgr.create("s2", "demo", "demo app")
        cfg = {"configurable": {"thread_id": "s2"}}
        initial = create_initial_state(UserRequest(prompt="demo app"), project_id="s2")

        await run_pipeline(mgr, rec, graph, initial, cfg)
        assert rec.hitl_payload["gate_type"] == "security"

        await resume_pipeline(mgr, rec, graph, {"decision": "approve"}, cfg)
        assert rec.hitl_payload["gate_type"] == "deploy"

        await resume_pipeline(mgr, rec, graph, {"decision": "reject"}, cfg)
        return rec.closed, rec.status, rec.events[-1]

    closed, status, last_event = asyncio.run(scenario())
    assert closed is True
    assert status == "failed"
    assert last_event["type"] == "completed"
    assert last_event["status"] == "failed"


def test_drive_stream_worker_exception_resolves_run_as_failed() -> None:
    class _RaisingGraph:
        def stream(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("boom: simulated LLM/Docker failure")

        def get_state(self, config: object) -> object:  # pragma: no cover - unused
            raise AssertionError("get_state should not be called on failure path")

    async def scenario() -> tuple[bool, str, dict]:
        mgr = RunManager()
        rec = mgr.create("s3", "demo", "demo app")
        cfg = {"configurable": {"thread_id": "s3"}}

        await run_pipeline(mgr, rec, _RaisingGraph(), {}, cfg)
        return rec.closed, rec.status, rec.events[-1]

    closed, status, last_event = asyncio.run(scenario())
    assert closed is True
    assert status == "failed"
    assert last_event["type"] == "completed"
    assert last_event["status"] == "failed"
    assert "boom" in last_event["error"]
