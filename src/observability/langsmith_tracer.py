"""LangSmith tracing configuration (env-driven).

LangChain/LangGraph and LiteLLM auto-emit traces to LangSmith when the standard
``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_API_KEY`` environment variables are set —
no per-call callback wiring is required. This module bridges the project's
Pydantic settings (``LANGSMITH_*``) to those environment variables in one place,
so enabling tracing is a single ``configure_tracing()`` call at startup.

It is deliberately defensive: tracing is *opt-in* (``LANGSMITH_TRACING=true``)
and a missing API key disables it with a warning rather than raising — a bad/
absent key otherwise only produces harmless ``403`` noise from the exporter.
"""

from __future__ import annotations

import os

from src.core.config import settings
from src.core.logging import logger

# Standard LangChain tracing environment variables.
_TRACING_FLAG = "LANGCHAIN_TRACING_V2"
_API_KEY = "LANGCHAIN_API_KEY"
_PROJECT = "LANGCHAIN_PROJECT"


def configure_tracing() -> bool:
    """Wire LangSmith tracing from settings into the environment.

    Returns:
        ``True`` if tracing was enabled (flag on **and** an API key is present),
        ``False`` otherwise (and the tracing flag is explicitly cleared so a
        stale environment value can't silently re-enable a keyless exporter).
    """
    if not settings.LANGSMITH_TRACING:
        os.environ.pop(_TRACING_FLAG, None)
        logger.info("LangSmith tracing disabled (LANGSMITH_TRACING is false)")
        return False

    if not settings.LANGSMITH_API_KEY:
        os.environ.pop(_TRACING_FLAG, None)
        logger.warning(
            "LangSmith tracing requested but no LANGSMITH_API_KEY set; disabling "
            "to avoid 403 exporter noise"
        )
        return False

    os.environ[_TRACING_FLAG] = "true"
    os.environ[_API_KEY] = settings.LANGSMITH_API_KEY
    os.environ[_PROJECT] = settings.LANGSMITH_PROJECT
    logger.info("LangSmith tracing enabled", project=settings.LANGSMITH_PROJECT)
    return True


def is_tracing_enabled() -> bool:
    """Return whether the tracing flag is currently set in the environment."""
    return os.environ.get(_TRACING_FLAG, "").lower() == "true"
