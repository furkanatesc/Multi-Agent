"""Bridge the (blocking) LangGraph stream onto the asyncio event loop (Sprint 8).

``graph.stream(..., stream_mode="updates")`` is synchronous and blocking, so it
is driven inside a worker thread (``asyncio.to_thread``). Each chunk is converted
to WebSocket events and handed back to the loop via ``run_coroutine_threadsafe``
so the :class:`RunManager` condition wakes any observers immediately (spec §4.1).

A run streams until it either (a) hits a HITL ``__interrupt__`` — the stream ends
and the run is left ``awaiting_hitl`` for the checkpointer to resume — or (b) runs
to completion, at which point the record is marked closed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.types import Command

from src.api.run_manager import RunManager, RunRecord

# State channels that are JSON-safe and useful to surface to the UI.
_SAFE_KEYS = (
    "status",
    "security_score",
    "security_critical",
    "review_decision",
    "review_notes",
    "lint_passed",
    "tests_passed",
    "total_cost_usd",
    "iteration_count",
    "inner_loop_count",
    "outer_loop_count",
    "architecture_spec",
    "platform",
    "error",
)


def _safe_delta(delta: dict[str, Any]) -> dict[str, Any]:
    """Project a node's partial-state update onto JSON-serializable fields."""
    safe: dict[str, Any] = {k: delta[k] for k in _SAFE_KEYS if k in delta}
    if "source_code" in delta and isinstance(delta["source_code"], dict):
        safe["source_files"] = sorted(delta["source_code"].keys())
    return safe


def chunk_to_events(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one ``stream_mode="updates"`` chunk into WS event dicts."""
    if "__interrupt__" in chunk:
        payload = chunk["__interrupt__"][0].value
        return [
            {
                "type": "hitl_request",
                "gate_type": payload.get("gate_type"),
                "payload": payload,
            }
        ]

    events: list[dict[str, Any]] = []
    for node_name, delta in chunk.items():
        if not isinstance(delta, dict):
            continue
        for msg in delta.get("messages", []) or []:
            line = getattr(msg, "content", None)
            if line:
                events.append({"type": "log", "line": str(line)})
        events.append(
            {
                "type": "node",
                "node": node_name,
                "status": "complete",
                "state_delta": _safe_delta(delta),
            }
        )
    return events


async def _drive_stream(
    manager: RunManager,
    record: RunRecord,
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
) -> None:
    """Run ``graph.stream`` in a thread; append converted events to the record.

    Sets ``awaiting_hitl`` when the segment ends on an interrupt, otherwise marks
    the record closed (completed/failed). If the worker thread raises (e.g. a
    real-mode LLM/Docker/auth error), the run is still resolved to a terminal
    ``failed`` state with a ``completed`` event, so no WebSocket observer blocked
    on ``record.condition`` hangs forever.
    """
    loop = asyncio.get_running_loop()
    saw_interrupt: dict[str, Any] = {}

    def _emit(coro: Any) -> None:
        asyncio.run_coroutine_threadsafe(coro, loop).result()

    def _worker() -> None:
        for chunk in graph.stream(graph_input, config=config, stream_mode="updates"):
            for event in chunk_to_events(chunk):
                if event["type"] == "hitl_request":
                    saw_interrupt["payload"] = event["payload"]
                _emit(manager.append(record, event))

    try:
        await asyncio.to_thread(_worker)
    except Exception as exc:  # noqa: BLE001 - any stream failure must resolve the run
        await manager.set_awaiting(record, None, "failed")
        await manager.append(
            record, {"type": "completed", "status": "failed", "error": str(exc)}
        )
        await manager.mark_closed(record)
        return

    if saw_interrupt:
        await manager.set_awaiting(
            record, saw_interrupt["payload"], "awaiting_hitl"
        )
    else:
        snapshot = graph.get_state(config)
        status = (
            snapshot.values.get("status", "completed")
            if snapshot.values
            else "completed"
        )
        await manager.set_awaiting(record, None, status)
        await manager.append(record, {"type": "completed", "status": status})
        await manager.mark_closed(record)


async def run_pipeline(
    manager: RunManager,
    record: RunRecord,
    graph: Any,
    initial: Any,
    config: dict[str, Any],
) -> None:
    """Start a fresh run: emit ``run_started`` then stream to the first pause."""
    await manager.append(
        record,
        {"type": "run_started", "project_id": record.project_id, "mode": record.mode},
    )
    await _drive_stream(manager, record, graph, initial, config)


async def resume_pipeline(
    manager: RunManager,
    record: RunRecord,
    graph: Any,
    resume: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Resume a paused run with a human decision, then stream to the next pause."""
    await manager.append(
        record,
        {
            "type": "hitl_resolved",
            "gate_type": (record.hitl_payload or {}).get("gate_type"),
            "decision": resume.get("decision"),
        },
    )
    await manager.set_awaiting(record, None, record.status)
    await _drive_stream(manager, record, graph, Command(resume=resume), config)
