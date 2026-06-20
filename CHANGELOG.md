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

#### Added (Sprint 5 — PR #7 — Security Agent, 2026-06-20)
- `agents/security/owasp_rules.py`: OWASP Mobile Top 10 (2024) catalog + **deterministic scoring** — `compute_score()` (severity penalties critical −40 / high −25 / medium −10 / low −3 / info 0, clamped 0–100) and `has_critical()` (only `critical` → HITL gate). Score math lives here, not in the prompt, so the `security_gate` decision is reproducible. A single HIGH finding lands at 75 (below the 80 gate) → forces a Coder fix.
- `agents/security/schemas.py`: two-layer Pydantic contract — `SecurityScan` (LLM-facing: summary + `SecurityFinding[]`) vs. `SecurityReport` (final: `score`/`has_critical` computed from findings, not LLM-emitted).
- `agents/security/tools.py`: `run_semgrep_tool` / `run_gitleaks_tool` (via `DockerRunner`, graceful degrade when Docker is down) + `check_dependencies_tool` (Docker-free OWASP M2 manifest audit for unpinned/risky version specs).
- `agents/security/agent.py`: **`SecurityAgent(BaseAgent)`** — `scan_code()` / `audit_dependencies()` / `detect_secrets()` + `run()`. Single-shot structured (decision #2, like Architect): gather scanner evidence → `complete_structured(SecurityScan)` → compute `SecurityReport`. Writes `security_score` + `security_critical` to state. Route `security-model` (GPT-4o).
- `config/prompts/security_system.md`: OWASP checklist, severity guidance, JSON-only output rule.
- `docker/Dockerfile.security`: scanner image (semgrep + gitleaks) for `DockerRunner`.
- `integrations/docker_runner.py`: added **`run_command()`** — general single-command exec (counterpart to `run_checks`) reused by the security scanners.
- `orchestrator/nodes.py`: `security_scan` stub → real `SecurityAgent().run()`. `tests/conftest.py`: added autouse offline `SecurityAgent` stub. `orchestrator/edges.py` `security_gate()` unchanged (already correct: critical→HITL, score<80→fix, else proceed).
- Tests: `test_security.py` (scoring, schemas, dependency audit, agent with mock LLM + fake Docker, graceful-degrade path) + `run_command` cases in `test_docker_runner.py`. **112 passing**, 1 skipped (Postgres); `mypy --strict` clean (44 files).

#### Added (Sprint 5 — PR #8 — Test Generator, 2026-06-20)
- `agents/test_generator/schemas.py`: `TestSuite` (LLM-facing: summary + `GeneratedTestFile[]`); each file carries `path`/`content`/`kind` (`unit`|`widget`|`integration`)/`target`.
- `agents/test_generator/tools.py`: `analyze_code_structure_tool` (Docker-free source-vs-test split) + `run_coverage_tool` (reuses the inner-loop Node/Flutter images via `DockerRunner`, best-effort `parse_coverage_percent`, graceful degrade) + `CoverageResult`.
- `agents/test_generator/agent.py`: **`TestGeneratorAgent(BaseAgent)`** — `generate_unit_tests()` / `generate_widget_tests()` / `generate_integration_tests()` + `run()`. Single-shot structured (decision #2): analyze → `complete_structured(TestSuite)` → merge tests into `source_code` → (if Docker up) coverage check vs the **≥70% target** sets `tests_passed`. Platform-aware kinds (Flutter adds widget tests). Route `test-generator-model` (Claude Sonnet).
- `config/prompts/test_generator_system.md`: framework conventions (Jest/RTL, flutter_test), coverage target, JSON-only output.
- `orchestrator/nodes.py`: `test_generator` stub → real agent. `tests/conftest.py`: added autouse offline `TestGeneratorAgent` stub. No `state.py`/`edges.py`/`graph.py` changes (`test_generator → reviewer` static edge unchanged).
- Tests: `test_test_generator.py` (structure analysis, coverage parsing, schemas, platform kind mapping, coverage tool with fake runner, agent generate/run incl. below-target + Docker-unavailable paths). **129 passing**, 1 skipped (Postgres); `mypy --strict` clean (49 files). **Sprint 5 complete.**

#### Added (Sprint 6 — PR #11 — Reviewer Agent & GitHub Integration, 2026-06-20)
- `agents/reviewer/review_rules.py`: **deterministic PASS/FAIL verdict** — `decide_verdict()` FAILs iff any comment is `blocker`/`major` (severity ladder blocker > major > minor > nit), mirroring the Security agent's deterministic gate (decision #6). The verdict logic lives here, not in the prompt, so the `review_decision` edge routes identically for identical findings.
- `agents/reviewer/schemas.py`: two-layer Pydantic contract — `CodeReview` (LLM-facing: summary + severity-tagged `ReviewComment[]`) vs. `ReviewReport` (final: `verdict` computed from comments, not LLM-emitted) + `CILogAnalysis` (structured CI-log root-cause/fix).
- `agents/reviewer/agent.py`: **`ReviewerAgent(BaseAgent)`** — `review_code()` / `analyze_ci_logs()` / `create_pr_review()` + `run()`. Single-shot structured (decision #2, like Architect/Security): `complete_structured(CodeReview)` → compute `ReviewReport`. `run()` writes `review_decision` + `review_notes` and increments `outer_loop_count`. GitHub I/O is a *separate* explicit capability so the graph node stays offline-testable (as Security's `run` doesn't need Docker). Route `reviewer-model` (GPT-4o). `analyze_ci_logs()` short-circuits (zero cost) on empty logs.
- `integrations/github_client.py`: **`GitHubClient`** (PyGithub facade) — `create_branch()` / `commit_files()` / `create_pull_request()` / `get_ci_logs()` / `submit_review()` / `auto_merge()`. Lazy handle (injectable for tests), every PyGithub failure funneled through `GitHubError`; `create_pr_review` maps verdict→event (PASS→APPROVE, FAIL→REQUEST_CHANGES) and line-anchored comments→inline comments.
- `config/prompts/reviewer_system.md`: SOLID/Clean-Code review checklist, severity guidance, JSON-only output rule.
- `orchestrator/nodes.py`: `reviewer` stub → real `ReviewerAgent().run()`. `tests/conftest.py`: added autouse offline `ReviewerAgent` stub. `orchestrator/edges.py` `review_decision()` + `should_escalate()` unchanged (already correct: PASS→deploy, FAIL+cap→escalate, FAIL→coder).
- Tests: `test_reviewer.py` (verdict rules, schemas, agent review/run/analyze_ci_logs/create_pr_review with mock LLM + mock GitHub) + `test_github_client.py` (branch/commit create-vs-update/PR/CI-logs/review/merge + error wrapping, mock handle). **172 passing**, 1 skipped (Postgres); `mypy --strict` clean (58 files). **Sprint 6 in progress.**

#### Added (Sprint 7 — PR #12 — Observability (lean), 2026-06-21)
- `observability/metrics.py`: Prometheus collectors on a **dedicated `CollectorRegistry`** (isolated from the global default) — `agent_tokens_total{model,kind}`, `agent_cost_usd_total{model}`, `llm_requests_total{model,status}`, `agent_loop_count{loop}`, `review_rejections_total`, `ci_build_duration_seconds` — plus `record_*`/`observe_*` one-liner helpers and `render()` for the exposition. Instrumentation surface is decoupled from the Prometheus API.
- `observability/langsmith_tracer.py`: `configure_tracing()` bridges `settings.LANGSMITH_*` → standard `LANGCHAIN_TRACING_V2`/`_API_KEY`/`_PROJECT` env. **Opt-in & defensive**: disabled (flag cleared) when `LANGSMITH_TRACING` is false or no API key — avoids the keyless-exporter 403 noise.
- `api/main.py` + `api/__init__.py`: **FastAPI app skeleton** (`create_app()` + module-level `app`) with `GET /health` (reports tracing status) and `GET /metrics` (Prometheus exposition). Tracing configured at app construction. This is the API foundation the HITL PR builds on.
- `integrations/litellm_client.py`: wired metrics at the `completion()` chokepoint — records token/cost per model + request success/error outcomes (defensive: metric failures never break a call). `orchestrator/nodes.py`: `inner_loop_check` records inner-loop iterations; `reviewer` records the outer loop + FAIL rejections.
- Scope decision (lean): Grafana dashboards + Prometheus/Grafana docker-compose services **deferred** (to S8/follow-up); this PR ships the `/metrics` exposition + tracer those tools consume.
- Tests: `test_metrics.py` (counter/histogram recording via registry samples), `test_api.py` (FastAPI `/health` + `/metrics` via `TestClient`), `test_langsmith_tracer.py` (enable/disable/no-key paths). **186 passing**, 1 skipped (Postgres); `mypy --strict` clean (66 files); `ruff` clean.

#### Fixed (2026-06-20)
- `config/litellm_config.yaml`: added the missing **`anthropic/`** provider prefix to `coder-model` and `test-generator-model` (`claude-3-5-sonnet-20241022`). Without it LiteLLM Router init raised "LLM Provider NOT provided" — surfaced by the first live `python -m src` run (the mocked unit tests never construct a real Router). Added a regression guard in `test_litellm_client.py` that asserts every `model_list` entry has a `provider/` prefix.

#### Added (tooling — minimal CLI runner, 2026-06-20)
- `src/__main__.py`: a minimal **`python -m src --prompt "..." [--platform ...]`** runner wrapping `build_graph()` so the pipeline can be invoked live before the Sprint 7 API. Includes an environment pre-flight (`check_environment` → LLM-key presence + Docker reachability): blocks with a clear error when no LLM key is set, warns when Docker is down (the inner loop hard-requires it). Reviewer/deployer/HITL are still stubs, so a run yields ADR + source + tests but auto-PASSes review. Tests: `test_cli.py` (arg parsing, env report, no-key guard). **138 passing**, 1 skipped; `mypy --strict` clean (51 files).

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
