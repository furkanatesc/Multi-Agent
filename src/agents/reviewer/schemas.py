"""Pydantic schemas for the Reviewer agent.

Two layers, mirroring the Security agent's design:

* :class:`CodeReview` is the **LLM-facing** structured-output contract — the
  model returns an overall summary plus a list of :class:`ReviewComment`. It is
  *not* trusted to decide the merge verdict.
* :class:`ReviewReport` is the **final** result the agent assembles: its
  ``verdict`` (``PASS``/``FAIL``) is computed deterministically from the
  comments' severities via ``review_rules.decide_verdict`` (see
  ``agents/reviewer/agent.py``), so the ``review_decision`` edge never depends
  on LLM arithmetic.

:class:`CILogAnalysis` is a separate structured contract used by
:meth:`ReviewerAgent.analyze_ci_logs` to turn raw CI output into a root-cause +
suggested-fix summary that can be folded into the review context.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.reviewer.review_rules import ReviewSeverity, ReviewVerdict


class _Schema(BaseModel):
    """Base config: ignore unexpected LLM fields rather than hard-failing."""

    model_config = ConfigDict(extra="ignore")


class ReviewComment(_Schema):
    """A single review remark located in the generated source."""

    file: str = Field(description="Relative path of the file the comment is about.")
    line: Optional[int] = Field(
        default=None, description="1-based line number, if the issue is line-specific."
    )
    severity: ReviewSeverity = Field(
        description="One of: blocker, major, minor, nit."
    )
    category: str = Field(
        description="Concern area, e.g. a SOLID principle, 'clean-code', 'bug', "
        "'security', 'naming', 'tests'."
    )
    message: str = Field(description="What the problem is and why it matters.")
    suggestion: Optional[str] = Field(
        default=None, description="Concrete improvement, ideally as a code snippet."
    )


class CodeReview(_Schema):
    """LLM-facing structured output: an overall summary plus all comments."""

    summary: str = Field(
        description="One-paragraph overall assessment of the change."
    )
    comments: list[ReviewComment] = Field(
        default_factory=list,
        description="Every review comment; an empty list means the change is clean.",
    )


class ReviewReport(_Schema):
    """Final report — ``verdict`` is computed from comments, not LLM-emitted."""

    verdict: ReviewVerdict = Field(
        description="PASS or FAIL (computed from comment severities)."
    )
    summary: str = Field(description="Human-readable overall assessment.")
    comments: list[ReviewComment] = Field(
        default_factory=list, description="All comments carried from the review."
    )

    @property
    def blocking_comments(self) -> list[ReviewComment]:
        """Return only the comments that forced (or would force) a FAIL."""
        from src.agents.reviewer.review_rules import is_blocking

        return [c for c in self.comments if is_blocking(c.severity)]


class CILogAnalysis(_Schema):
    """LLM-facing structured analysis of a CI run's logs."""

    passed: bool = Field(description="True if the CI run appears to have succeeded.")
    failing_step: Optional[str] = Field(
        default=None, description="Name/identifier of the first failing step, if any."
    )
    root_cause: str = Field(
        description="Concise explanation of why CI failed (or 'n/a' when passing)."
    )
    suggested_fix: Optional[str] = Field(
        default=None, description="Actionable guidance to make CI pass."
    )
