# Changelog

All notable changes to the **Multi-Agent Mobile App Development System** are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This file is updated at every **sprint & PR closure**.

---

## [Unreleased]

> ⏸️ **Stopping point (2026-06-18).** Sprint 4 complete (PRs #4 + #5 merged to `develop`). Next session → **Sprint 5 — Security Agent & Test Generator (Faz 5)**. See `cache.md` for full resume context.

#### Added (tooling — `feature/integrate-superpowers`, 2026-06-19)
- **Vendored [superpowers](https://github.com/obra/superpowers) agent skills** (MIT, commit `896224c`) into `.claude/skills/` — 14 dev-workflow skills (TDD, systematic-debugging, brainstorming, writing/executing-plans, subagent-driven-development, code-review flows, git-worktrees, verification-before-completion). Auto-discovered by Claude Code; not a plugin install. Origin/license/update notes in `.claude/skills/VENDORED.md`; session-start hooks copied to `.claude/superpowers-hooks/` (not wired into settings — optional).
- `docs/06_gortex_vendoring_plan.md`: integration/vendor **plan** for [gortex](https://github.com/zzet/gortex) (Apache-2.0). Source NOT moved in yet — deferred to brownfield **Milestone B** (post-S5) per `docs/05_expansion_vision.md`; documents subtree-vs-fork options and the Python↔gortex MCP/HTTP bridge.

---

## [Sprint 4] — Coder Agent & Inner Loop (Faz 4) — 2026-06-18 — 🔴 highest-risk sprint (Docker self-fix)
Complete. Two PRs merged: **#4 Coder Agent**, **#5 Inner Loop**. The Coder now generates code via a tool-loop and self-fixes it against real Docker lint/test runs. **83 tests passing**, `mypy --strict` clean (38 files).

#### Added (PR #4 — Coder Agent)
- `integrations/litellm_chat_model.py`: **`LiteLLMChatModel`** — the deferred LiteLLM ↔ LangChain `BaseChatModel` bridge (**decision #4**). Routes every `create_react_agent` model call through `LiteLLMClient`, so Router fallback + token/cost tracking stay intact. Converts LangChain messages ↔ OpenAI dicts, parses `tool_calls` (valid → `ToolCall`, malformed → `invalid_tool_calls`), and exposes `bind_tools`.
- `agents/coder/tools.py`: in-memory `Workspace` (`{path: content}`) with path-safety (rejects absolute paths / `..` traversal) + `make_file_tools()` → `write_file` / `read_file` / `list_files` LangChain tools for the tool-loop.
- `agents/coder/schemas.py`: `GeneratedModule` / `SelfFixResult` structured summaries (Pydantic v2, `extra="ignore"`).
- `agents/coder/agent.py`: **`CoderAgent`** — `generate_module()` + `self_fix()` run a `create_react_agent` tool-loop over the bridge (writing into the workspace), then request a structured summary; `run()` returns the `source_code` map and inner-loop routing. Primary `coder-model` (Claude Sonnet), fallback Gemini.
- `config/prompts/coder_system.md`: Coder system prompt (file tools, complete-files rule, self-fix mode).
- Tests: `test_litellm_chat_model.py` (bridge: generation, tool-call parsing, `bind_tools`, routing) + `test_coder.py` (workspace/tools path-safety, generation, `run` state, self-fix). **65 tests passing**; `mypy --strict` clean across `src/` + `tests/`.

#### Changed (PR #4)
- `orchestrator/nodes.py`: `coder` stub → real `CoderAgent` integration.
- `tests/conftest.py`: added autouse offline `CoderAgent` stub so graph tests stay deterministic (mirrors the architect stub).

#### Added (PR #5 — Inner Loop)
- `integrations/docker_runner.py`: **`DockerRunner`** — sandboxed lint/test in disposable containers. Files injected via in-memory **`put_archive` tar** (not bind-mounts → Windows-safe); commands wrapped in coreutils `timeout`; container always removed. `ensure_image()` builds a tagged image from its Dockerfile on first use. Result models `CommandResult` / `RunResult`.
- `agents/coder/inner_loop.py`: **`InnerLoopRunner`** — encapsulates the lint→test→`self_fix` cycle (bounded by `max_inner_loop_iterations`), returning the fixed files + final verdicts + cost (`InnerLoopResult`). Platform→toolchain mapping (`_PROFILES`: Node / Flutter).
- `docker/Dockerfile.node` (node:20-slim) + `docker/Dockerfile.dart` (Cirrus Flutter): generic runtime images; project files + commands arrive at runtime.
- Tests: `test_docker_runner.py` (mocked client: lifecycle, tar upload, timeout wrap, install short-circuit, cleanup-on-error) + `test_inner_loop.py` (mocked Docker+Coder: pass-first-try, fix-then-pass, iteration cap, profile selection).

#### Changed (PR #5)
- `orchestrator/nodes.py`: `inner_loop_check` stub → real `InnerLoopRunner` integration.
- `tests/conftest.py`: added autouse offline `InnerLoopRunner` stub for graph tests.
- `orchestrator/edges.py`: **unchanged** — `should_continue_inner_loop` logic was already correct; the inner loop being encapsulated in the runner means the graph back-edge stays dormant (cap reached → proceed).

#### Notes
- **Decision #4 (2026-06-17):** the Coder uses the `BaseChatModel` bridge + `create_react_agent` tool-loop (not single-shot structured output), because it needs to write/read/revise files iteratively. This realizes the bridge deferred in Sprint 3.
- **Decision #5 (2026-06-18):** the inner self-fix loop is encapsulated **inside `InnerLoopRunner`** (one `inner_loop_check` node call runs the whole lint→test→fix cycle), not realized via the graph's `coder↔inner_loop_check` back-edge — keeps the Coder's error-context out of graph state. Docker file injection uses `put_archive` (tar) to avoid Windows bind-mount issues.

---

## [v0.1-alpha] — 2026-06-17 — 🏷️ Milestone M1: Core Engine
Released via `develop → main`. Aggregates Sprints 1–3: LiteLLM Router fallback, LangGraph `StateGraph` + PostgreSQL checkpointing, and the Architect Agent (ADR generation). Core engine runs end-to-end; 42 tests + `mypy --strict` green; CI active.

---

## [Sprint 3] — Architect Agent (Faz 3) — 2026-06-17
### Added
- **PR #3**: First real LLM-backed agent — the Architect, producing a structured ADR.
  - `agents/base.py`: abstract `BaseAgent` built on `LiteLLMClient` (preserves Router fallback + token/cost tracking); `complete_structured()` JSON→Pydantic helper; `AgentError` / `AgentOutputError`.
  - `agents/architect/schemas.py`: `ADRDocument`, `TechStack`, `FolderStructure`, `ArchitectureDecision` (Pydantic v2, `extra="ignore"`).
  - `agents/architect/tools.py`: `analyze_requirements` (keyword platform heuristic) + `default_folder_structure` (per-framework fallback layout).
  - `agents/architect/agent.py`: `ArchitectAgent` — `analyze_requirements()`, `select_tech_stack()`, `generate_adr()`, `run()`.
  - `config/prompts/architect_system.md`: platform-selection logic, Clean Architecture rules, JSON-only ADR output contract.
  - Tests: `test_architect.py` (mock-LLM ADR generation, schema validation, tool heuristics) + shared `conftest.py` offline architect stub for graph tests. 42 tests passing; `mypy --strict` clean across `src/` and `tests/`.
### Changed
- `orchestrator/nodes.py`: `architect` stub → real `ArchitectAgent` integration (the other 8 nodes remain stubs until their sprints).
### Notes
- LLM access uses `LiteLLMClient` + structured output (**decision #2**), not `create_react_agent`, to keep the Sprint 1 Router fallback/cost infrastructure intact. The `make_handoff_tool` react-supervisor and a LangChain `BaseChatModel` bridge are **deferred to Sprint 4 (Coder)**, where a genuine tool-loop is required; the existing edge-based routing already realizes the supervisor→architect handoff.

---

## [Sprint 2] — Orchestration & State (Faz 2) — 2026-06-17
### Added
- **PR #2**: LangGraph `StateGraph` orchestration skeleton, state reducers & PostgreSQL checkpointing.
  - `orchestrator/state.py`: `AgentState` (TypedDict) with reducer channels — `add_messages`, `operator.add` (cost/iteration), custom `merge_source_code`; boundary Pydantic models `UserRequest` / `AgentResponse` + `create_initial_state` / `build_response` helpers.
  - `orchestrator/nodes.py`: 9 stub agent nodes (`supervisor` → `deployer`) returning partial-dict updates.
  - `orchestrator/edges.py`: conditional routers — `cost_check`, `should_continue_inner_loop`, `should_escalate`, `security_gate`, `review_decision` (thresholds from `guardrails.yaml`).
  - `orchestrator/graph.py`: full pipeline topology compiled with a pluggable checkpointer.
  - `db/models.py`: SQLAlchemy 2.0 models — `Project`, `AgentRun`, `HITLApproval`, `CostLog` (JSONB on Postgres).
  - `db/session.py`: lazy engine/session + `PostgresSaver` connection pool; psycopg-v3 URL normalization.
  - `alembic/` + `alembic.ini`: `001_initial` migration for the four tables.
  - `docker-compose.yml`: `postgres:16` + `redis:7` dev services (matching config defaults).
  - `.github/workflows/ci.yml`: CI pipeline — `mypy --strict` + `alembic upgrade head` + `pytest` against a live Postgres service.
  - Tests: `test_state.py`, `test_orchestrator.py`, `test_checkpoint_postgres.py` (live-Postgres integration, auto-skips when unavailable). 33 tests passing.
### Changed
- `pyproject.toml`: added `sqlalchemy>=2.0`, `alembic>=1.13`; registered `integration` pytest marker.
- `core/logging.py`, `integrations/litellm_client.py`: minor typing fixes to keep `mypy --strict` green.

---

## [Sprint 1] — Infrastructure & LiteLLM (Faz 1) — 2026-06-17
### Added
- **PR #1**: Project skeleton & LiteLLM Router foundation.
  - `pyproject.toml`: Python 3.11+ project + pinned core stack (`langgraph>=1.0.10`, `litellm>=1.50`, `pydantic>=2`, FastAPI, structlog, psycopg).
  - `config/litellm_config.yaml`: model definitions (Gemini 2.5 Pro, Claude Sonnet 4, GPT-4o) + fallback chains.
  - `config/guardrails.yaml`: inner/outer loop caps, max cost, per-agent token limits, timeout.
  - `core/config.py`: Pydantic `Settings` (`.env` + YAML config merge).
  - `core/logging.py`: structlog setup — JSON in non-TTY, colorized console in TTY.
  - `integrations/litellm_client.py`: `LiteLLMClient` — `Router` wrapper with fallback, token tracking & cost calculation.
  - Tests: `test_litellm_client.py` (init, completion/cost tracking, fallback failure).
