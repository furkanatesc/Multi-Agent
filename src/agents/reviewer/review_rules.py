"""Deterministic PASS/FAIL verdict rules for the Reviewer agent.

The gate-critical part of a code review — whether the change is approved or sent
back to the Coder — must be *reproducible*, exactly like the Security agent's
score (project decision #6). The LLM is trusted to *locate and classify* issues
(it emits a list of severity-tagged comments); it is **not** trusted to decide
the final verdict. This module derives that verdict from the comment severities.

Severity ladder (highest → lowest impact):

* ``blocker`` — must fix before merge (bug, security hole, broken contract).
* ``major``   — significant design/correctness problem (e.g. a SOLID violation
  with real consequences); also blocks the merge.
* ``minor``   — worth fixing but not merge-blocking.
* ``nit``     — stylistic/preference; never blocks.

A review **FAILs** iff it contains at least one ``blocker`` or ``major`` comment;
otherwise it **PASSes**. Keeping the threshold here (not in the prompt) means the
``review_decision`` edge routes identically for identical findings.
"""

from __future__ import annotations

from typing import Literal

ReviewSeverity = Literal["blocker", "major", "minor", "nit"]
"""Severity tag attached to a single review comment."""

ReviewVerdict = Literal["PASS", "FAIL"]
"""Final, computed outcome of a review (mirrors ``state.ReviewDecision``)."""

#: Severities that block a merge — any of these forces a FAIL verdict.
BLOCKING_SEVERITIES: frozenset[str] = frozenset({"blocker", "major"})


def is_blocking(severity: str) -> bool:
    """Return True if a single comment severity blocks the merge."""
    return severity in BLOCKING_SEVERITIES


def has_blocking_comment(severities: list[str]) -> bool:
    """Return True if any severity in the list blocks the merge."""
    return any(is_blocking(s) for s in severities)


def decide_verdict(severities: list[str]) -> ReviewVerdict:
    """Compute the final PASS/FAIL verdict from all comment severities.

    Args:
        severities: Severity tag of every review comment (empty list = clean).

    Returns:
        ``"FAIL"`` if any comment is ``blocker``/``major``, else ``"PASS"``.
    """
    return "FAIL" if has_blocking_comment(severities) else "PASS"
