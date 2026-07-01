"""In-memory registry of pipeline runs with per-run event history (Sprint 8).

A :class:`RunRecord` holds the append-only event log for one run plus an
``asyncio.Condition`` used to notify WebSocket observers. Late-joining or
reconnecting clients replay ``events`` from index 0 and then ``wait`` on the
condition for new events; multiple clients can observe the same run.

Single-process only (spec §6): the registry lives in the FastAPI app instance.
Production multi-worker scaling (PostgresSaver + external pub/sub) is deferred.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

RunMode = Literal["real", "demo"]


class RunRecord:
    """Mutable state + event log for a single pipeline run."""

    def __init__(self, project_id: str, mode: RunMode, prompt: str) -> None:
        self.project_id = project_id
        self.mode: RunMode = mode
        self.prompt = prompt
        self.status: str = "pending"
        self.events: list[dict[str, Any]] = []
        self.condition = asyncio.Condition()
        self.awaiting_hitl: bool = False
        self.hitl_payload: Optional[dict[str, Any]] = None
        self.closed: bool = False
        self.task: Optional[asyncio.Task[Any]] = None

    def summary(self) -> dict[str, Any]:
        """Compact projection for the run-list endpoint."""
        return {
            "project_id": self.project_id,
            "mode": self.mode,
            "prompt": self.prompt,
            "status": self.status,
            "awaiting_hitl": self.awaiting_hitl,
            "event_count": len(self.events),
        }


class RunManager:
    """Process-wide registry of :class:`RunRecord` keyed by ``project_id``."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(self, project_id: str, mode: RunMode, prompt: str) -> RunRecord:
        record = RunRecord(project_id, mode, prompt)
        self._runs[project_id] = record
        return record

    def get(self, project_id: str) -> Optional[RunRecord]:
        return self._runs.get(project_id)

    def list_summaries(self) -> list[dict[str, Any]]:
        return [record.summary() for record in self._runs.values()]

    async def append(self, record: RunRecord, event: dict[str, Any]) -> None:
        """Append an event and wake all observers."""
        async with record.condition:
            record.events.append(event)
            record.condition.notify_all()

    async def set_awaiting(
        self, record: RunRecord, payload: Optional[dict[str, Any]], status: str
    ) -> None:
        """Flip the run's awaiting-HITL flags and wake observers."""
        async with record.condition:
            record.awaiting_hitl = payload is not None
            record.hitl_payload = payload
            record.status = status
            record.condition.notify_all()

    async def mark_closed(self, record: RunRecord) -> None:
        """Mark the run terminal (completed/failed) and wake observers."""
        async with record.condition:
            record.closed = True
            record.condition.notify_all()
