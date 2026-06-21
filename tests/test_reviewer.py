"""Unit tests for the Reviewer agent (Sprint 6, PR#11).

Covers the deterministic verdict rules, the two-layer schemas, and the
LLM-backed agent (``review_code`` / ``analyze_ci_logs`` / ``create_pr_review`` /
``run``) with a mock client — no live LLM or GitHub access.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, get_args
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agents.reviewer.agent import ReviewerAgent
from src.agents.reviewer.review_rules import (
    BLOCKING_SEVERITIES,
    ReviewSeverity,
    ReviewVerdict,
    decide_verdict,
    has_blocking_comment,
    is_blocking,
)
from src.agents.reviewer.schemas import (
    CILogAnalysis,
    CodeReview,
    ReviewComment,
    ReviewReport,
)

# --------------------------------------------------------------------------- #
# deterministic verdict rules
# --------------------------------------------------------------------------- #


def test_clean_review_passes() -> None:
    assert decide_verdict([]) == "PASS"


def test_blocker_or_major_fails() -> None:
    assert decide_verdict(["blocker"]) == "FAIL"
    assert decide_verdict(["major"]) == "FAIL"
    assert decide_verdict(["minor", "major", "nit"]) == "FAIL"


def test_minor_and_nit_pass() -> None:
    assert decide_verdict(["minor", "nit", "minor"]) == "PASS"


def test_is_blocking_matches_blocking_set() -> None:
    assert is_blocking("blocker") is True
    assert is_blocking("major") is True
    assert is_blocking("minor") is False
    assert is_blocking("nit") is False


def test_has_blocking_comment() -> None:
    assert has_blocking_comment(["nit", "minor"]) is False
    assert has_blocking_comment(["nit", "blocker"]) is True


def test_blocking_set_is_subset_of_severities() -> None:
    assert BLOCKING_SEVERITIES <= set(get_args(ReviewSeverity))
    assert BLOCKING_SEVERITIES == {"blocker", "major"}


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #


def test_comment_defaults() -> None:
    c = ReviewComment(
        file="src/App.tsx",
        severity="minor",
        category="naming",
        message="rename x to count",
    )
    assert c.line is None
    assert c.suggestion is None


def test_comment_rejects_bad_severity() -> None:
    with pytest.raises(ValidationError):
        ReviewComment.model_validate(
            {
                "file": "a.ts",
                "severity": "catastrophic",  # not a valid severity
                "category": "bug",
                "message": "boom",
            }
        )


def test_code_review_defaults_to_empty_comments() -> None:
    review = CodeReview(summary="looks good")
    assert review.comments == []


def test_code_review_ignores_extra_fields() -> None:
    review = CodeReview.model_validate(
        {"summary": "ok", "comments": [], "verdict": "ignored"}
    )
    assert review.summary == "ok"


def test_report_blocking_comments_property() -> None:
    report = ReviewReport(
        verdict="FAIL",
        summary="x",
        comments=[
            ReviewComment(file="a", severity="nit", category="style", message="m"),
            ReviewComment(file="b", severity="major", category="solid", message="m"),
            ReviewComment(file="c", severity="blocker", category="bug", message="m"),
        ],
    )
    assert {c.severity for c in report.blocking_comments} == {"major", "blocker"}


def test_ci_log_analysis_defaults() -> None:
    ci = CILogAnalysis(passed=True, root_cause="n/a")
    assert ci.failing_step is None
    assert ci.suggested_fix is None


# --------------------------------------------------------------------------- #
# ReviewerAgent (mock LLM)
# --------------------------------------------------------------------------- #


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _agent_with_review(
    review: dict[str, Any], costs: tuple[float, float] = (0.0, 0.05)
) -> ReviewerAgent:
    """Construct a ReviewerAgent wired to a mock client returning ``review``."""
    client = MagicMock()
    client.completion.return_value = _fake_response(json.dumps(review))
    client.get_metrics.side_effect = [
        {"total_cost_usd": costs[0]},
        {"total_cost_usd": costs[1]},
    ]
    return ReviewerAgent(client=client, system_prompt="SYSTEM")


def test_review_code_clean_passes() -> None:
    agent = _agent_with_review({"summary": "clean", "comments": []})
    report, cost = agent.review_code({"src/App.tsx": "const x = 1;"})

    assert isinstance(report, ReviewReport)
    assert report.verdict == "PASS"
    assert report.comments == []
    assert cost == pytest.approx(0.05)


def test_review_code_major_fails() -> None:
    review = {
        "summary": "god object",
        "comments": [
            {
                "file": "src/App.tsx",
                "line": 10,
                "severity": "major",
                "category": "SRP",
                "message": "App does data fetching, rendering, and routing.",
            }
        ],
    }
    report, _ = _agent_with_review(review).review_code({"src/App.tsx": "..."})
    assert report.verdict == "FAIL"
    assert len(report.blocking_comments) == 1


def test_review_code_only_nits_passes() -> None:
    review = {
        "summary": "tiny style stuff",
        "comments": [
            {
                "file": "src/App.tsx",
                "severity": "nit",
                "category": "style",
                "message": "double blank line",
            }
        ],
    }
    report, _ = _agent_with_review(review).review_code({"src/App.tsx": "..."})
    assert report.verdict == "PASS"


def test_run_writes_outer_loop_and_decision_channels() -> None:
    agent = _agent_with_review({"summary": "clean", "comments": []})
    update = agent.run({"source_code": {"src/App.tsx": "x"}, "outer_loop_count": 2})

    assert update["review_decision"] == "PASS"
    assert update["review_notes"] == "clean"
    assert update["outer_loop_count"] == 3  # incremented from 2
    assert update["status"] == "review"
    assert update["iteration_count"] == 1
    assert update["total_cost_usd"] == pytest.approx(0.05)
    assert update["messages"][0].name == "reviewer"


def test_run_starts_outer_loop_from_zero() -> None:
    agent = _agent_with_review({"summary": "clean", "comments": []})
    update = agent.run({"source_code": {"a.ts": "x"}})
    assert update["outer_loop_count"] == 1


# --------------------------------------------------------------------------- #
# analyze_ci_logs
# --------------------------------------------------------------------------- #


def test_analyze_ci_logs_empty_skips_llm() -> None:
    client = MagicMock()
    agent = ReviewerAgent(client=client, system_prompt="SYSTEM")
    analysis, cost = agent.analyze_ci_logs("   ")

    assert analysis.passed is True
    assert cost == 0.0
    client.completion.assert_not_called()


def test_analyze_ci_logs_parses_failure() -> None:
    result = {
        "passed": False,
        "failing_step": "pytest",
        "root_cause": "ImportError in test_app.py",
        "suggested_fix": "add the missing dependency",
    }
    agent = _agent_with_review(result)
    analysis, cost = agent.analyze_ci_logs("E   ImportError: no module named foo")

    assert analysis.passed is False
    assert analysis.failing_step == "pytest"
    assert cost == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
# create_pr_review (mock GitHubClient)
# --------------------------------------------------------------------------- #


def _report(verdict: ReviewVerdict, comments: list[ReviewComment]) -> ReviewReport:
    return ReviewReport(verdict=verdict, summary="summary text", comments=comments)


def test_create_pr_review_pass_approves_and_auto_merges() -> None:
    github = MagicMock()
    github.submit_review.return_value = 999
    agent = ReviewerAgent(client=MagicMock(), system_prompt="SYSTEM")

    review_id = agent.create_pr_review(
        _report("PASS", []), github, "owner/repo", 7, auto_merge=True
    )

    assert review_id == 999
    args, kwargs = github.submit_review.call_args
    assert kwargs["event"] == "APPROVE"
    github.auto_merge.assert_called_once_with("owner/repo", 7)


def test_create_pr_review_fail_requests_changes_no_merge() -> None:
    github = MagicMock()
    github.submit_review.return_value = 1
    comments = [
        ReviewComment(
            file="src/api.ts",
            line=12,
            severity="blocker",
            category="bug",
            message="null deref",
            suggestion="guard with if (x)",
        ),
        # no line → must NOT become an inline comment
        ReviewComment(
            file="src/util.ts", severity="minor", category="naming", message="rename"
        ),
    ]
    agent = ReviewerAgent(client=MagicMock(), system_prompt="SYSTEM")

    agent.create_pr_review(_report("FAIL", comments), github, "owner/repo", 7)

    _, kwargs = github.submit_review.call_args
    assert kwargs["event"] == "REQUEST_CHANGES"
    inline = kwargs["comments"]
    assert len(inline) == 1  # only the line-anchored comment
    assert inline[0]["path"] == "src/api.ts"
    assert inline[0]["line"] == 12
    assert "```suggestion" in inline[0]["body"]
    github.auto_merge.assert_not_called()


def test_create_pr_review_pass_without_auto_merge_does_not_merge() -> None:
    github = MagicMock()
    github.submit_review.return_value = 5
    agent = ReviewerAgent(client=MagicMock(), system_prompt="SYSTEM")

    agent.create_pr_review(_report("PASS", []), github, "owner/repo", 7)
    github.auto_merge.assert_not_called()
