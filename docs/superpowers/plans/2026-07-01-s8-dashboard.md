# Sprint 8 — Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a live web dashboard over the multi-agent pipeline — start a build from a prompt, watch the agent graph execute in real time over WebSocket, approve/reject the HITL gates from the UI, and inspect ADR / code / security / review / logs / cost — with a keyless `mode=demo`.

**Architecture:** Two deliverables sharing one design doc. **PR-A** adds a streaming layer to the existing FastAPI app: an in-process `RunManager` holds per-run event history guarded by an `asyncio.Condition`; the (blocking) `graph.stream(...)` runs in a worker thread and pushes converted events onto the loop via `run_coroutine_threadsafe`; WebSocket clients replay history from index 0 then follow live. A keyless `build_demo_graph()` mirrors the real topology with stub agent nodes + real HITL gates so the whole UI is demoable without API keys or Docker. **PR-B** adds a Vue 3 + Vite + Pinia SPA under `frontend/` that mirrors the user's SQLGen project (Three.js/GSAP/d3 aesthetic), with a hero live `AgentGraph`.

**Tech Stack:** Backend — FastAPI, LangGraph `graph.stream(stream_mode="updates")`, `asyncio` (Condition + `to_thread` + `run_coroutine_threadsafe`), Starlette WebSockets, pytest + `TestClient.websocket_connect`. Frontend — Vue 3.5 (TS strict), Vite, Pinia, Tailwind 3, d3, gsap, three, lenis, vue-tsc.

## Global Constraints

- **LangGraph >= 1.0.10**, **LiteLLM >= 1.50** (in-process, no proxy) — unchanged.
- **Backend gates:** `pytest` green, `mypy src/ --strict` clean, `ruff check .` clean on new code. Copy existing module style (module docstring, `from __future__ import annotations`, typed signatures, structlog `logger`).
- **Frontend gate:** `cd frontend && npm ci && npm run build` (runs `vue-tsc -b` type-check then `vite build`) must pass. TypeScript strict.
- **Framework decision (locked):** Vue 3 + Vite + Pinia. NOT React. Charts = d3/SVG, NOT Recharts. (Overrides the PR#11 sprint plan; see memory `dashboard-design-direction` and the design spec §2.)
- **Two branches:** `feature/s8a-dashboard-backend` (PR-A) merged first, then `feature/s8b-dashboard-frontend` (PR-B) branched off `develop` after PR-A merges.
- **Single-process / in-memory** `RunManager` + in-memory checkpointer is accepted (spec §6). No auth, no persisted history across restarts, read-only code viewing (spec §7).
- **Contract change (accepted, spec §4.4):** `POST /api/projects` becomes async-start (returns `{project_id, mode}` immediately and runs in the background) instead of returning the finished/paused state synchronously. Existing `test_api.py` HITL tests are updated to the new contract in Task A5.
- **Update living docs in the same session** (CLAUDE.md rule): `CHANGELOG.md` at each PR closure; `cache.md` resume pointer; memory as decisions land.
- **Reference project (read-only, do not modify):** `C:\Users\furkan\Desktop\SQLGen\frontend` — reuse `src/style.css`, `tailwind.config.js`, `src/components/SpaceSpiderweb.vue`, `src/services/api.ts` as adaptation sources.

---

# PR-A — Backend streaming layer (`feature/s8a-dashboard-backend`, pytest-gated)

Branch setup (run once before Task A1):

```bash
git checkout develop && git pull
git checkout -b feature/s8a-dashboard-backend
```

## File map (PR-A)

- Create `src/api/run_manager.py` — `RunRecord` + `RunManager` (in-memory registry, event history, `asyncio.Condition`).
- Create `src/api/streaming.py` — event conversion (`chunk_to_events`, `_safe_delta`) + background drivers (`run_pipeline`, `resume_pipeline`).
- Create `src/orchestrator/demo.py` — `build_demo_graph(delay=0.5)` (stub agent nodes + real HITL gates, forces both gates).
- Modify `src/core/config.py` — add `CORS_ORIGINS` setting.
- Modify `src/api/main.py` — CORS middleware, `RunManager` wiring, async-start `POST /api/projects?mode=`, `GET /api/projects`, `GET /api/projects/{id}`, `WS /api/projects/{id}/stream`, resume via `POST /api/hitl/{id}/approve`.
- Create `tests/test_run_manager.py`, `tests/test_demo_graph.py`, `tests/test_streaming.py`.
- Modify `tests/test_api.py` — async-start contract + WS demo-run test.

---

### Task A1: `CORS_ORIGINS` setting + CORS middleware

**Files:**
- Modify: `src/core/config.py:25-27` (add field near `GITHUB_TOKEN`)
- Modify: `src/api/main.py` (add middleware inside `create_app`)
- Test: `tests/test_api.py` (add one test; full file edited in A5)

**Interfaces:**
- Produces: `settings.CORS_ORIGINS: str` (comma-separated origins); `create_app()` app now emits `access-control-allow-origin`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_api.py`:

```python
def test_cors_headers_present() -> None:
    resp = _client().get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_cors_headers_present -v`
Expected: FAIL (no `access-control-allow-origin` header).

- [ ] **Step 3: Add the setting.** In `src/core/config.py`, after the `GITHUB_TOKEN` line (`:25`) add:

```python
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed frontend origins for CORS.",
    )
```

- [ ] **Step 4: Add the middleware.** In `src/api/main.py`, add the import near the other fastapi import (top of file):

```python
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
```

Then, inside `create_app`, immediately after `app = FastAPI(...)` (before the first `@app.get`), add:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_api.py::test_cors_headers_present -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core/config.py src/api/main.py tests/test_api.py
git commit -m "feat(api): add configurable CORS origins for the dashboard frontend"
```

---

### Task A2: `RunManager` + `RunRecord` (in-memory registry with event history)

**Files:**
- Create: `src/api/run_manager.py`
- Test: `tests/test_run_manager.py`

**Interfaces:**
- Consumes: nothing (pure asyncio + stdlib).
- Produces:
  - `RunMode = Literal["real", "demo"]`
  - `class RunRecord` with attrs: `project_id: str`, `mode: RunMode`, `prompt: str`, `status: str` (defaults `"pending"`), `events: list[dict[str, Any]]`, `condition: asyncio.Condition`, `awaiting_hitl: bool`, `hitl_payload: Optional[dict[str, Any]]`, `closed: bool`, `task: Optional[asyncio.Task[Any]]`.
  - `class RunManager` methods:
    - `create(self, project_id: str, mode: RunMode, prompt: str) -> RunRecord`
    - `get(self, project_id: str) -> Optional[RunRecord]`
    - `list_summaries(self) -> list[dict[str, Any]]` → `[{project_id, mode, prompt, status, awaiting_hitl, event_count}]`
    - `async def append(self, record: RunRecord, event: dict[str, Any]) -> None` (appends + `notify_all`)
    - `async def mark_closed(self, record: RunRecord) -> None` (sets `closed=True` + `notify_all`)
    - `async def set_awaiting(self, record: RunRecord, payload: Optional[dict], status: str) -> None` (sets `awaiting_hitl`/`hitl_payload`/`status` + `notify_all`)

- [ ] **Step 1: Write the failing test** — create `tests/test_run_manager.py`:

```python
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
```

- [ ] **Step 2: Confirm asyncio test support.** Run: `pytest tests/test_run_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.run_manager'`. If instead the async tests are **skipped** with an "async def functions are not natively supported" warning, install the plugin and enable auto mode:

