"""Human-in-the-loop (HITL) approval gate for the orchestration graph.

Two gates are wired into the pipeline (Sprint 7 decision — not all four):

* **security** — entered when the Security agent flags a critical finding; a
  human must approve accepting the risk (proceed) or reject (send back to fix).
* **deploy** — entered after the Reviewer approves a build; a human must approve
  the actual deployment.

Mechanics: :meth:`HITLGate.request` calls LangGraph's dynamic ``interrupt()``
inside a node. The graph pauses and the run is resumed from the API with
``Command(resume=<decision>)``; the resume value is then interpreted into an
approve/reject :class:`HITLResolution`. Because a resumed node re-executes from
the top, the DB write is *idempotent* (find-or-create the pending row).

Persistence to the ``hitl_approvals`` table is **best-effort**: like the
Docker-backed tools, the gate degrades gracefully when the database is
unreachable (it logs a warning and still resolves the interrupt). A
``session_factory`` can be injected for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager, Literal, Optional

from langgraph.types import interrupt
from sqlalchemy.orm import Session

from src.core.logging import logger
from src.db.models import HITLApproval
from src.db.session import session_scope
from src.orchestrator.guardrails import GuardrailsEngine
from src.orchestrator.state import AgentState

GateType = Literal["security", "deploy"]
"""Which gate is requesting approval."""

HITLDecisionT = Literal["approve", "reject"]
"""The human's verdict on a gate."""

# Resume-value tokens (case-insensitive) that mean "approve". Anything else
# (including missing/garbage input) is treated as a rejection — a gate must
# never auto-approve on ambiguous resume input.
_APPROVE_TOKENS = {"approve", "approved", "yes", "true", "y"}

SessionFactory = Callable[[], ContextManager[Session]]


