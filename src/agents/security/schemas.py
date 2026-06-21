"""Pydantic schemas for the Security agent.

Two layers, by design:

* :class:`SecurityScan` is the **LLM-facing** structured-output contract — the
  model returns a summary plus a list of :class:`SecurityFinding`. It is *not*
  trusted to compute the gate-critical score.
* :class:`SecurityReport` is the **final** result the agent assembles: its
  ``score`` and ``has_critical`` are computed deterministically from the
  findings via ``owasp_rules`` (see ``agents/security/agent.py``), so the
  ``security_gate`` decision never depends on LLM arithmetic.

``OWASPCategory`` / ``Severity`` are reused from ``owasp_rules`` so the agent,
the scorer, and the schema agree on the allowed values (single source of truth).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.security.owasp_rules import OWASPCategory, Severity


class _Schema(BaseModel):
    """Base config: ignore unexpected LLM fields rather than hard-failing."""

    model_config = ConfigDict(extra="ignore")


class SecurityFinding(_Schema):
    """A single security issue located in the generated source."""

    owasp_id: OWASPCategory = Field(
        description="OWASP Mobile Top 10 category, e.g. 'M9'."
    )
    title: str = Field(description="Short finding title.")
    severity: Severity = Field(
        description="One of: critical, high, medium, low, info."
    )
    file: str = Field(description="Relative path of the affected file.")
    line: Optional[int] = Field(
        default=None, description="1-based line number, if known."
    )
    description: str = Field(description="What the issue is and why it is a risk.")
    recommendation: Optional[str] = Field(
        default=None, description="Concrete remediation guidance."
    )


class SecurityScan(_Schema):
    """LLM-facing structured output: a summary plus all findings."""

    summary: str = Field(
        description="One-paragraph summary of the code's security posture."
    )
    findings: list[SecurityFinding] = Field(
        default_factory=list,
        description="Every finding; an empty list means no issues were found.",
    )


class SecurityReport(_Schema):
    """Final report — ``score`` and ``has_critical`` are computed, not LLM-emitted."""

    score: int = Field(ge=0, le=100, description="0-100 security score (computed).")
    has_critical: bool = Field(
        description="True if any finding is critical (forces a HITL gate)."
    )
    summary: str = Field(description="Human-readable posture summary.")
    findings: list[SecurityFinding] = Field(
        default_factory=list, description="All findings carried from the scan."
    )