```bash
pip install pytest-asyncio
```

Then add to `pyproject.toml` under the pytest config (create the section if absent):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

If `asyncio_mode = "auto"` is set, remove the `@pytest.mark.asyncio` decorators (auto mode makes them redundant but harmless — leaving them is fine). Re-run to confirm the failure is the import error, not a skip.

- [ ] **Step 3: Write the implementation** — create `src/api/run_manager.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_manager.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/api/run_manager.py tests/test_run_manager.py pyproject.toml
git commit -m "feat(api): add in-memory RunManager with async event history"
```

---

### Task A3: `build_demo_graph()` — keyless mock pipeline

**Files:**
- Create: `src/orchestrator/demo.py`
- Test: `tests/test_demo_graph.py`

**Interfaces:**
- Consumes: `src.orchestrator.state` (`AgentState`, `create_initial_state`, `UserRequest`), `src.orchestrator.edges` (routers), `src.orchestrator.hitl.HITLGate`, `langgraph`.
- Produces: `build_demo_graph(delay: float = 0.5) -> Any` — a compiled graph (InMemorySaver) with the real topology, stub agent nodes, and real HITL gate nodes with `persist=False`. Forces `security_critical=True` so the run pauses at **both** the security and deploy gates.

**Design notes for the implementer:**
- Reuse the pure routers from `src/orchestrator/edges.py` (`cost_check`, `should_continue_inner_loop`, `security_gate`, `hitl_route`, `review_decision`) — they read only state, no LLM.
- Stub nodes return the same partial-state shape the real nodes return (see `src/orchestrator/nodes.py`) but with canned content and a `time.sleep(delay)` to simulate progress. Every node bumps `iteration_count: 1` and a small `total_cost_usd` so the accumulators move.
- The security stub sets `security_critical=True` + `security_score=60` so `edges.security_gate` routes `block_hitl` → the security HITL gate fires. After human approve, the demo inner-loop/security state stays as-is (approve = accept risk) and proceeds to `test_generator`.
- Gate nodes construct `HITLGate("security", persist=False)` / `HITLGate("deploy", persist=False)` (no DB in demo).

- [ ] **Step 1: Write the failing test** — create `tests/test_demo_graph.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demo_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.orchestrator.demo'`.

- [ ] **Step 3: Write the implementation** — create `src/orchestrator/demo.py`:

```python
"""Keyless demo/mock orchestration graph (Sprint 8, PR-A).

Mirrors the real pipeline topology (:mod:`src.orchestrator.graph`) and the
**real** HITL gate mechanics, but replaces every LLM/Docker-backed agent node
with a deterministic stub that emits canned output after a small ``delay``. This
lets the dashboard stream a full run — pausing at both HITL gates — with no API
keys and no Docker (spec §4.3).

The security stub intentionally reports a critical finding so the security HITL
gate fires; the deploy gate always fires after the (stub) PASS review. Gates use
``HITLGate(..., persist=False)`` so no database is required.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.orchestrator import edges
from src.orchestrator.hitl import HITLGate
from src.orchestrator.state import AgentState

_STUB_COST = 0.01


def _make_nodes(delay: float) -> dict[str, Any]:
    """Build the stub node callables, closing over the per-step ``delay``."""

    def _sleep() -> None:
        if delay > 0:
            time.sleep(delay)

    def _msg(name: str, content: str, **updates: Any) -> dict[str, Any]:
        update: dict[str, Any] = {
            "messages": [AIMessage(content=content, name=name)],
            "iteration_count": 1,
            "total_cost_usd": _STUB_COST,
        }
        update.update(updates)
        return update

    def supervisor(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "supervisor",
            "[supervisor] demo run started; dispatching to architect",
            status="architecting",
            next_agent="architect",
        )

    def architect(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "architect",
            "[architect] demo ADR generated",
            architecture_spec={
                "project_name": "DemoApp",
                "tech_stack": {"platform": "react-native"},
                "summary": "A demo mobile app scaffolded by the mock pipeline.",
            },
            platform="react-native",
            status="coding",
            next_agent="coder",
        )

    def coder(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "coder",
            "[coder] demo module written",
            source_code={"src/App.tsx": "// demo generated component\n"},
            lint_passed=None,
            tests_passed=None,
            status="inner_loop",
            next_agent="inner_loop_check",
        )

    def inner_loop_check(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "inner_loop",
            "[inner_loop] demo lint+tests passed (0 self-fix iters)",
            lint_passed=True,
            tests_passed=True,
            inner_loop_count=0,
            status="security_scan",
        )

    def security_scan(state: AgentState) -> dict[str, Any]:
        _sleep()
        # Force the security HITL gate to fire so the full HITL UI is exercised.
        return _msg(
            "security",
            "[security] demo scan: score=60, critical finding requires approval",
            security_score=60,
            security_critical=True,
            status="security_scan",
        )

    def security_gate(state: AgentState) -> dict[str, Any]:
        resolution = HITLGate("security", persist=False).request(state)
        if resolution.approved:
            return {
                "messages": [
                    AIMessage(
                        content="[hitl] security approved — accepting risk",
                        name="hitl",
                    )
                ],
                "iteration_count": 1,
                "status": "test_generation",
                "hitl_decision": "approve",
            }
        return {
            "messages": [
                AIMessage(
                    content="[hitl] security rejected — back to coder", name="hitl"
                )
            ],
            "iteration_count": 1,
            "status": "coding",
            "hitl_decision": "reject",
        }

    def test_generator(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "test_generator",
            "[test_generator] demo tests generated",
            source_code={"src/App.test.tsx": "// demo test\n"},
            tests_passed=True,
            status="test_generation",
        )

    def reviewer(state: AgentState) -> dict[str, Any]:
        _sleep()
        outer = int(state.get("outer_loop_count", 0)) + 1
        return _msg(
            "reviewer",
            "[reviewer] demo review: PASS",
            review_decision="PASS",
            review_notes="LGTM (demo review)",
            outer_loop_count=outer,
            status="review",
        )

    def deploy_gate(state: AgentState) -> dict[str, Any]:
        resolution = HITLGate("deploy", persist=False).request(state)
        if resolution.approved:
            return {
                "messages": [
                    AIMessage(content="[hitl] deploy approved", name="hitl")
                ],
                "iteration_count": 1,
                "status": "deploying",
                "hitl_decision": "approve",
            }
        return {
            "messages": [
                AIMessage(content="[hitl] deploy rejected — aborted", name="hitl")
            ],
            "iteration_count": 1,
            "status": "failed",
            "hitl_decision": "reject",
            "error": "Deployment rejected by human reviewer.",
        }

    def deployer(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "deployer",
            "[deployer] demo deploy complete",
            status="completed",
            next_agent=None,
        )

    return {
        "supervisor": supervisor,
        "architect": architect,
        "coder": coder,
        "inner_loop_check": inner_loop_check,
        "security_scan": security_scan,
        "hitl_gate": security_gate,
        "test_generator": test_generator,
        "reviewer": reviewer,
        "deploy_gate": deploy_gate,
        "deployer": deployer,
    }


def build_demo_graph(delay: float = 0.5) -> Any:
    """Compile the keyless demo graph (InMemorySaver, stub nodes, real gates).

    Args:
        delay: Seconds each stub node sleeps to simulate progress (0 in tests).
    """
    nodes = _make_nodes(delay)
    builder = StateGraph(AgentState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor", edges.cost_check, {"halt": END, "continue": "architect"}
    )
    builder.add_edge("architect", "coder")
    builder.add_edge("coder", "inner_loop_check")
    builder.add_conditional_edges(
        "inner_loop_check",
        edges.should_continue_inner_loop,
        {"fix": "coder", "proceed": "security_scan"},
    )
    builder.add_conditional_edges(
        "security_scan",
        edges.security_gate,
        {"block_hitl": "hitl_gate", "fix": "coder", "proceed": "test_generator"},
    )
    builder.add_conditional_edges(
        "hitl_gate",
        edges.hitl_route,
        {"approve": "test_generator", "reject": "coder"},
    )
    builder.add_edge("test_generator", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        edges.review_decision,
        {"approve": "deploy_gate", "reject": "coder", "escalate": END},
    )
    builder.add_conditional_edges(
        "deploy_gate", edges.hitl_route, {"approve": "deployer", "reject": END}
    )
    builder.add_edge("deployer", END)

    return builder.compile(checkpointer=InMemorySaver())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_demo_graph.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/demo.py tests/test_demo_graph.py
git commit -m "feat(orchestrator): add keyless demo graph (stub agents, real HITL gates)"
```

