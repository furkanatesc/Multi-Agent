# Sprint 8 — Web Dashboard Design Spec

**Date:** 2026-06-21
**Status:** Approved (design); pending implementation plan (writing-plans)
**Branch(es):** `feature/s8a-dashboard-backend` → `feature/s8b-dashboard-frontend`
**Depends on:** Sprint 7 complete (FastAPI + HITL endpoints + checkpointer). M2 (`v0.5-beta`) cut.

---

## 1. Goal

A live web dashboard over the multi-agent pipeline: start a build from a prompt,
watch the agent graph execute in real time, approve/reject the human-in-the-loop
(HITL) gates from the UI, and inspect the ADR, generated code, security score,
review verdict, logs, and cost/metrics.

## 2. Resolved decisions (2026-06-21)

| Decision | Choice | Notes |
|----------|--------|-------|
| Framework | **Vue 3 + Vite + Pinia** (TS strict) | Matches the user's SQLGen project so its Three.js/GSAP/Lenis aesthetic + assets are reused. Overrides the sprint plan's React 19/Zustand/Recharts. See memory `dashboard-design-direction`. |
| Liveness | **Full real-time** | Backend background run + WebSocket broadcast of `graph.stream()` steps; live `AgentGraph` + live `TerminalLogs`. |
| Keyless demo | **Yes — `mode=demo`** | A mock run mode (stub agent outputs + artificial delay) so the dashboard is demoable without valid API keys / Docker. Real mode preserved. |
| Decomposition | **2 PRs, one design doc** | PR-A backend streaming (pytest-gated "solid foundation"), then PR-B Vue SPA (build/type-check gated). |
| Charts | **d3 / SVG** | Recharts is React-only; d3 is already the SQLGen idiom. |

## 3. Architecture overview

Two layers, one `frontend/` directory + additions to the existing FastAPI app.

Data flow:
```
ProjectForm --POST /api/projects(?mode=demo)--> {project_id}
   -> open WS /api/projects/{id}/stream
   -> events update Pinia store -> components react
   -> at a HITL gate: HITLPanel opens -> POST /api/hitl/{id}/approve
   -> background run resumes -> stream continues -> completed
```

---

## 4. PR-A — Backend streaming layer (pytest-gated)

### 4.1 Components
- **CORS** middleware (allow the frontend origin; configurable).
- **`RunManager`** — in-process registry, one entry per run:
  - compiled graph + `config` (`thread_id` = `project_id`), `mode` (real/demo), status.
  - **event history** `list[dict]` + an `asyncio.Condition`. WS clients replay from index 0 and await the condition for new events → supports reconnect and multiple clients.
- **Background execution** — `graph.stream(input, config, stream_mode="updates")` is sync/blocking, so it runs in a worker thread (`asyncio.to_thread`). Each stream chunk (`{node_name: state_delta}`) is converted to events and appended to history (condition `notify_all`). On a HITL `__interrupt__`, the stream ends → emit `hitl_request`, set status `awaiting_hitl`, background task finishes (run paused; checkpointer holds state).
- **Resume** — `POST /api/hitl/{id}/approve` starts a new background task: `graph.stream(Command(resume={"decision","feedback"}), config)`, appending more events until the next interrupt or completion.

### 4.2 WebSocket event protocol (JSON)
- `{type:"run_started", project_id, mode}`
- `{type:"node", node, status:"running"|"complete", state_delta:{…subset…}}`
- `{type:"log", line}` — extracted from node `messages` (AIMessage content)
- `{type:"hitl_request", gate_type, payload}`
- `{type:"hitl_resolved", gate_type, decision}`
- `{type:"metrics", total_cost_usd, iteration_count, …}` (may be folded into `node`)
- `{type:"completed", status}` | `{type:"error", error}`

### 4.3 Demo / mock graph
- `build_demo_graph()` (`src/orchestrator/demo.py`) — same `StateGraph` topology and the **real** HITL gate nodes (so demo runs pause at gates and exercise the full HITL UI), but agent nodes are stubs producing canned ADR/code/security/test/review outputs with a small `time.sleep(delay)` to simulate progress. Uses `InMemorySaver`; `HITLGate(persist=False)`. No LLM keys, no Docker.
- Demo node implementations + `build_demo_graph()` live in `src/orchestrator/demo.py`.

