"""FastAPI application: observability surface + HITL run lifecycle (Sprint 7).

The app is built by :func:`create_app` (so tests get a fresh instance with its
own checkpointer) and also exposed as a module-level ``app`` for
``uvicorn src.api.main:app``. LangSmith tracing is configured once at startup.

Endpoints:

* ``GET  /health``                    — liveness probe (+ tracing status).
* ``GET  /metrics``                   — Prometheus exposition.
* ``POST /api/projects``              — start a pipeline run; returns the state,
  which is **paused** at the first HITL gate (``awaiting_hitl`` true).
* ``POST /api/hitl/{project_id}/approve`` — resume a paused run with a human
  decision (``approve``/``reject``) via ``Command(resume=...)``.

The compiled graph carries a checkpointer so runs can pause on a dynamic
``interrupt`` and resume later. ``create_app`` defaults to an in-memory
checkpointer (single-process); production should inject a ``PostgresSaver``
(``create_app(checkpointer=get_postgres_checkpointer())``) so paused runs
survive restarts and span workers.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.db.session import get_memory_checkpointer
from src.observability import metrics
from src.observability.langsmith_tracer import configure_tracing, is_tracing_enabled
from src.orchestrator.graph import build_graph
from src.orchestrator.state import UserRequest, build_response, create_initial_state


class HITLResolveRequest(BaseModel):
    """Human decision used to resume a paused run at a HITL gate."""

    decision: Literal["approve", "reject"] = Field(
        default="approve", description="The human's verdict on the gate."
    )
    feedback: Optional[str] = Field(
        default=None, description="Optional reviewer note recorded with the decision."
    )


def _thread_config(project_id: str) -> dict[str, Any]:
    """Build the LangGraph config that scopes state to one project run."""
    return {"configurable": {"thread_id": project_id}}


def _run_payload(project_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Project an invoke/resume result onto the API response shape.

    When the run paused at a HITL gate, ``result`` carries an ``__interrupt__``
    entry whose value is the gate's human-review payload.
    """
    interrupts = result.get("__interrupt__") or []
    awaiting = bool(interrupts)
    hitl = interrupts[0].value if awaiting else None
    response = build_response(result)  # type: ignore[arg-type]
    return {
        "project_id": project_id,
        "status": response.status,
        "awaiting_hitl": awaiting,
        "hitl": hitl,
        "response": response.model_dump(),
    }


def create_app(checkpointer: Optional[Any] = None) -> FastAPI:
    """Construct and configure the FastAPI application.

    Args:
        checkpointer: LangGraph checkpointer for the compiled graph. Defaults to
            an in-memory saver; production should pass a ``PostgresSaver``.
    """
    # Idempotent: wires LangSmith env from settings (no-op when disabled).
    configure_tracing()

    graph = build_graph(checkpointer=checkpointer or get_memory_checkpointer())

    app = FastAPI(
        title="Multi-Agent Mobile App Development System",
        description="Autonomous multi-agent pipeline API.",
        version="0.5.0",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        """Liveness probe with a tracing-status hint."""
        return {"status": "ok", "tracing": is_tracing_enabled()}

    @app.get("/metrics", tags=["system"])
    def prometheus_metrics() -> Response:
        """Serve the Prometheus exposition for this app's metrics."""
        payload, content_type = metrics.render()
        return Response(content=payload, media_type=content_type)

    @app.post("/api/projects", tags=["pipeline"])
    def start_project(request: UserRequest) -> dict[str, Any]:
        """Start a pipeline run; returns the (likely HITL-paused) run state."""
        project_id = str(uuid4())
        config = _thread_config(project_id)
        initial = create_initial_state(request, project_id=project_id)
        result = graph.invoke(initial, config=config)
        return _run_payload(project_id, result)

    @app.post("/api/hitl/{project_id}/approve", tags=["pipeline"])
    def resolve_hitl(project_id: str, body: HITLResolveRequest) -> dict[str, Any]:
        """Resume a paused run with a human approve/reject decision."""
        config = _thread_config(project_id)
        snapshot = graph.get_state(config)
        if not snapshot.values:
            raise HTTPException(
                status_code=404, detail=f"Unknown project '{project_id}'."
            )
        if not snapshot.next:
            raise HTTPException(
                status_code=409,
                detail="No pending HITL approval for this project.",
            )
        result = graph.invoke(Command(resume=body.model_dump()), config=config)
        return _run_payload(project_id, result)

    return app


app = create_app()