---

### Task A4: Event conversion + background stream drivers

**Files:**
- Create: `src/api/streaming.py`
- Test: `tests/test_streaming.py`

**Interfaces:**
- Consumes: `RunManager`/`RunRecord` (A2), a compiled graph with `.stream(...)` (A3 or the real graph), `langgraph.types.Command`.
- Produces:
  - `chunk_to_events(chunk: dict[str, Any]) -> list[dict[str, Any]]` — convert one `stream_mode="updates"` chunk into WS events. Interrupt chunk → one `hitl_request`; node chunk → `log` events (one per message) + one `node` event with a JSON-safe `state_delta`.
  - `_safe_delta(delta: dict[str, Any]) -> dict[str, Any]` — pick JSON-safe channels; `source_code` → sorted list of filenames.
  - `async def run_pipeline(manager, record, graph, initial, config) -> None` — emit `run_started`, stream to next pause/completion in a worker thread, convert+append events, set awaiting/closed.
  - `async def resume_pipeline(manager, record, graph, resume, config) -> None` — emit `hitl_resolved`, then stream `Command(resume=resume)` to next pause/completion.

- [ ] **Step 1: Write the failing test** — create `tests/test_streaming.py`:

```python
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
    assert events == [
        {"type": "hitl_request", "gate_type": "security", "payload": {"gate_type": "security", "question": "?"}}
    ]


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_streaming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.streaming'`.

- [ ] **Step 3: Write the implementation** — create `src/api/streaming.py`:

```python
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
    the record closed (completed/failed).
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

    await asyncio.to_thread(_worker)

    if saw_interrupt:
        await manager.set_awaiting(
            record, saw_interrupt["payload"], "awaiting_hitl"
        )
    else:
        snapshot = graph.get_state(config)
        status = snapshot.values.get("status", "completed") if snapshot.values else "completed"
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
        record, {"type": "run_started", "project_id": record.project_id, "mode": record.mode}
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_streaming.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/api/streaming.py tests/test_streaming.py
git commit -m "feat(api): add stream->asyncio event bridge and background run drivers"
```

---

### Task A5: Wire endpoints into the FastAPI app (async-start, list, snapshot, WS, resume)

**Files:**
- Modify: `src/api/main.py`
- Modify: `tests/test_api.py` (rewrite the HITL-lifecycle section for the async-start contract + add the WS demo-run test)

**Interfaces:**
- Consumes: `RunManager` (A2), `run_pipeline`/`resume_pipeline` (A4), `build_demo_graph` (A3), the real `build_graph` (existing).
- Produces: endpoints — `POST /api/projects?mode=real|demo` → `{project_id, mode}`; `GET /api/projects` → `{runs: [...]}`; `GET /api/projects/{id}` → snapshot; `WS /api/projects/{id}/stream`; `POST /api/hitl/{id}/approve` → `{project_id, accepted: true}`.

**Design notes:**
- `create_app` builds the real graph (as today) **and** keeps a `RunManager` + a demo-graph factory. The demo graph is built per-run (each needs its own InMemorySaver thread space is fine, but a single shared demo graph with distinct `thread_id` also works — build one shared demo graph at app creation with `delay` configurable via a module constant `DEMO_DELAY = 0.4`; tests override by monkeypatching or by a query arg — simplest: build per POST with `build_demo_graph(delay=...)`, delay from a small helper that returns 0.0 under tests via an app-state flag). To keep it deterministic and simple: store `app.state.demo_delay` (default `0.4`); tests set it to `0.0`.
- Endpoints that start work are `async def` and use `asyncio.create_task`, storing the task on `record.task`.
- The resume endpoint keeps the existing 404 (unknown) / 409 (nothing pending) semantics but now checks the `RunManager` record's `awaiting_hitl` instead of the graph snapshot.

- [ ] **Step 1: Write the failing tests** — replace the HITL-lifecycle section (everything from the `# HITL run lifecycle` comment at line 50 to end of file) in `tests/test_api.py` with:

