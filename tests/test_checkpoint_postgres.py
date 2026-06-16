"""Live PostgreSQL checkpointing integration test.

Marked ``integration``: it requires a reachable PostgreSQL (e.g.
``docker-compose up -d postgres``). When the database is unreachable the test
*skips* rather than fails, so the default ``pytest`` run stays green in
environments without Docker (CI unit stage, contributor laptops).

What it proves (the core Sprint 2 acceptance criterion): graph state written
through a ``PostgresSaver`` is durably persisted and can be restored by a
*separate* graph + checkpointer instance — i.e. real DB persistence, not the
in-process memory saver used by the unit tests.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.orchestrator.graph import build_graph
from src.orchestrator.state import UserRequest, create_initial_state

pytestmark = pytest.mark.integration


def _postgres_checkpointer_or_skip(setup: bool) -> Any:
    """Return a PostgresSaver, or skip the test if Postgres is unreachable."""
    try:
        from src.db.session import get_postgres_checkpointer

        return get_postgres_checkpointer(setup=setup)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not available for integration test: {exc}")


def test_postgres_checkpoint_persists_and_restores() -> None:
    """A run's final state survives in Postgres and restores via a fresh saver."""
    thread_id = f"it-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    # 1) Run the graph to completion with a Postgres-backed checkpointer.
    writer_graph = build_graph(checkpointer=_postgres_checkpointer_or_skip(setup=True))
    final = writer_graph.invoke(
        create_initial_state(UserRequest(prompt="Build a notes app"), project_id="it1"),
        config=config,
    )
    assert final["status"] == "completed"
    assert final["iteration_count"] == 8

    # 2) Restore via a brand-new graph + checkpointer (no shared in-memory state).
    reader_graph = build_graph(checkpointer=_postgres_checkpointer_or_skip(setup=False))
    snapshot = reader_graph.get_state(config)

    assert snapshot.values["status"] == "completed"
    assert snapshot.values["iteration_count"] == 8
    assert snapshot.values["total_cost_usd"] == pytest.approx(0.08)
    assert "src/App.stub.txt" in snapshot.values["source_code"]
