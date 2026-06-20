"""FastAPI application: health + Prometheus metrics (Sprint 7 observability).

The app is built by :func:`create_app` (so tests get a fresh instance) and also
exposed as a module-level ``app`` for ``uvicorn src.api.main:app``. LangSmith
tracing is configured once at startup via :func:`configure_tracing`.

This PR establishes the skeleton and the observability surface:

* ``GET /health``  — liveness probe (also reports whether tracing is enabled).
* ``GET /metrics`` — Prometheus exposition of the collectors in
  :mod:`observability.metrics`.

The HITL PR adds the project-run and ``/api/hitl/{id}/approve`` routes to the
same application.
"""

from __future__ import annotations

from fastapi import FastAPI, Response

from src.observability import metrics
from src.observability.langsmith_tracer import configure_tracing, is_tracing_enabled


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    # Idempotent: wires LangSmith env from settings (no-op when disabled).
    configure_tracing()

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

    return app


app = create_app()