```python
# --------------------------------------------------------------------------- #
# Sprint 8 — async-start run lifecycle + streaming.
#
# POST /api/projects now returns {project_id, mode} immediately and runs in the
# background. Tests use mode=demo with delay=0 (deterministic, keyless) and drive
# the flow over the WebSocket, approving each HITL gate via POST.
# --------------------------------------------------------------------------- #


def _demo_client() -> TestClient:
    client = TestClient(create_app())
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
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()["project_id"]
    runs = client.get("/api/projects").json()["runs"]
    assert any(r["project_id"] == pid for r in runs)


def test_ws_streams_full_demo_run_through_both_gates() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "todo"}).json()["project_id"]

    seen_types: list[str] = []
    with client.websocket_connect(f"/api/projects/{pid}/stream") as ws:
        approvals = 0
        while True:
            ev = ws.receive_json()
            seen_types.append(ev["type"])
            if ev["type"] == "hitl_request":
                client.post(f"/api/hitl/{pid}/approve", json={"decision": "approve"})
                approvals += 1
            if ev["type"] == "completed":
                break
    assert seen_types[0] == "run_started"
    assert seen_types.count("hitl_request") == 2  # security + deploy
    assert approvals == 2
    assert seen_types[-1] == "completed"


def test_snapshot_reports_awaiting_after_first_gate() -> None:
    client = _demo_client()
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()["project_id"]
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
    pid = client.post("/api/projects?mode=demo", json={"prompt": "x"}).json()["project_id"]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL (the new endpoints / query param / WS route don't exist; the old sync tests are gone).

- [ ] **Step 3: Rewrite `src/api/main.py`.** Replace the whole file with:

```python
"""FastAPI application: observability + streaming run lifecycle (Sprint 7-8).

Built by :func:`create_app` (fresh instance + checkpointer per test) and exposed
as module-level ``app`` for ``uvicorn src.api.main:app``.

Run lifecycle (Sprint 8): ``POST /api/projects?mode=real|demo`` starts a run in
the background and returns ``{project_id, mode}`` immediately. The run streams
over ``WS /api/projects/{id}/stream`` (history replay + live). HITL gates pause
the run; ``POST /api/hitl/{id}/approve`` resumes it. ``mode=demo`` uses a keyless
stub graph so the dashboard is demoable without API keys or Docker.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.api.run_manager import RunManager, RunRecord
from src.api.streaming import resume_pipeline, run_pipeline
from src.core.config import settings
from src.db.session import get_memory_checkpointer
from src.observability import metrics
from src.observability.langsmith_tracer import configure_tracing, is_tracing_enabled
from src.orchestrator.demo import build_demo_graph
from src.orchestrator.graph import build_graph
from src.orchestrator.state import UserRequest, create_initial_state

_DEFAULT_DEMO_DELAY = 0.4


class HITLResolveRequest(BaseModel):
    """Human decision used to resume a paused run at a HITL gate."""

    decision: Literal["approve", "reject"] = Field(default="approve")
    feedback: Optional[str] = Field(default=None)


def _thread_config(project_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": project_id}}


def create_app(checkpointer: Optional[Any] = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    configure_tracing()
    real_graph = build_graph(checkpointer=checkpointer or get_memory_checkpointer())
    manager = RunManager()

    app = FastAPI(
        title="Multi-Agent Mobile App Development System",
        description="Autonomous multi-agent pipeline API.",
        version="0.6.0",
    )
    app.state.demo_delay = _DEFAULT_DEMO_DELAY

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return {"status": "ok", "tracing": is_tracing_enabled()}

    @app.get("/metrics", tags=["system"])
    def prometheus_metrics() -> Response:
        payload, content_type = metrics.render()
        return Response(content=payload, media_type=content_type)

    @app.post("/api/projects", tags=["pipeline"])
    async def start_project(
        request: UserRequest, mode: Literal["real", "demo"] = "real"
    ) -> dict[str, Any]:
        """Start a run in the background; return its id + mode immediately."""
        import asyncio

        project_id = str(uuid4())
        record = manager.create(project_id, mode, request.prompt)
        config = _thread_config(project_id)
        initial = create_initial_state(request, project_id=project_id)
        if mode == "demo":
            graph = build_demo_graph(delay=app.state.demo_delay)
        else:
            graph = real_graph
        record.task = asyncio.create_task(
            run_pipeline(manager, record, graph, initial, config)
        )
        # Remember the graph for resume (demo graphs are per-run).
        record_graphs[project_id] = graph
        return {"project_id": project_id, "mode": mode}

    @app.get("/api/projects", tags=["pipeline"])
    def list_projects() -> dict[str, Any]:
        return {"runs": manager.list_summaries()}

    @app.get("/api/projects/{project_id}", tags=["pipeline"])
    def get_project(project_id: str) -> dict[str, Any]:
        record = manager.get(project_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown project '{project_id}'.")
        return {
            "project_id": record.project_id,
            "mode": record.mode,
            "prompt": record.prompt,
            "status": record.status,
            "awaiting_hitl": record.awaiting_hitl,
            "hitl": record.hitl_payload,
            "event_count": len(record.events),
        }

    @app.websocket("/api/projects/{project_id}/stream")
    async def stream(websocket: WebSocket, project_id: str) -> None:
        await websocket.accept()
        record = manager.get(project_id)
        if record is None:
            await websocket.close(code=4004)
            return
        idx = 0
        try:
            while True:
                async with record.condition:
                    await record.condition.wait_for(
                        lambda: len(record.events) > idx or record.closed
                    )
                    pending = record.events[idx:]
                    idx = len(record.events)
                    closed = record.closed
                for event in pending:
                    await websocket.send_json(event)
                if closed and idx >= len(record.events):
                    break
        except WebSocketDisconnect:
            return

    @app.post("/api/hitl/{project_id}/approve", tags=["pipeline"])
    async def resolve_hitl(
        project_id: str, body: HITLResolveRequest
    ) -> dict[str, Any]:
        import asyncio

        record = manager.get(project_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown project '{project_id}'.")
        if not record.awaiting_hitl:
            raise HTTPException(
                status_code=409, detail="No pending HITL approval for this project."
            )
        graph = record_graphs[project_id]
        config = _thread_config(project_id)
        record.task = asyncio.create_task(
            resume_pipeline(manager, record, graph, body.model_dump(), config)
        )
        return {"project_id": project_id, "accepted": True}

    # Per-app map of project_id -> compiled graph (demo graphs are per-run).
    record_graphs: dict[str, Any] = {}

    return app


app = create_app()
```

Note: move the `record_graphs: dict[str, Any] = {}` declaration **above** `start_project` (put it right after `manager = RunManager()`), so both endpoints close over it. Fix that ordering when you paste — the executor MUST define `record_graphs` before the endpoint functions that reference it.

- [ ] **Step 4: Run the full API test file**

Run: `pytest tests/test_api.py -v`
Expected: PASS (health/metrics + the 6 new lifecycle/WS tests). If a WS test hangs, confirm `app.state.demo_delay` is `0.0` in `_demo_client` and that `run_pipeline` emits `completed` (Task A4).

- [ ] **Step 5: Run the whole suite + type/lint gates**

Run:
```bash
pytest -q
mypy src/ --strict
ruff check .
```
Expected: all green (previous 223 + the new PR-A tests). `mypy` clean on new files. `ruff` clean on new code.

- [ ] **Step 6: Update living docs.**
- `CHANGELOG.md`: under `## [Unreleased]` add an `### Added` entry: "Sprint 8 PR-A — dashboard streaming backend: `RunManager`, WS `/api/projects/{id}/stream`, async-start `POST /api/projects?mode=`, keyless demo graph."
- Note the `POST /api/projects` contract change under a `### Changed` subsection.

- [ ] **Step 7: Commit + open PR**

```bash
git add src/api/main.py tests/test_api.py CHANGELOG.md
git commit -m "feat(api): async-start runs, list/snapshot endpoints, WS streaming, demo mode"
git push -u origin feature/s8a-dashboard-backend
```

**STOP — user gate:** Do not open/merge the PR without the user. Tell the user PR-A is pushed and green; ask them to review/merge (branch protection is off; the user merges via web UI or authorizes `gh pr create`).

---

# PR-B — Vue dashboard (`feature/s8b-dashboard-frontend`, build/type-check gated)

**Prerequisite:** PR-A merged to `develop`. Then:

```bash
git checkout develop && git pull
git checkout -b feature/s8b-dashboard-frontend
```

Node.js 20+ and npm required locally. All commands below run from the repo root unless a `cd frontend` is shown.

## File map (PR-B)

```
frontend/
  package.json  vite.config.ts  tsconfig.json  tsconfig.node.json
  tailwind.config.js  postcss.config.js  index.html  .gitignore
  src/
    main.ts  App.vue  style.css  vite-env.d.ts
    types.ts
    services/api.ts
    stores/projects.ts
    composables/useWebSocket.ts
    components/ProjectForm.vue  ProjectList.vue  AgentGraph.vue
               HITLPanel.vue    TerminalLogs.vue MetricCards.vue
.github/workflows/ci.yml   # add a frontend job
```

---

### Task B1: Scaffold `frontend/` (build/type-check gate green on an empty app)

**Files:** create all config files + a minimal `App.vue`/`main.ts`/`style.css` that type-check and build.

**Interfaces:** Produces a `frontend/` that passes `npm ci && npm run build`. The dev server proxies `/api` and `/ws` → `http://localhost:8000`.

- [ ] **Step 1: Create `frontend/package.json`:**

```json
{
  "name": "multi-agent-dashboard",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "d3": "^7.9.0",
    "gsap": "^3.12.5",
    "lenis": "^1.1.13",
    "pinia": "^2.2.6",
    "three": "^0.160.0",
    "vue": "^3.5.13"
  },
  "devDependencies": {
    "@types/d3": "^7.4.3",
    "@types/three": "^0.160.0",
    "@vitejs/plugin-vue": "^5.2.1",
    "@vue/tsconfig": "^0.7.0",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.17",
    "typescript": "~5.7.2",
    "vite": "^6.0.5",
    "vue-tsc": "^2.2.0"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`:**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true },
    },
  },
})
```

- [ ] **Step 3: Create `frontend/tsconfig.json`:**

```json
{
  "extends": "@vue/tsconfig/tsconfig.dom.json",
  "compilerOptions": {
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vite/client"]
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create `frontend/tsconfig.node.json`:**

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "types": ["node"]
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create `frontend/tailwind.config.js`:**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Outfit', 'Inter', 'sans-serif'], mono: ['JetBrains Mono', 'monospace'] },
      colors: {
        space: { 900: '#05060f', 800: '#0a0e1f', 700: '#111634', 600: '#1b2350' },
        glow: { cyan: '#38e1ff', violet: '#8b5cf6', lime: '#a3e635' },
      },
      boxShadow: { glow: '0 0 20px rgba(56,225,255,0.35)' },
    },
  },
  plugins: [],
}
```

- [ ] **Step 6: Create `frontend/postcss.config.js`:**

```javascript
export default { plugins: { tailwindcss: {}, autoprefixer: {} } }
```

- [ ] **Step 7: Create `frontend/index.html`:**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link
      href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <title>Multi-Agent Dashboard</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 8: Create `frontend/.gitignore`:**

```
node_modules
dist
*.local
```

- [ ] **Step 9: Create `frontend/src/vite-env.d.ts`:**

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 10: Create `frontend/src/style.css`:**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: dark;
}

body {
  margin: 0;
  background: radial-gradient(circle at 20% 10%, #111634 0%, #05060f 55%);
  color: #e5e9f5;
  font-family: 'Outfit', sans-serif;
  min-height: 100vh;
}

.panel {
  background: rgba(17, 22, 52, 0.6);
  border: 1px solid rgba(56, 225, 255, 0.12);
  border-radius: 14px;
  backdrop-filter: blur(8px);
}

.glow-text {
  text-shadow: 0 0 12px rgba(56, 225, 255, 0.6);
}
```

- [ ] **Step 11: Create `frontend/src/main.ts`:**

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'

createApp(App).use(createPinia()).mount('#app')
```

- [ ] **Step 12: Create a minimal `frontend/src/App.vue`:**

```vue
<script setup lang="ts">
// Full layout is assembled in Task B5; this placeholder makes B1 build clean.
</script>

<template>
  <main class="min-h-screen p-8">
    <h1 class="text-3xl font-bold glow-text">Multi-Agent Dashboard</h1>
    <p class="text-space-600">Scaffold ready.</p>
  </main>
</template>
```

- [ ] **Step 13: Install and verify the build gate**

Run:
```bash
cd frontend && npm install && npm run build
```
Expected: `vue-tsc` type-checks clean and `vite build` writes `dist/`. If `@vue/tsconfig` path errors occur, confirm the `extends` target exists in `node_modules/@vue/tsconfig`.

- [ ] **Step 14: Commit**

```bash
cd .. && git add frontend
git commit -m "feat(frontend): scaffold Vue 3 + Vite + Pinia + Tailwind dashboard shell"
```

---

### Task B2: Types, API service, Pinia store, WebSocket composable

**Files:** `frontend/src/types.ts`, `services/api.ts`, `stores/projects.ts`, `composables/useWebSocket.ts`.

**Interfaces:**
- Produces:
  - `types.ts`: `StreamEvent` union, `RunSummary`, `HitlPayload`, `Metrics`, `NodeName`.
  - `api.ts`: `startProject(prompt, platform, mode)`, `listProjects()`, `getProject(id)`, `approveHitl(id, decision, feedback?)`.
  - `stores/projects.ts`: Pinia store `useProjectsStore` exposing `runs`, `activeId`, `events`, `logs`, `nodes` (status per node), `hitl`, `metrics`, and actions `start`, `select`, `applyEvent`, `approve`, `reject`, `refreshList`.
  - `composables/useWebSocket.ts`: `connectStream(projectId, onEvent)` returning a `close()` fn with auto-reconnect.

- [ ] **Step 1: Create `frontend/src/types.ts`:**

```typescript
export type NodeName =
  | 'supervisor' | 'architect' | 'coder' | 'inner_loop_check'
  | 'security_scan' | 'hitl_gate' | 'test_generator' | 'reviewer'
  | 'deploy_gate' | 'deployer'

export type NodeStatus = 'idle' | 'running' | 'complete'

export interface HitlPayload {
  gate_type: 'security' | 'deploy'
  question?: string
  security_score?: number
  security_critical?: boolean
  review_decision?: string
  files?: number
  [k: string]: unknown
}

export interface StateDelta {
  status?: string
  security_score?: number
  review_decision?: string
  total_cost_usd?: number
  iteration_count?: number
  source_files?: string[]
  architecture_spec?: Record<string, unknown>
  [k: string]: unknown
}

export type StreamEvent =
  | { type: 'run_started'; project_id: string; mode: string }
  | { type: 'node'; node: NodeName; status: 'complete'; state_delta: StateDelta }
  | { type: 'log'; line: string }
  | { type: 'hitl_request'; gate_type: string; payload: HitlPayload }
  | { type: 'hitl_resolved'; gate_type: string; decision: string }
  | { type: 'completed'; status: string }
  | { type: 'error'; error: string }

export interface RunSummary {
  project_id: string
  mode: string
  prompt: string
  status: string
  awaiting_hitl: boolean
  event_count: number
}

export interface Metrics {
  total_cost_usd: number
  iteration_count: number
  security_score: number | null
  review_decision: string | null
}
```

- [ ] **Step 2: Create `frontend/src/services/api.ts`:**

```typescript
import type { RunSummary } from '../types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

export function startProject(
  prompt: string,
  platform: string | null,
  mode: 'real' | 'demo',
): Promise<{ project_id: string; mode: string }> {
  return fetch(`/api/projects?mode=${mode}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, platform }),
  }).then(json)
}

export function listProjects(): Promise<{ runs: RunSummary[] }> {
  return fetch('/api/projects').then(json)
}

export function getProject(id: string): Promise<Record<string, unknown>> {
  return fetch(`/api/projects/${id}`).then(json)
}

export function approveHitl(
  id: string,
  decision: 'approve' | 'reject',
  feedback?: string,
): Promise<{ accepted: boolean }> {
  return fetch(`/api/hitl/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, feedback }),
  }).then(json)
}
```

- [ ] **Step 3: Create `frontend/src/composables/useWebSocket.ts`:**

```typescript
import type { StreamEvent } from '../types'

/**
 * Open a stream to a run and invoke `onEvent` per message. Reconnects on drop
 * (the backend replays history from index 0, so re-consumption is safe until a
 * `completed`/`error` event is seen).
 */
export function connectStream(
  projectId: string,
  onEvent: (ev: StreamEvent) => void,
): () => void {
  let ws: WebSocket | null = null
  let closedByUs = false
  let done = false

  const url = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}/api/projects/${projectId}/stream`
  }

  const open = () => {
    ws = new WebSocket(url())
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data) as StreamEvent
      if (ev.type === 'completed' || ev.type === 'error') done = true
      onEvent(ev)
    }
    ws.onclose = () => {
      if (!closedByUs && !done) setTimeout(open, 1000)
    }
  }

  open()
  return () => {
    closedByUs = true
    ws?.close()
  }
}
```

- [ ] **Step 4: Create `frontend/src/stores/projects.ts`:**

```typescript
import { defineStore } from 'pinia'
import type { NodeName, NodeStatus, StreamEvent, RunSummary, HitlPayload, Metrics } from '../types'
import * as api from '../services/api'
import { connectStream } from '../composables/useWebSocket'

const NODE_ORDER: NodeName[] = [
  'supervisor', 'architect', 'coder', 'inner_loop_check', 'security_scan',
  'hitl_gate', 'test_generator', 'reviewer', 'deploy_gate', 'deployer',
]

interface State {
  runs: RunSummary[]
  activeId: string | null
  logs: string[]
  nodes: Record<NodeName, NodeStatus>
  hitl: HitlPayload | null
  metrics: Metrics
  costHistory: number[]
  disconnect: (() => void) | null
}

function emptyNodes(): Record<NodeName, NodeStatus> {
  return Object.fromEntries(NODE_ORDER.map((n) => [n, 'idle'])) as Record<NodeName, NodeStatus>
}

export const useProjectsStore = defineStore('projects', {
  state: (): State => ({
    runs: [],
    activeId: null,
    logs: [],
    nodes: emptyNodes(),
    hitl: null,
    metrics: { total_cost_usd: 0, iteration_count: 0, security_score: null, review_decision: null },
    costHistory: [],
    disconnect: null,
  }),
  getters: {
    nodeOrder: () => NODE_ORDER,
    isAwaiting: (s): boolean => s.hitl !== null,
  },
  actions: {
    async refreshList() {
      this.runs = (await api.listProjects()).runs
    },
    async start(prompt: string, platform: string | null, mode: 'real' | 'demo') {
      const { project_id } = await api.startProject(prompt, platform, mode)
      await this.refreshList()
      this.select(project_id)
    },
    select(id: string) {
      this.disconnect?.()
      this.activeId = id
      this.logs = []
      this.nodes = emptyNodes()
      this.hitl = null
      this.metrics = { total_cost_usd: 0, iteration_count: 0, security_score: null, review_decision: null }
      this.costHistory = []
      this.disconnect = connectStream(id, (ev) => this.applyEvent(ev))
    },
    applyEvent(ev: StreamEvent) {
      if (ev.type === 'log') {
        this.logs.push(ev.line)
      } else if (ev.type === 'node') {
        // Mark all prior nodes complete, current running->complete.
        this.nodes[ev.node] = 'complete'
        const d = ev.state_delta
        if (typeof d.total_cost_usd === 'number') {
          this.metrics.total_cost_usd += d.total_cost_usd
          this.costHistory.push(this.metrics.total_cost_usd)
        }
        if (typeof d.iteration_count === 'number') this.metrics.iteration_count += d.iteration_count
        if (typeof d.security_score === 'number') this.metrics.security_score = d.security_score
        if (typeof d.review_decision === 'string') this.metrics.review_decision = d.review_decision
      } else if (ev.type === 'hitl_request') {
        this.hitl = ev.payload
        const gateNode: NodeName = ev.gate_type === 'security' ? 'hitl_gate' : 'deploy_gate'
        this.nodes[gateNode] = 'running'
      } else if (ev.type === 'hitl_resolved') {
        this.hitl = null
      } else if (ev.type === 'completed' || ev.type === 'error') {
        this.hitl = null
      }
    },
    async approve(feedback?: string) {
      if (this.activeId) await api.approveHitl(this.activeId, 'approve', feedback)
    },
    async reject(feedback?: string) {
      if (this.activeId) await api.approveHitl(this.activeId, 'reject', feedback)
    },
  },
})
```

- [ ] **Step 5: Verify the build type-checks**

Run: `cd frontend && npm run build`
Expected: PASS (no type errors). If `defineStore` state typing complains, confirm `pinia` is installed.

- [ ] **Step 6: Commit**

```bash
cd .. && git add frontend/src
git commit -m "feat(frontend): types, API client, Pinia store, WebSocket composable"
```

---

### Task B3: `ProjectForm` + `ProjectList` components

**Files:** `frontend/src/components/ProjectForm.vue`, `ProjectList.vue`.

**Interfaces:**
- Consumes: `useProjectsStore` (B2).
- Produces: `ProjectForm.vue` (prompt textarea, platform select, demo toggle, submit → `store.start`); `ProjectList.vue` (renders `store.runs`, status badge, click → `store.select`).

- [ ] **Step 1: Create `frontend/src/components/ProjectForm.vue`:**

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const prompt = ref('')
const platform = ref<string>('react-native')
const demo = ref(true)
const submitting = ref(false)

async function submit() {
  if (!prompt.value.trim()) return
  submitting.value = true
  try {
    await store.start(prompt.value.trim(), platform.value, demo.value ? 'demo' : 'real')
    prompt.value = ''
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="panel p-4 space-y-3" @submit.prevent="submit">
    <textarea
      v-model="prompt"
      rows="3"
      placeholder="Describe the app to build…"
      class="w-full bg-space-900/60 rounded-lg p-3 text-sm outline-none border border-space-600 focus:border-glow-cyan"
    />
    <div class="flex items-center gap-3 text-sm">
      <select v-model="platform" class="bg-space-900/60 rounded-lg p-2 border border-space-600">
        <option value="react-native">React Native</option>
        <option value="flutter">Flutter</option>
        <option value="native-ios">Native iOS</option>
        <option value="native-android">Native Android</option>
      </select>
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" v-model="demo" /> Demo mode (keyless)
      </label>
    </div>
    <button
      type="submit"
      :disabled="submitting"
      class="w-full py-2 rounded-lg bg-glow-cyan/20 border border-glow-cyan text-glow-cyan font-semibold hover:bg-glow-cyan/30 disabled:opacity-50"
    >
      {{ submitting ? 'Starting…' : 'Build' }}
    </button>
  </form>
</template>
```

- [ ] **Step 2: Create `frontend/src/components/ProjectList.vue`:**

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
onMounted(() => store.refreshList())

const badgeClass = (status: string): string => {
  if (status === 'completed') return 'text-glow-lime border-glow-lime'
  if (status === 'failed') return 'text-red-400 border-red-400'
  if (status === 'awaiting_hitl') return 'text-glow-violet border-glow-violet'
  return 'text-glow-cyan border-glow-cyan'
}
</script>

<template>
  <div class="panel p-4 space-y-2">
    <h2 class="text-sm uppercase tracking-widest text-space-600">Runs</h2>
    <ul class="space-y-1">
      <li
        v-for="r in store.runs"
        :key="r.project_id"
        @click="store.select(r.project_id)"
        class="p-2 rounded-lg cursor-pointer hover:bg-space-700/50 flex items-center justify-between"
        :class="{ 'bg-space-700/70': r.project_id === store.activeId }"
      >
        <span class="truncate text-sm">{{ r.prompt || r.project_id }}</span>
        <span class="text-xs px-2 py-0.5 rounded-full border" :class="badgeClass(r.status)">
          {{ r.status }}
        </span>
      </li>
    </ul>
  </div>
</template>
```

- [ ] **Step 3: Verify build** — Run: `cd frontend && npm run build` → PASS.

- [ ] **Step 4: Commit**

```bash
cd .. && git add frontend/src/components
git commit -m "feat(frontend): ProjectForm and ProjectList components"
```

---

### Task B4: `AgentGraph` hero visual (d3/SVG live node graph)

**Files:** `frontend/src/components/AgentGraph.vue`.

**Interfaces:**
- Consumes: `useProjectsStore` (`nodes` map, `nodeOrder`).
- Produces: an SVG constellation of the 10 pipeline nodes wired in pipeline order; each node glows by status (`idle`/`running`/`complete`); a GSAP pulse on the running node.

**Design notes:** Reference `C:\Users\furkan\Desktop\SQLGen\frontend\src\components\SpaceSpiderweb.vue` for the star/edge aesthetic. Keep it dependency-light: static layout (two rows), d3 only for a scale; GSAP for the running-node pulse. No force simulation needed.

- [ ] **Step 1: Create `frontend/src/components/AgentGraph.vue`:**

```vue
<script setup lang="ts">
import { computed, watch, ref, nextTick } from 'vue'
import gsap from 'gsap'
import { useProjectsStore } from '../stores/projects'
import type { NodeName } from '../types'

const store = useProjectsStore()

// Static two-row constellation layout (x,y in a 1000x360 viewBox).
const POS: Record<NodeName, [number, number]> = {
  supervisor: [60, 90], architect: [210, 90], coder: [360, 90],
  inner_loop_check: [510, 90], security_scan: [660, 90], hitl_gate: [810, 90],
  test_generator: [810, 270], reviewer: [610, 270], deploy_gate: [410, 270],
  deployer: [210, 270],
}
const EDGES: [NodeName, NodeName][] = [
  ['supervisor', 'architect'], ['architect', 'coder'], ['coder', 'inner_loop_check'],
  ['inner_loop_check', 'security_scan'], ['security_scan', 'hitl_gate'],
  ['hitl_gate', 'test_generator'], ['test_generator', 'reviewer'],
  ['reviewer', 'deploy_gate'], ['deploy_gate', 'deployer'],
]

const color = (n: NodeName): string => {
  const s = store.nodes[n]
  if (s === 'complete') return '#a3e635'
  if (s === 'running') return '#38e1ff'
  return '#33406b'
}

const label = (n: NodeName): string => n.replace(/_/g, ' ')

const nodeEls = ref<Record<string, SVGCircleElement | null>>({})
const setRef = (n: NodeName) => (el: unknown) => { nodeEls.value[n] = el as SVGCircleElement | null }

watch(
  () => ({ ...store.nodes }),
  async () => {
    await nextTick()
    for (const n of store.nodeOrder) {
      const el = nodeEls.value[n]
      if (el && store.nodes[n] === 'running') {
        gsap.fromTo(el, { attr: { r: 14 } }, { attr: { r: 20 }, repeat: -1, yoyo: true, duration: 0.7 })
      } else if (el) {
        gsap.killTweensOf(el)
        gsap.set(el, { attr: { r: 14 } })
      }
    }
  },
  { deep: true },
)

const edgeActive = computed(() =>
  (a: NodeName, b: NodeName): boolean =>
    store.nodes[a] === 'complete' && store.nodes[b] !== 'idle',
)
</script>

<template>
  <div class="panel p-4">
    <h2 class="text-sm uppercase tracking-widest text-space-600 mb-2">Agent Graph</h2>
    <svg viewBox="0 0 1000 360" class="w-full">
      <line
        v-for="([a, b], i) in EDGES"
        :key="i"
        :x1="POS[a][0]" :y1="POS[a][1]" :x2="POS[b][0]" :y2="POS[b][1]"
        :stroke="edgeActive(a, b) ? '#38e1ff' : '#1b2350'"
        stroke-width="2"
      />
      <g v-for="n in store.nodeOrder" :key="n">
        <circle
          :ref="setRef(n)"
          :cx="POS[n][0]" :cy="POS[n][1]" r="14"
          :fill="color(n)"
          :style="{ filter: store.nodes[n] !== 'idle' ? 'drop-shadow(0 0 8px currentColor)' : 'none' }"
        />
        <text
          :x="POS[n][0]" :y="POS[n][1] + 34"
          text-anchor="middle" fill="#9fb0d9" font-size="12"
        >{{ label(n) }}</text>
      </g>
    </svg>
  </div>
</template>
```

- [ ] **Step 2: Verify build** — Run: `cd frontend && npm run build` → PASS. (If the `:ref` function-ref typing errors under strict, cast in `setRef` as shown.)

- [ ] **Step 3: Commit**

```bash
cd .. && git add frontend/src/components/AgentGraph.vue
git commit -m "feat(frontend): live AgentGraph hero visual (d3/SVG + GSAP pulse)"
```

---

### Task B5: `HITLPanel` + `TerminalLogs` + `MetricCards`, and assemble `App.vue`

**Files:** `frontend/src/components/HITLPanel.vue`, `TerminalLogs.vue`, `MetricCards.vue`; rewrite `frontend/src/App.vue`.

**Interfaces:**
- Consumes: `useProjectsStore`.
- Produces: gate panel (approve/reject/feedback → `store.approve/reject`), autoscrolling logs, metric cards with a d3 SVG cost sparkline; `App.vue` composes sidebar (ProjectForm + ProjectList) + main (AgentGraph, HITLPanel, MetricCards, TerminalLogs).

- [ ] **Step 1: Create `frontend/src/components/HITLPanel.vue`:**

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const feedback = ref('')

async function decide(kind: 'approve' | 'reject') {
  if (kind === 'approve') await store.approve(feedback.value || undefined)
  else await store.reject(feedback.value || undefined)
  feedback.value = ''
}
</script>

<template>
  <div v-if="store.hitl" class="panel p-4 border-glow-violet/40">
    <h2 class="text-sm uppercase tracking-widest text-glow-violet mb-2">
      Human Approval — {{ store.hitl.gate_type }} gate
    </h2>
    <p class="text-sm text-space-600 mb-2">{{ store.hitl.question }}</p>
    <ul class="text-sm mb-3 space-y-1">
      <li v-if="store.hitl.security_score != null">Security score: {{ store.hitl.security_score }}</li>
      <li v-if="store.hitl.review_decision">Review: {{ store.hitl.review_decision }}</li>
      <li v-if="store.hitl.files != null">Files: {{ store.hitl.files }}</li>
    </ul>
    <input
      v-model="feedback"
      placeholder="Optional feedback…"
      class="w-full bg-space-900/60 rounded-lg p-2 text-sm border border-space-600 mb-3"
    />
    <div class="flex gap-3">
      <button
        @click="decide('approve')"
        class="flex-1 py-2 rounded-lg bg-glow-lime/20 border border-glow-lime text-glow-lime font-semibold"
      >Approve</button>
      <button
        @click="decide('reject')"
        class="flex-1 py-2 rounded-lg bg-red-500/20 border border-red-400 text-red-300 font-semibold"
      >Reject</button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Create `frontend/src/components/TerminalLogs.vue`:**

```vue
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const box = ref<HTMLDivElement | null>(null)

watch(
  () => store.logs.length,
  async () => {
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  },
)
</script>

<template>
  <div class="panel p-4">
    <h2 class="text-sm uppercase tracking-widest text-space-600 mb-2">Logs</h2>
    <div ref="box" class="font-mono text-xs h-48 overflow-y-auto space-y-0.5">
      <div v-for="(line, i) in store.logs" :key="i" class="text-space-600/90">
        <span class="text-glow-cyan">›</span> {{ line }}
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Create `frontend/src/components/MetricCards.vue`:**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import * as d3 from 'd3'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()

const sparkPath = computed<string>(() => {
  const data = store.costHistory
  if (data.length < 2) return ''
  const w = 120, h = 32
  const x = d3.scaleLinear().domain([0, data.length - 1]).range([0, w])
  const y = d3.scaleLinear().domain([0, d3.max(data) || 1]).range([h, 0])
  const line = d3.line<number>().x((_, i) => x(i)).y((d) => y(d))
  return line(data) || ''
})
</script>

<template>
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div class="panel p-3">
      <div class="text-xs text-space-600">Cost (USD)</div>
      <div class="text-xl font-semibold glow-text">${{ store.metrics.total_cost_usd.toFixed(3) }}</div>
      <svg width="120" height="32" class="mt-1"><path :d="sparkPath" fill="none" stroke="#38e1ff" stroke-width="1.5" /></svg>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-space-600">Iterations</div>
      <div class="text-xl font-semibold">{{ store.metrics.iteration_count }}</div>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-space-600">Security</div>
      <div class="text-xl font-semibold">{{ store.metrics.security_score ?? '—' }}</div>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-space-600">Review</div>
      <div class="text-xl font-semibold">{{ store.metrics.review_decision ?? '—' }}</div>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Rewrite `frontend/src/App.vue`:**

```vue
<script setup lang="ts">
import ProjectForm from './components/ProjectForm.vue'
import ProjectList from './components/ProjectList.vue'
import AgentGraph from './components/AgentGraph.vue'
import HITLPanel from './components/HITLPanel.vue'
import TerminalLogs from './components/TerminalLogs.vue'
import MetricCards from './components/MetricCards.vue'
import { useProjectsStore } from './stores/projects'

const store = useProjectsStore()
</script>

<template>
  <div class="min-h-screen flex">
    <aside class="w-80 p-4 space-y-4 border-r border-space-600/40">
      <h1 class="text-2xl font-bold glow-text">◇ Multi-Agent</h1>
      <ProjectForm />
      <ProjectList />
    </aside>
    <main class="flex-1 p-6 space-y-4">
      <div v-if="store.activeId" class="space-y-4">
        <AgentGraph />
        <MetricCards />
        <HITLPanel />
        <TerminalLogs />
      </div>
      <div v-else class="h-full grid place-items-center text-space-600">
        Start a build to watch the pipeline run.
      </div>
    </main>
  </div>
</template>
```

- [ ] **Step 5: Verify build** — Run: `cd frontend && npm run build` → PASS (type-check clean).

- [ ] **Step 6: Manual smoke test (optional but recommended).** In one terminal: `python -m uvicorn src.api.main:app --port 8000`. In another: `cd frontend && npm run dev`. Open the dev URL, submit a prompt with **Demo mode** on, and confirm: AgentGraph lights up, logs stream, the HITL panel opens at the security gate → Approve → opens at deploy gate → Approve → run completes. No API keys needed.

- [ ] **Step 7: Commit**

```bash
cd .. && git add frontend/src
git commit -m "feat(frontend): HITL panel, live logs, metric cards, assembled dashboard"
```

---

### Task B6: CI frontend job

**Files:** `.github/workflows/ci.yml`.

**Interfaces:** Produces a `frontend` CI job that runs `npm ci && npm run build`, independent of the Python job.

- [ ] **Step 1: Read the current workflow** to match its style.

Run: `cat .github/workflows/ci.yml`

- [ ] **Step 2: Add a `frontend` job** to `.github/workflows/ci.yml` (as a sibling of the existing Python job — same `jobs:` mapping):

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run build
```

- [ ] **Step 3: Ensure `frontend/package-lock.json` is committed** (created by `npm install` in B1). If it is git-ignored or missing, run `cd frontend && npm install` and `git add -f frontend/package-lock.json`. The `npm ci` step and the `cache-dependency-path` both require it.

- [ ] **Step 4: Verify the workflow is valid YAML.**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Update living docs.**
- `CHANGELOG.md`: under `## [Unreleased]` add `### Added` — "Sprint 8 PR-B — Vue 3 dashboard (`frontend/`): live AgentGraph, HITL panel, streaming logs, metric cards; CI frontend build job."
- `cache.md`: update the resume pointer to "Sprint 8 complete; both PRs pushed" (or the actual state) after PRs land.

- [ ] **Step 6: Commit + push + STOP for user gate**

```bash
git add .github/workflows/ci.yml frontend/package-lock.json CHANGELOG.md cache.md
git commit -m "ci(frontend): add npm build/type-check job for the dashboard"
git push -u origin feature/s8b-dashboard-frontend
```

**STOP — user gate:** Tell the user PR-B is pushed and the frontend build is green locally; ask them to review/merge. Do not merge without the user.

---

## Self-Review (completed against the spec)

**Spec coverage:**
- §4.1 RunManager (history + condition, reconnect/multi-client) → Task A2 + WS replay in A5. ✓
- §4.1 background `graph.stream` in thread + interrupt handling → Task A4 (`_drive_stream` via `to_thread` + `run_coroutine_threadsafe`). ✓
- §4.1 resume via `Command(resume=...)` → Task A4 `resume_pipeline`, A5 endpoint. ✓
- §4.2 WS event protocol (run_started/node/log/hitl_request/hitl_resolved/completed/error) → Task A4 `chunk_to_events` + drivers (metrics folded into `node` state_delta per spec's "may be folded into node"). ✓
- §4.3 demo graph (same topology, real gates, stubs, InMemorySaver, persist=False, no keys/Docker) → Task A3. ✓
- §4.4 endpoints (async POST w/ mode, GET list, GET snapshot, WS, approve) → Task A5. ✓
- §4.5 testing (WS demo-run drain to completion, CORS, list, snapshot, resume; async-start contract update) → A1/A5. ✓
- §5.1 frontend structure → B1–B5 (all listed files created). ✓
- §5.2 aesthetic (SQLGen tokens, Outfit, hero AgentGraph) → B1 style/tailwind + B4. ✓
- §5.3 CI frontend job → B6. ✓
- §8 acceptance criteria → covered by A5 WS test, B5 smoke test, B6 CI, backend gates in A5 step 5. ✓

**Placeholder scan:** No TBD/"handle edge cases"/"similar to Task N" — all steps carry concrete code. The one intentional cross-task note (`record_graphs` ordering in A5 step 3) is called out explicitly with the fix.

**Type consistency:** Event `type` strings, `gate_type` values, node names (`hitl_gate`/`deploy_gate`), and store field names (`nodes`, `hitl`, `metrics`, `costHistory`) are consistent across `types.ts`, `stores/projects.ts`, and the components. Backend `_SAFE_KEYS` produces `source_files` (list) consumed as `state_delta.source_files` in `types.ts`. `chunk_to_events` interrupt shape matches `HitlPayload`.

**Known risk flagged for the executor:** the thread→loop bridge (A4) is the spec's called-out trickiest piece. If a WS test hangs, verify (a) `app.state.demo_delay = 0.0` in tests, (b) `run_coroutine_threadsafe(...).result()` is used (not fire-and-forget), and (c) `completed` is always appended before `mark_closed` so the WS loop's `closed` check terminates.
