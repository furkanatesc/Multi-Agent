"""Unit tests for the LangSmith tracing configuration (Sprint 7, PR#12)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from src.core.config import settings
from src.observability import langsmith_tracer as tracer

_TRACE_ENV = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


@pytest.fixture(autouse=True)
def _restore_trace_env() -> Iterator[None]:
    """Snapshot and restore the LangChain tracing env around each test."""
    saved = {k: os.environ.get(k) for k in _TRACE_ENV}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_tracing_disabled_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LANGSMITH_TRACING", False)
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # stale value must be cleared

    assert tracer.configure_tracing() is False
    assert tracer.is_tracing_enabled() is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ


def test_tracing_disabled_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(settings, "LANGSMITH_API_KEY", "")

    assert tracer.configure_tracing() is False
    assert tracer.is_tracing_enabled() is False


def test_tracing_enabled_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(settings, "LANGSMITH_API_KEY", "lsk-test")
    monkeypatch.setattr(settings, "LANGSMITH_PROJECT", "proj-x")

    assert tracer.configure_tracing() is True
    assert tracer.is_tracing_enabled() is True
    assert os.environ["LANGCHAIN_API_KEY"] == "lsk-test"
    assert os.environ["LANGCHAIN_PROJECT"] == "proj-x"
