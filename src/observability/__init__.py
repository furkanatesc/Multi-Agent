"""Observability package (Sprint 7).

Lean instrumentation for the multi-agent pipeline:

* :mod:`observability.metrics` — Prometheus collectors (token/cost/loop/review
  metrics) on a dedicated registry, plus ``record_*`` helpers and a ``render``
  function the FastAPI ``/metrics`` endpoint serves.
* :mod:`observability.langsmith_tracer` — env-driven LangSmith tracing
  configuration (auto-traces LangGraph/LiteLLM when ``LANGSMITH_TRACING=true``).

Grafana dashboards + the Prometheus/Grafana docker-compose services are
intentionally deferred (see the Sprint 7 scope decision); this package gives the
``/metrics`` exposition and trace wiring those tools would later consume.
"""
