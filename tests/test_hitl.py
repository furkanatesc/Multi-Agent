"""Unit tests for the human-in-the-loop gate (:class:`HITLGate`).

The gate is exercised here without a live LangGraph runtime: the module-level
``interrupt`` symbol is monkeypatched to simulate a resume value, and DB
persistence is tested against a real (in-memory SQLite) ORM session so the
find-or-create / resolution / timeout logic runs against actual SQLAlchemy.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, HITLApproval, Project
from src.orchestrator import hitl as hitl_module
from src.orchestrator.hitl import HITLGate, HITLResolution
from src.orchestrator.state import AgentState

_NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)


def _state(**kwargs: Any) -> AgentState:
    return cast(AgentState, dict(kwargs))


@pytest.fixture
def session_factory() -> Any:
    """Return a context-manager session factory over an in-memory SQLite DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    @contextmanager
    def scope() -> Iterator[Session]:
        db = maker()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # Seed the parent project row referenced by the FK.
    with scope() as db:
        db.add(Project(id="p1", prompt="Build a todo app"))
    return scope


# --------------------------------------------------------------------------- #
# interpret() — pure resume-value parsing
# --------------------------------------------------------------------------- #


def test_interpret_approve_dict() -> None:
    res = HITLGate.interpret({"decision": "approve", "feedback": "ship it"})
    assert res.decision == "approve"
    assert res.approved is True
    assert res.feedback == "ship it"


def test_interpret_reject_dict() -> None:
    res = HITLGate.interpret({"decision": "reject", "feedback": "fix auth"})
    assert res.decision == "reject"
    assert res.approved is False
    assert res.feedback == "fix auth"


def test_interpret_string_and_bool() -> None:
    assert HITLGate.interpret("approve").decision == "approve"
    assert HITLGate.interpret("APPROVED").decision == "approve"
    assert HITLGate.interpret("reject").decision == "reject"
    assert HITLGate.interpret(True).decision == "approve"
    assert HITLGate.interpret(False).decision == "reject"
    assert HITLGate.interpret({"approved": True}).decision == "approve"


def test_interpret_defaults_to_reject_on_ambiguous() -> None:
    """A gate must never auto-approve on missing/garbage resume input."""
    assert HITLGate.interpret(None).decision == "reject"
    assert HITLGate.interpret({}).decision == "reject"
    assert HITLGate.interpret("maybe").decision == "reject"


# --------------------------------------------------------------------------- #
# build_payload() — gate-specific human-review summary
# --------------------------------------------------------------------------- #


def test_build_payload_security_gate() -> None:
    gate = HITLGate("security", persist=False)
    payload = gate.build_payload(
        _state(project_id="p1", security_score=40, security_critical=True)
    )
    assert payload["gate_type"] == "security"
    assert payload["security_score"] == 40
    assert payload["security_critical"] is True
    assert "question" in payload


def test_build_payload_deploy_gate() -> None:
    gate = HITLGate("deploy", persist=False)
    payload = gate.build_payload(
        _state(
            project_id="p1",
            review_decision="PASS",
            source_code={"a": "1", "b": "2"},
        )
    )
    assert payload["gate_type"] == "deploy"
    assert payload["review_decision"] == "PASS"
    assert payload["files"] == 2


# --------------------------------------------------------------------------- #
# request() — persist -> interrupt -> interpret -> resolve (no live graph)
# --------------------------------------------------------------------------- #


def test_request_returns_resolution_from_resume_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hitl_module, "interrupt", lambda payload: {"decision": "approve"}
    )
    gate = HITLGate("deploy", persist=False)
    res = gate.request(_state(project_id="p1"))
    assert res == HITLResolution(decision="approve", feedback=None)


def test_request_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hitl_module,
        "interrupt",
        lambda payload: {"decision": "reject", "feedback": "no"},
    )
    gate = HITLGate("security", persist=False)
    res = gate.request(_state(project_id="p1"))
    assert res.decision == "reject"
    assert res.feedback == "no"


# --------------------------------------------------------------------------- #
# persistence — find-or-create pending, then resolve (real SQLite ORM)
# --------------------------------------------------------------------------- #


def test_record_pending_is_idempotent(session_factory: Any) -> None:
    gate = HITLGate("security", session_factory=session_factory)
    gate._record_pending("p1", {"gate_type": "security"})
    gate._record_pending("p1", {"gate_type": "security"})  # second call: no dup
    with session_factory() as db:
        rows = db.query(HITLApproval).filter_by(project_id="p1").all()
    assert len(rows) == 1
    assert rows[0].status == "pending"


def test_record_resolution_updates_pending_row(session_factory: Any) -> None:
    gate = HITLGate("deploy", session_factory=session_factory)
    gate._record_pending("p1", {"gate_type": "deploy"})
    gate._record_resolution("p1", HITLResolution(decision="approve", feedback="go"))
    with session_factory() as db:
        row = db.query(HITLApproval).filter_by(project_id="p1").one()
    assert row.status == "approved"
    assert row.feedback == "go"
    assert row.resolved_at is not None


def test_record_resolution_marks_rejected(session_factory: Any) -> None:
    gate = HITLGate("security", session_factory=session_factory)
    gate._record_pending("p1", {"gate_type": "security"})
    gate._record_resolution("p1", HITLResolution(decision="reject", feedback="nope"))
    with session_factory() as db:
        row = db.query(HITLApproval).filter_by(project_id="p1").one()
    assert row.status == "rejected"


# --------------------------------------------------------------------------- #
# timeout
# --------------------------------------------------------------------------- #


def test_is_expired_pure() -> None:
    gate = HITLGate("deploy", persist=False, guardrails={"hitl_timeout_seconds": 60})
    requested = _NOW
    assert gate.is_expired(requested, _NOW + timedelta(seconds=61)) is True
    assert gate.is_expired(requested, _NOW + timedelta(seconds=30)) is False


def test_expire_pending_marks_stale_rows(session_factory: Any) -> None:
    gate = HITLGate(
        "deploy",
        session_factory=session_factory,
        guardrails={"hitl_timeout_seconds": 60},
    )
    # One stale pending row, one fresh.
    with session_factory() as db:
        db.add(
            HITLApproval(
                id="old",
                project_id="p1",
                gate_type="deploy",
                status="pending",
                requested_at=_NOW - timedelta(seconds=120),
            )
        )
        db.add(
            HITLApproval(
                id="new",
                project_id="p1",
                gate_type="deploy",
                status="pending",
                requested_at=_NOW - timedelta(seconds=10),
            )
        )
    marked = gate.expire_pending(now=_NOW)
    assert marked == 1
    with session_factory() as db:
        old = db.query(HITLApproval).filter_by(id="old").one()
        new = db.query(HITLApproval).filter_by(id="new").one()
    assert old.status == "timeout"
    assert new.status == "pending"


# --------------------------------------------------------------------------- #
# graceful degradation — DB unavailable must not break the gate
# --------------------------------------------------------------------------- #


def test_request_survives_db_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def broken() -> Iterator[Session]:
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(
        hitl_module, "interrupt", lambda payload: {"decision": "approve"}
    )
    gate = HITLGate("deploy", session_factory=broken)
    # persistence fails internally but the gate still resolves the interrupt.
    res = gate.request(_state(project_id="p1"))
    assert res.decision == "approve"
