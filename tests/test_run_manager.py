"""Unit tests for the in-memory RunManager / RunRecord (Sprint 8, PR-A)."""

from __future__ import annotations

import asyncio

import pytest

from src.api.run_manager import RunManager


def test_create_and_get_roundtrip() -> None:
    mgr = RunManager()
    rec = mgr.create("p1", "demo", "build a todo app")
    assert rec.project_id == "p1"
    assert rec.mode == "demo"
    assert rec.status == "pending"
    assert rec.events == []
    assert mgr.get("p1") is rec
    assert mgr.get("missing") is None


def test_list_summaries_shape() -> None:
    mgr = RunManager()
    mgr.create("p1", "demo", "one")
    mgr.create("p2", "real", "two")
    summaries = {s["project_id"]: s for s in mgr.list_summaries()}
    assert summaries["p1"]["mode"] == "demo"
    assert summaries["p2"]["prompt"] == "two"
    assert summaries["p1"]["event_count"] == 0
    assert summaries["p1"]["awaiting_hitl"] is False


@pytest.mark.asyncio
async def test_append_notifies_waiters() -> None:
    mgr = RunManager()
    rec = mgr.create("p1", "demo", "x")

    async def waiter() -> dict:
        async with rec.condition:
            await rec.condition.wait_for(lambda: len(rec.events) > 0)
            return rec.events[0]

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # let the waiter start waiting
    await mgr.append(rec, {"type": "log", "line": "hi"})
    got = await asyncio.wait_for(task, timeout=1.0)
    assert got == {"type": "log", "line": "hi"}


@pytest.mark.asyncio
async def test_mark_closed_and_set_awaiting() -> None:
    mgr = RunManager()
    rec = mgr.create("p1", "demo", "x")
    await mgr.set_awaiting(rec, {"gate_type": "security"}, "awaiting_hitl")
    assert rec.awaiting_hitl is True
    assert rec.hitl_payload == {"gate_type": "security"}
    assert rec.status == "awaiting_hitl"
    await mgr.mark_closed(rec)
    assert rec.closed is True
