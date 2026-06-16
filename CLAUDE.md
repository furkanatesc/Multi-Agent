# Multi-Agent Mobile App Development System

This file provides build, test, and style commands for Claude Code, along with the project's coding standards.

## Build and Environment Commands
* **Install dependencies (editable mode):** `pip install -e .`
* **Create virtual environment:** `python -m venv venv`
* **Activate virtual environment:**
  * Windows (PowerShell): `.\venv\Scripts\Activate.ps1`
  * Linux/macOS: `source venv/bin/activate`

## Test and Quality Commands
* **Run all tests:** `pytest`
* **Run tests with verbose output:** `pytest -v`
* **Run specific test file:** `pytest tests/test_litellm_client.py -v`
* **Static type checking:** `mypy src/ --strict`
* **Format code:** `ruff format .`
* **Lint code:** `ruff check .`

## Coding Guidelines
* **Core Technology Stack:**
  * Orchestration: **LangGraph >= 1.0.10** (using Supervisor pattern and handoff tools)
  * LLM Client: **LiteLLM >= 1.50** Router SDK (in-process wrapper client, no proxy server)
  * Logging: **structlog** for structured JSON logging
  * Configuration: **Pydantic v2 Settings**
  * Checkpointing: **PostgresSaver** (SQLite is avoided for safety/CVE compliance)
* **Design Standards:**
  * Always use boundary Pydantic models for external APIs and TypedDict for inner LangGraph states.
  * Use reducers (`Annotated[list, add_messages]`, `operator.add`) for LangGraph state attributes.
  * Implement fallback chains: Gemini 2.5 Pro <-> Claude Sonnet 4 <-> GPT-4o.
  * Keep files and functions modular, well-documented, and strictly typed.
