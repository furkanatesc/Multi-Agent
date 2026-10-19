"""Tests for the keyless demo graph (Sprint 8, PR-A)."""

from __future__ import annotations

from langgraph.types import Command

from src.orchestrator.demo import build_demo_graph
from src.orchestrator.state import UserRequest, create_initial_state


def _config(pid: str) -> dict:
    return {"configurable": {"thread_id": pid}}


def test_demo_run_pauses_at_both_gates_then_completes() -> None:
    graph = build_demo_graph(delay=0.0)
    initial = create_initial_state(UserRequest(prompt="demo app"), project_id="d1")

    # First segment: runs until the security HITL interrupt.
    r1 = graph.invoke(initial, config=_config("d1"))
    assert r1.get("__interrupt__"), "expected security gate interrupt"
    assert r1["__interrupt__"][0].value["gate_type"] == "security"

    # Approve security → runs until the deploy HITL interrupt.
    r2 = graph.invoke(Command(resume={"decision": "approve"}), config=_config("d1"))
    assert r2.get("__interrupt__"), "expected deploy gate interrupt"
    assert r2["__interrupt__"][0].value["gate_type"] == "deploy"

    # Approve deploy → completes.
    r3 = graph.invoke(Command(resume={"decision": "approve"}), config=_config("d1"))
    assert not r3.get("__interrupt__")
    assert r3["status"] == "completed"
    assert r3["architecture_spec"] is not None
    assert r3["source_code"]  # non-empty
    assert r3["review_decision"] == "PASS"


def test_demo_run_needs_no_api_keys_or_docker() -> None:
    # Building + running must not import agent LLM clients or touch Docker.
    graph = build_demo_graph(delay=0.0)
    out = graph.invoke(
        create_initial_state(UserRequest(prompt="x"), project_id="d2"),
        config=_config("d2"),
    )
    # Pauses at the first gate without any network/LLM call.
    assert out["__interrupt__"][0].value["gate_type"] == "security"
