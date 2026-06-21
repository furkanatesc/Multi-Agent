"""OWASP Mobile Top 10 (2024) catalog and deterministic security scoring.

The Security agent's LLM emits findings tagged with an OWASP Mobile category and
a severity. This module owns the parts that must **not** depend on LLM
arithmetic: the canonical category catalog, the severity penalty table, and the
0-100 score derived from a finding set. Keeping scoring here (not in the prompt)
makes the ``security_gate`` decision reproducible and unit-testable — the LLM is
trusted to *find* issues, not to *do the math* that gates the pipeline.

Reference: https://owasp.org/www-project-mobile-top-10/ (2024 list).
"""

from __future__ import annotations

from typing import Iterable, Literal, get_args

# --------------------------------------------------------------------------- #
# Type aliases (shared with the schemas as the single source of truth)
# --------------------------------------------------------------------------- #

OWASPCategory = Literal[
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"
]
"""OWASP Mobile Top 10 (2024) category identifiers."""

Severity = Literal["critical", "high", "medium", "low", "info"]
"""Finding severity, highest to lowest impact."""


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

OWASP_MOBILE_TOP_10: dict[str, str] = {
    "M1": "Improper Credential Usage",
    "M2": "Inadequate Supply Chain Security",
    "M3": "Insecure Authentication/Authorization",
    "M4": "Insufficient Input/Output Validation",
    "M5": "Insecure Communication",
    "M6": "Inadequate Privacy Controls",
    "M7": "Insufficient Binary Protections",
    "M8": "Security Misconfiguration",
    "M9": "Insecure Data Storage",
    "M10": "Insufficient Cryptography",
}
"""Canonical ``{id: title}`` map of the OWASP Mobile Top 10 categories."""

# Score penalty subtracted from a perfect 100, per finding, by severity.
_SEVERITY_PENALTY: dict[str, int] = {
    "critical": 40,
    # 25 (not 20) so a single HIGH finding drops the score to 75 — below the
    # PASSING_SCORE gate — forcing a Coder fix instead of slipping through at 80.
    "high": 25,
    "medium": 10,
    "low": 3,
    "info": 0,
}

# The minimum acceptable score; mirrors edges._MIN_SECURITY_SCORE (the gate
# threshold). Defined here as documentation for the scoring scale.
PASSING_SCORE = 80


def category_title(category: str) -> str:
    """Return the human-readable title for an OWASP category id (or 'Unknown')."""
    return OWASP_MOBILE_TOP_10.get(category, "Unknown")


def severity_penalty(severity: str) -> int:
    """Return the score penalty for a single finding of the given severity."""
    return _SEVERITY_PENALTY.get(severity, 0)


def compute_score(severities: Iterable[str]) -> int:
    """Compute a 0-100 security score from a set of finding severities.

    Starts from a perfect 100 and subtracts each finding's severity penalty,
    clamped to the ``[0, 100]`` range. An empty finding set scores 100.

    Args:
        severities: The severity of each finding (order-independent).

    Returns:
        The clamped integer score.
    """
    score = 100 - sum(severity_penalty(s) for s in severities)
    return max(0, min(100, score))


def has_critical(severities: Iterable[str]) -> bool:
    """Return True if any finding is ``critical`` (i.e. requires a HITL gate).

    Only ``critical`` escalates to a human gate; ``high`` and below reduce the
    score and are handled by the score-threshold ``fix`` route in
    ``orchestrator.edges.security_gate``.
    """
    return any(s == "critical" for s in severities)


# Validated at import: the penalty table covers every declared severity.
assert set(_SEVERITY_PENALTY) == set(get_args(Severity)), (
    "severity penalty table is out of sync with the Severity literal"
)
