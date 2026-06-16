"""SQLAlchemy 2.0 ORM models for persistent project state.

These tables back the orchestration layer (they are independent of the LangGraph
checkpointer, which stores its own ``langgraph.*`` tables via ``PostgresSaver``):

* :class:`Project`       -- one row per user request / app build.
* :class:`AgentRun`      -- one row per agent invocation (audit + token usage).
* :class:`HITLApproval`  -- human-in-the-loop gate requests and their resolution.
* :class:`CostLog`       -- fine-grained per-call cost ledger.

Typed with ``Mapped[...]`` / ``mapped_column`` for ``mypy --strict`` compliance.
JSON columns use a generic ``JSON`` type with a Postgres ``JSONB`` variant so the
production database gets indexable/efficient storage while staying portable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# A JSON column that becomes JSONB on PostgreSQL, plain JSON elsewhere.
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _uuid_str() -> str:
    """Generate a string UUID4 for use as a primary key default."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base; ``Base.metadata`` is the Alembic ``target_metadata``."""


class Project(Base):
    """A single autonomous app-build run initiated by a user prompt."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    # Latest Architect ADR / spec snapshot.
    architecture_spec: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JsonType, nullable=True
    )

    security_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    hitl_approvals: Mapped[list["HITLApproval"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    cost_logs: Mapped[list["CostLog"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentRun(Base):
    """Audit record of a single agent (node) invocation."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    model_used: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="agent_runs")


class HITLApproval(Base):
    """A human-in-the-loop gate request and its eventual resolution.

    ``gate_type`` ∈ {``architecture``, ``security``, ``deploy``, ``budget``};
    ``status`` ∈ {``pending``, ``approved``, ``rejected``, ``timeout``}.
    """

    __tablename__ = "hitl_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    # The artifact under review (ADR JSON, security report, deploy plan, ...).
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="hitl_approvals")


class CostLog(Base):
    """Per-call cost ledger entry for budget tracking and reporting."""

    __tablename__ = "cost_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="cost_logs")
