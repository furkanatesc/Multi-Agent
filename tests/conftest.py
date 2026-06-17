"""Shared pytest fixtures.

The architect stub below is autouse so that *any* test which invokes the
orchestration graph runs offline and deterministically — the real, LLM-backed
``ArchitectAgent`` is exercised directly (with a mock client) in
``tests/test_architect.py``. It only patches the symbol used by the graph node
(``orchestrator.nodes.ArchitectAgent``), so tests that construct the agent
directly are unaffected.
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.orchestrator.state import AgentState


@pytest.fixture(autouse=True)
def _stub_architect_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the graph's ArchitectAgent with a deterministic offline stub.

    Mirrors a single node's contribution (one message, +1 iteration, +0.01 cost)
    so accumulator assertions in the graph tests hold.
    """

    class _FakeArchitect:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            ...

        def run(self, state: AgentState) -> dict[str, Any]:
            return {
                "messages": [AIMessage(content="[architect] stub ADR", name="architect")],
                "architecture_spec": {
                    "project_name": "TestApp",
                    "tech_stack": {"platform": "react-native"},
                },
                "platform": "react-native",
                "total_cost_usd": 0.01,
                "iteration_count": 1,
                "status": "coding",
                "next_agent": "coder",
            }

    monkeypatch.setattr("src.orchestrator.nodes.ArchitectAgent", _FakeArchitect)


@pytest.fixture(autouse=True)
def _stub_coder_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the graph's CoderAgent with a deterministic offline stub.

    Mirrors a single node's contribution (one message, +1 iteration, +0.01 cost)
    and emits a placeholder source file with the lint/test flags reset, matching
    the real agent's routing into the inner loop. Tests that exercise the real,
    tool-using ``CoderAgent`` do so directly (with a mock client) in
    ``tests/test_coder.py``; this only patches the symbol used by the graph node.
    """

    class _FakeCoder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            ...

        def run(self, state: AgentState) -> dict[str, Any]:
            return {
                "messages": [AIMessage(content="[coder] stub module", name="coder")],
                "source_code": {"src/App.stub.txt": "// stub generated module"},
                "lint_passed": None,
                "tests_passed": None,
                "total_cost_usd": 0.01,
                "iteration_count": 1,
                "status": "inner_loop",
                "next_agent": "inner_loop_check",
            }

    monkeypatch.setattr("src.orchestrator.nodes.CoderAgent", _FakeCoder)
