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

import asyncio
from functools import partial
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.api.run_manager import RunManager
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
    # Per-app map of project_id -> compiled graph (demo graphs are per-run).
    record_graphs: dict[str, Any] = {}

    app = FastAPI(
        title="Multi-Agent Mobile App Development System",
        description="Autonomous multi-agent pipeline API.",
        version="0.6.0",
    )
    app.state.demo_delay = _DEFAULT_DEMO_DELAY

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
        ],
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
            raise HTTPException(
                status_code=404, detail=f"Unknown project '{project_id}'."
            )
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

        def _has_more(seen: int) -> bool:
            return len(record.events) > seen or record.closed

        try:
            while True:
                async with record.condition:
                    await record.condition.wait_for(partial(_has_more, idx))
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
    async def resolve_hitl(project_id: str, body: HITLResolveRequest) -> dict[str, Any]:
        record = manager.get(project_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown project '{project_id}'."
            )
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

    return app


app = create_app()
