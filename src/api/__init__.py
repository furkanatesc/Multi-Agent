"""HTTP API package (Sprint 7).

Hosts the FastAPI application that exposes the pipeline over HTTP. Sprint 7's
observability PR establishes the app skeleton with ``/health`` and the
Prometheus ``/metrics`` endpoint; the HITL PR adds the project-run and
``/api/hitl/{id}/approve`` endpoints on top of the same app.
"""
