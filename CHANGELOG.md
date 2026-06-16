# Changelog

All notable changes to the **Multi-Agent Mobile App Development System** are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This file is updated at every **sprint & PR closure**.

---

## [Unreleased]

> In progress: Sprint 3 — Architect Agent (Faz 3). Closes Milestone **M1 (v0.1-alpha)**.

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