def _as_utc(dt: datetime) -> datetime:
    """Return ``dt`` as timezone-aware UTC (naive timestamps are assumed UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@dataclass(frozen=True)
class HITLResolution:
    """The resolved outcome of a HITL gate."""

    decision: HITLDecisionT
    feedback: Optional[str] = None

    @property
    def approved(self) -> bool:
        """True when the human approved the gate."""
        return self.decision == "approve"


class HITLGate:
    """A single human-in-the-loop approval gate.

    Args:
        gate_type: Which gate this instance represents (``security``/``deploy``).
        persist: When False, skip all database I/O (pure interrupt flow).
        session_factory: Context-manager session factory (defaults to the
            shared :func:`session_scope`); injectable for tests.
        guardrails: Optional explicit guardrails mapping for the timeout.
    """

    def __init__(
        self,
        gate_type: GateType,
        *,
        persist: bool = True,
        session_factory: Optional[SessionFactory] = None,
        guardrails: Optional[dict[str, Any]] = None,
    ) -> None:
        self.gate_type: GateType = gate_type
        self._persist = persist
        self._session_factory: SessionFactory = session_factory or session_scope
        self._guardrails = GuardrailsEngine(guardrails)

    # --- pure logic -------------------------------------------------------- #

    def build_payload(self, state: AgentState) -> dict[str, Any]:
        """Build the human-facing review summary surfaced by the interrupt."""
        payload: dict[str, Any] = {
            "gate_type": self.gate_type,
            "project_id": state.get("project_id"),
            "prompt": state.get("prompt"),
        }
        if self.gate_type == "security":
            payload.update(
                security_score=state.get("security_score"),
                security_critical=bool(state.get("security_critical")),
                question=(
                    "A critical security finding requires human approval. "
                    "Approve to accept the risk and proceed, or reject to send "
                    "the build back to the Coder for fixes."
                ),
            )
        else:  # deploy
            payload.update(
                review_decision=state.get("review_decision"),
                security_score=state.get("security_score"),
                files=len(state.get("source_code") or {}),
                question="Approve deployment of the reviewed build?",
            )
        return payload

    @staticmethod
    def interpret(resume_value: Any) -> HITLResolution:
        """Parse a resume value (dict/str/bool/None) into a :class:`HITLResolution`."""
        feedback: Optional[str] = None
        raw: Any = resume_value
        if isinstance(resume_value, dict):
            feedback = resume_value.get("feedback")
            raw = resume_value.get("decision", resume_value.get("approved"))

        if isinstance(raw, bool):
            approved = raw
        elif isinstance(raw, str):
            approved = raw.strip().lower() in _APPROVE_TOKENS
        else:
            approved = False

        return HITLResolution(
            decision="approve" if approved else "reject", feedback=feedback
        )

    def is_expired(self, requested_at: datetime, now: datetime) -> bool:
        """True when a request made at ``requested_at`` has exceeded the timeout.

        Tolerates naive/aware mismatches (some backends — e.g. SQLite — drop the
        timezone on round-trip) by treating naive timestamps as UTC.
        """
        elapsed = (_as_utc(now) - _as_utc(requested_at)).total_seconds()
        return elapsed > self._guardrails.hitl_timeout_seconds

    # --- node-facing entry point ------------------------------------------- #

    def request(self, state: AgentState) -> HITLResolution:
        """Persist a pending request, pause on ``interrupt``, and resolve.

        On first execution this raises a ``GraphInterrupt`` (the run pauses).
        When resumed via ``Command(resume=...)`` the node re-runs from the top;
        the idempotent pending-write is a no-op and ``interrupt`` returns the
        resume value, which is interpreted and recorded as the resolution.
        """
        project_id = state.get("project_id")
        payload = self.build_payload(state)
        self._record_pending(project_id, payload)
        resume_value = interrupt(payload)
        resolution = self.interpret(resume_value)
        self._record_resolution(project_id, resolution)
        return resolution

    # --- persistence (best-effort) ----------------------------------------- #

    def _record_pending(
        self, project_id: Optional[str], payload: dict[str, Any]
    ) -> None:
        """Create a pending row for this gate, idempotently (find-or-create)."""
        if not self._persist or not project_id:
            return
        try:
            with self._session_factory() as db:
                existing = (
                    db.query(HITLApproval)
                    .filter_by(
                        project_id=project_id,
                        gate_type=self.gate_type,
                        status="pending",
                    )
                    .first()
                )
                if existing is None:
                    db.add(
                        HITLApproval(
                            project_id=project_id,
                            gate_type=self.gate_type,
                            status="pending",
                            payload=payload,
                        )
                    )
        except Exception as exc:  # pragma: no cover - exercised via broken factory
            logger.warning(
                "HITL pending persist skipped (DB unavailable)",
                gate=self.gate_type,
                error=str(exc),
            )

    def _record_resolution(
        self, project_id: Optional[str], resolution: HITLResolution
    ) -> None:
        """Resolve the latest pending row for this gate to approved/rejected."""
        if not self._persist or not project_id:
            return
        try:
            with self._session_factory() as db:
                row = (
                    db.query(HITLApproval)
                    .filter_by(
                        project_id=project_id,
                        gate_type=self.gate_type,
                        status="pending",
                    )
                    .order_by(HITLApproval.requested_at.desc())
                    .first()
                )
                if row is not None:
                    row.status = "approved" if resolution.approved else "rejected"
                    row.feedback = resolution.feedback
                    row.resolved_at = datetime.now(timezone.utc)
        except Exception as exc:  # pragma: no cover - exercised via broken factory
            logger.warning(
                "HITL resolution persist skipped (DB unavailable)",
                gate=self.gate_type,
                error=str(exc),
            )

    def expire_pending(self, now: datetime, project_id: Optional[str] = None) -> int:
        """Mark stale pending rows for this gate as ``timeout``; return the count."""
        if not self._persist:
            return 0
        try:
            with self._session_factory() as db:
                query = db.query(HITLApproval).filter_by(
                    gate_type=self.gate_type, status="pending"
                )
                if project_id:
                    query = query.filter_by(project_id=project_id)
                marked = 0
                for row in query.all():
                    if self.is_expired(row.requested_at, now):
                        row.status = "timeout"
                        row.resolved_at = now
                        marked += 1
                return marked
        except Exception as exc:  # pragma: no cover - exercised via broken factory
            logger.warning(
                "HITL expiry sweep skipped (DB unavailable)",
                gate=self.gate_type,
                error=str(exc),
            )
            return 0