### 4.4 Endpoints
- `POST /api/projects?mode=real|demo` (body `UserRequest`) → `{project_id, mode}` immediately; starts the background run. **(Contract change: was synchronous-result.)**
- `GET /api/projects` → list of runs (id, status, prompt, created).
- `GET /api/projects/{id}` → snapshot (status, projected state, `awaiting_hitl`, hitl payload, event count) for initial load / reconnect.
- `WS /api/projects/{id}/stream` → replay history then live events.
- `POST /api/hitl/{project_id}/approve` (body decision/feedback) → resume run; returns accepted.
- `GET /health`, `GET /metrics` — preserved.

### 4.5 Testing
- `TestClient.websocket_connect`: start a **demo** run (delays=0), drain events, assert the sequence reaches `hitl_request` → approve → `completed`.
- CORS header present; `GET /api/projects` + `GET /api/projects/{id}` snapshot; resume path.
- Real-mode runs in tests use the existing autouse agent stubs (deterministic, offline).
- Update existing `test_api.py` HITL tests for the async-start contract.

---

## 5. PR-B — Vue dashboard (build / type-check gated)

### 5.1 Structure (mirrors SQLGen `frontend/`)
```
frontend/
  package.json        # vue, three, gsap, lenis, d3, pinia, tailwind, typescript, vite, vue-tsc
  vite.config.ts      # proxy /api + /ws -> FastAPI :8000; HMR
  tsconfig*.json, tailwind.config.js, postcss.config.js
  index.html          # Outfit (+ Inter) fonts
  src/
    main.ts           # createApp + pinia
    App.vue           # layout: sidebar (ProjectList) + main detail panel
    style.css         # SQLGen design tokens: dark/space palette, glow, typography
    stores/projects.ts        # Pinia: projects, activeProject, events, hitl state, metrics
    services/api.ts           # REST client
    composables/useWebSocket.ts  # WS connect + auto-reconnect + snapshot replay
    components/
      ProjectForm.vue   # prompt, platform, demo-mode toggle
      ProjectList.vue   # active/past runs, status badges
      AgentGraph.vue    # HERO: SpaceSpiderweb-style live node viz (active highlight + completion animation)
      HITLPanel.vue     # gate payload (ADR / security / deploy summary) + approve/reject/feedback
      TerminalLogs.vue  # live log lines, autoscroll
      MetricCards.vue   # cost (USD), tokens, elapsed, iterations (d3/SVG sparklines)
```

### 5.2 Aesthetic
Reuse/adapt SQLGen's `style.css` tokens, `tailwind.config.js`, and Three.js bits:
the planet/`SpaceSpiderweb` concepts become an agent-constellation background +
the `AgentGraph` edge rendering. Outfit font. Keep it tasteful; `AgentGraph` is
the hero visual.

### 5.3 CI
Add a separate frontend job to `.github/workflows/ci.yml`: `npm ci && npm run build`
(vue-tsc type-check) — the build/type-check is the gate (the Python job is unchanged).

---

## 6. Known limitations (accepted)
- **Single-process**: in-memory `RunManager` + in-memory checkpointer default → one
  worker only. Prod multi-worker scaling (PostgresSaver + external pub/sub) is deferred.
- **`graph.stream` in a thread bridged to asyncio** is the trickiest backend piece;
  must be careful with thread→loop handoff (`call_soon_threadsafe` / condition).
- **Real runs still need keys + Docker**; `mode=demo` bypasses this for demos.

## 7. Out of scope (this sprint)
- Auth / multi-user.
- Persisted run history across restarts (registry is in-memory).
- Editing/diffing generated code in the browser beyond read-only viewing.

## 8. Acceptance criteria
- `cd frontend && npm install && npm run dev` runs; `npm run build` type-checks clean.
- A `mode=demo` run streams the full pipeline over WS, pauses at both HITL gates,
  and completes after approvals — **no API keys / Docker required**.
- `AgentGraph` highlights the active node and animates completed steps.
- `HITLPanel` opens on a gate and approve/reject reaches the API and resumes the run.
- `TerminalLogs` and `MetricCards` update live.
- Backend: pytest green (incl. WS demo-run test); `mypy --strict` clean; `ruff` clean.
- Frontend: CI frontend job (build/type-check) green.
