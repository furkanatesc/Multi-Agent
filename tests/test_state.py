"""Unit tests for state reducers and boundary models."""

import operator

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from src.orchestrator.state import (
    AgentResponse,
    UserRequest,
    build_response,
    create_initial_state,
    merge_source_code,
)


def test_merge_source_code_combines_files() -> None:
    """New files are folded into the accumulated map."""
    left = {"a.py": "1"}
    right = {"b.py": "2"}
    assert merge_source_code(left, right) == {"a.py": "1", "b.py": "2"}


def test_merge_source_code_overwrites_regenerated_file() -> None:
    """A regenerated file (same path) wins."""
    assert merge_source_code({"a.py": "old"}, {"a.py": "new"}) == {"a.py": "new"}


def test_merge_source_code_handles_none() -> None:
    """None on either side is treated as an empty map."""
    assert merge_source_code(None, None) == {}
    assert merge_source_code(None, {"a.py": "1"}) == {"a.py": "1"}
    assert merge_source_code({"a.py": "1"}, None) == {"a.py": "1"}


def test_add_messages_reducer_appends() -> None:
    """The messages channel appends via add_messages."""
    base = [HumanMessage(content="hi")]
    merged = add_messages(base, [AIMessage(content="hello")])
    assert len(merged) == 2


def test_operator_add_reducers_accumulate() -> None:
    """Cost/iteration channels accumulate with operator.add."""
    assert operator.add(0.0, 0.01) == pytest.approx(0.01)
    assert operator.add(2, 1) == 3


def test_create_initial_state_seeds_reducer_channels() -> None:
    """Initial state seeds accumulator channels with concrete zero values."""
    req = UserRequest(prompt="Build a todo app", platform="flutter")
    state = create_initial_state(req, project_id="p1")

    assert state["project_id"] == "p1"
    assert state["prompt"] == "Build a todo app"
    assert state["platform"] == "flutter"
    assert state["total_cost_usd"] == 0.0
    assert state["iteration_count"] == 0
    assert state["source_code"] == {}
    assert state["inner_loop_count"] == 0
    assert state["outer_loop_count"] == 0
    assert state["status"] == "pending"
    assert state["messages"] == []


def test_user_request_rejects_empty_prompt() -> None:
    """Boundary validation: prompt must be non-empty."""
    with pytest.raises(ValidationError):
        UserRequest(prompt="")


def test_user_request_rejects_invalid_platform() -> None:
    """Boundary validation: platform must be one of the supported literals."""
    with pytest.raises(ValidationError):
        UserRequest(prompt="x", platform="cobol-mobile")  # type: ignore[arg-type]


def test_user_request_rejects_non_positive_budget() -> None:
    """Boundary validation: max_cost_usd must be > 0 when provided."""
    with pytest.raises(ValidationError):
        UserRequest(prompt="x", max_cost_usd=0)


def test_build_response_projects_state() -> None:
    """build_response maps inner state onto the external boundary model."""
    req = UserRequest(prompt="Build a chat app")
    state = create_initial_state(req, project_id="p2")
    state["status"] = "completed"
    state["total_cost_usd"] = 0.42
    state["iteration_count"] = 7
    state["source_code"] = {"src/App.tsx": "// code"}
    state["security_score"] = 88
    state["review_decision"] = "PASS"

    resp = build_response(state)

    assert isinstance(resp, AgentResponse)
    assert resp.project_id == "p2"
    assert resp.status == "completed"
    assert resp.total_cost_usd == pytest.approx(0.42)
    assert resp.iteration_count == 7
    assert resp.source_code == {"src/App.tsx": "// code"}
    assert resp.security_score == 88
    assert resp.review_decision == "PASS"


def test_build_response_handles_partial_state() -> None:
    """build_response reads defensively from a near-empty state."""
    resp = build_response({})  # type: ignore[arg-type]
    assert resp.status == "pending"
    assert resp.total_cost_usd == 0.0
    assert resp.source_code == {}
    assert resp.project_id is None
