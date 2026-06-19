"""Unit tests for the Security agent foundation (Sprint 5, PR#7).

This file currently covers the *deterministic* foundation — the OWASP catalog,
the score computation, and the output schemas. Agent-level tests (LLM-backed
``scan_code``/``run`` with a mock client, and the vulnerable-code samples) are
added alongside the agent implementation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional, cast, get_args
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agents.security.agent import SecurityAgent
from src.agents.security.owasp_rules import (
    OWASP_MOBILE_TOP_10,
    OWASPCategory,
    Severity,
    category_title,
    compute_score,
    has_critical,
    severity_penalty,
)
from src.agents.security.schemas import (
    SecurityFinding,
    SecurityReport,
    SecurityScan,
)
from src.agents.security.tools import check_dependencies_tool
from src.integrations.docker_runner import CommandResult, DockerError, DockerRunner


# --------------------------------------------------------------------------- #
# OWASP catalog
# --------------------------------------------------------------------------- #


def test_catalog_covers_m1_through_m10() -> None:
    assert set(OWASP_MOBILE_TOP_10) == set(get_args(OWASPCategory))
    assert len(OWASP_MOBILE_TOP_10) == 10


def test_category_title_known_and_unknown() -> None:
    assert category_title("M9") == "Insecure Data Storage"
    assert category_title("M99") == "Unknown"


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def test_clean_scan_scores_100() -> None:
    assert compute_score([]) == 100


def test_penalties_subtract_from_100() -> None:
    # one high (25) + one medium (10) -> 65
    assert compute_score(["high", "medium"]) == 65


def test_single_high_finding_fails_the_gate() -> None:
    # A lone HIGH must land below PASSING_SCORE (80) so the gate routes to fix.
    from src.agents.security.owasp_rules import PASSING_SCORE

    assert compute_score(["high"]) < PASSING_SCORE


def test_score_clamped_at_zero() -> None:
    # three criticals (120) would be negative -> clamped
    assert compute_score(["critical", "critical", "critical"]) == 0


def test_info_findings_do_not_lower_score() -> None:
    assert compute_score(["info", "info"]) == 100
    assert severity_penalty("info") == 0


def test_unknown_severity_has_zero_penalty() -> None:
    assert severity_penalty("bogus") == 0


def test_severity_penalties_are_ordered() -> None:
    order = ["critical", "high", "medium", "low", "info"]
    penalties = [severity_penalty(s) for s in order]
    assert penalties == sorted(penalties, reverse=True)


# --------------------------------------------------------------------------- #
# critical detection (HITL gate trigger)
# --------------------------------------------------------------------------- #


def test_has_critical_true_only_for_critical() -> None:
    assert has_critical(["critical"]) is True
    assert has_critical(["high", "medium", "low"]) is False
    assert has_critical([]) is False


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #


def test_finding_validates_and_defaults() -> None:
    f = SecurityFinding(
        owasp_id="M9",
        title="Plaintext token in storage",
        severity="high",
        file="src/auth/store.ts",
        description="JWT written to AsyncStorage unencrypted.",
    )
    assert f.line is None
    assert f.recommendation is None


def test_finding_rejects_bad_category() -> None:
    # Built from a dict (not kwargs) so this is a *runtime* validation test, not
    # a static type error on the deliberately-invalid category.
    with pytest.raises(ValidationError):
        SecurityFinding.model_validate(
            {
                "owasp_id": "M42",  # not a valid category
                "title": "x",
                "severity": "low",
                "file": "a.ts",
                "description": "d",
            }
        )


def test_scan_defaults_to_empty_findings() -> None:
    scan = SecurityScan(summary="looks clean")
    assert scan.findings == []


def test_scan_ignores_extra_fields() -> None:
    scan = SecurityScan.model_validate(
        {"summary": "ok", "findings": [], "extra_noise": 123}
    )
    assert scan.summary == "ok"


def test_report_score_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        SecurityReport(score=101, has_critical=False, summary="x")
    with pytest.raises(ValidationError):
        SecurityReport(score=-1, has_critical=False, summary="x")


def test_severity_literal_matches_penalty_table_keys() -> None:
    # Guards against drift between the schema's Severity and the scorer.
    assert set(get_args(Severity)) == {
        "critical",
        "high",
        "medium",
        "low",
        "info",
    }


# --------------------------------------------------------------------------- #
# dependency audit tool (Docker-free, OWASP M2)
# --------------------------------------------------------------------------- #


def test_dependency_audit_flags_unpinned_npm() -> None:
    files = {
        "package.json": json.dumps(
            {"dependencies": {"left-pad": "*", "react": "18.2.0", "axios": "^1.0.0"}}
        )
    }
    result = check_dependencies_tool(files)
    assert result.available is True
    assert "left-pad" in result.output  # '*' is risky
    assert "axios" in result.output  # '^' is risky
    assert "react" not in result.output  # pinned


def test_dependency_audit_clean_when_pinned() -> None:
    files = {"package.json": json.dumps({"dependencies": {"react": "18.2.0"}})}
    result = check_dependencies_tool(files)
    assert "pinned" in result.output.lower()


def test_dependency_audit_no_manifest() -> None:
    result = check_dependencies_tool({"src/App.tsx": "code"})
    assert "no dependency manifest" in result.output.lower()


def test_dependency_audit_flags_floating_pubspec() -> None:
    files = {"pubspec.yaml": "dependencies:\n  http: any\n  flutter:\n    sdk: flutter\n"}
    result = check_dependencies_tool(files)
    assert "floating" in result.output.lower()


# --------------------------------------------------------------------------- #
# SecurityAgent (mock LLM + fake Docker runner)
# --------------------------------------------------------------------------- #


class _FakeRunner:
    """A DockerRunner stand-in returning canned scanner output (no real Docker)."""

    def __init__(self, output: str = "no findings") -> None:
        self._output = output

    def ensure_image(self, tag: str, dockerfile: str) -> None:
        ...

    def run_command(
        self,
        files: dict[str, str],
        image: str,
        command: str,
        install_cmd: Optional[str] = None,
    ) -> CommandResult:
        return CommandResult(0, self._output)


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _agent_with_scan(
    scan: dict[str, Any], costs: tuple[float, float] = (0.0, 0.07)
) -> SecurityAgent:
    """Construct a SecurityAgent wired to a mock client + fake Docker runner."""
    client = MagicMock()
    client.completion.return_value = _fake_response(json.dumps(scan))
    client.get_metrics.side_effect = [
        {"total_cost_usd": costs[0]},
        {"total_cost_usd": costs[1]},
    ]
    return SecurityAgent(
        client=client,
        system_prompt="SYSTEM",
        docker_runner=cast("DockerRunner", _FakeRunner()),
    )


def test_scan_code_clean_scores_100() -> None:
    agent = _agent_with_scan({"summary": "clean", "findings": []})
    report, cost = agent.scan_code({"src/App.tsx": "const x = 1;"})

    assert isinstance(report, SecurityReport)
    assert report.score == 100
    assert report.has_critical is False
    assert cost == pytest.approx(0.07)


def test_scan_code_single_high_scores_75_no_hitl() -> None:
    scan = {
        "summary": "one high issue",
        "findings": [
            {
                "owasp_id": "M5",
                "title": "Cleartext HTTP",
                "severity": "high",
                "file": "src/api.ts",
                "description": "Uses http:// for API calls.",
            }
        ],
    }
    report, _ = _agent_with_scan(scan).scan_code({"src/api.ts": "fetch('http://x')"})
    assert report.score == 75
    assert report.has_critical is False  # high does not trigger HITL


def test_scan_code_critical_sets_hitl_flag() -> None:
    scan = {
        "summary": "hardcoded secret",
        "findings": [
            {
                "owasp_id": "M1",
                "title": "Hardcoded API key",
                "severity": "critical",
                "file": "src/config.ts",
                "description": "Production API key committed in source.",
            }
        ],
    }
    report, _ = _agent_with_scan(scan).scan_code({"src/config.ts": "KEY='abc'"})
    assert report.score == 60
    assert report.has_critical is True


def test_run_writes_gate_state_channels() -> None:
    scan = {"summary": "clean", "findings": []}
    agent = _agent_with_scan(scan)
    update = agent.run({"source_code": {"src/App.tsx": "x"}})

    assert update["security_score"] == 100
    assert update["security_critical"] is False
    assert update["status"] == "security_scan"
    assert update["iteration_count"] == 1
    assert update["total_cost_usd"] == pytest.approx(0.07)
    assert update["messages"][0].name == "security"


def test_scanners_skipped_when_docker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force DockerRunner() construction to fail → LLM-only review still works.
    monkeypatch.setattr(
        "src.agents.security.agent.DockerRunner",
        MagicMock(side_effect=DockerError("daemon down")),
    )
    client = MagicMock()
    client.completion.return_value = _fake_response(
        json.dumps({"summary": "clean", "findings": []})
    )
    client.get_metrics.side_effect = [
        {"total_cost_usd": 0.0},
        {"total_cost_usd": 0.02},
    ]
    # No injected runner → agent must lazily try DockerRunner and degrade.
    agent = SecurityAgent(client=client, system_prompt="SYSTEM")

    report, _ = agent.scan_code({"src/App.tsx": "x"})
    assert report.score == 100  # degraded but functional
    assert agent.detect_secrets({"src/App.tsx": "x"}).available is False
