"""Unit tests for the Test Generator agent (Sprint 5, PR#8).

Covers the Docker-free structure analysis, coverage parsing, the schemas, and
the agent's generate/run flow with a mock LLM client and a fake Docker runner.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agents.test_generator.agent import TestGeneratorAgent, _kinds_for
from src.agents.test_generator.schemas import GeneratedTestFile, TestSuite
from src.agents.test_generator.tools import (
    CoverageResult,
    analyze_code_structure_tool,
    parse_coverage_percent,
    run_coverage_tool,
)
from src.integrations.docker_runner import CommandResult, DockerError, DockerRunner


# --------------------------------------------------------------------------- #
# structure analysis (Docker-free)
# --------------------------------------------------------------------------- #


def test_analyze_splits_source_and_tests() -> None:
    files = {
        "src/auth.ts": "x",
        "src/__tests__/auth.test.ts": "t",
        "src/Button.tsx": "c",
        "README.md": "doc",  # ignored (not a source ext)
    }
    structure = analyze_code_structure_tool(files)
    assert structure.source_files == ["src/Button.tsx", "src/auth.ts"]
    assert structure.test_files == ["src/__tests__/auth.test.ts"]


def test_analyze_recognizes_dart_and_spec_markers() -> None:
    files = {
        "lib/main.dart": "x",
        "test/main_test.dart": "t",
        "src/util.spec.js": "s",
    }
    structure = analyze_code_structure_tool(files)
    assert "lib/main.dart" in structure.source_files
    assert "test/main_test.dart" in structure.test_files
    assert "src/util.spec.js" in structure.test_files


def test_structure_summary_handles_empty() -> None:
    assert "No source files" in analyze_code_structure_tool({}).summary


# --------------------------------------------------------------------------- #
# coverage parsing
# --------------------------------------------------------------------------- #


def test_parse_coverage_prefers_all_files_row() -> None:
    output = (
        "File      | % Stmts | % Lines\n"
        "All files |   85.3  |  82.1 %\n"
        "auth.ts   |   90    |  88 %\n"
    )
    assert parse_coverage_percent(output) == 85.3


def test_parse_coverage_fallback_first_percent() -> None:
    assert parse_coverage_percent("total coverage: 73.5%") == 73.5


def test_parse_coverage_none_returns_zero() -> None:
    assert parse_coverage_percent("no numbers here") == 0.0


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #


def test_suite_defaults_empty_files() -> None:
    suite = TestSuite(summary="nothing testable")
    assert suite.files == []


def test_generated_file_rejects_bad_kind() -> None:
    with pytest.raises(ValidationError):
        GeneratedTestFile.model_validate(
            {"path": "a.test.ts", "content": "x", "kind": "e2e", "target": "a"}
        )


# --------------------------------------------------------------------------- #
# _kinds_for platform mapping
# --------------------------------------------------------------------------- #


def test_kinds_for_flutter_includes_widget() -> None:
    assert "widget" in _kinds_for("flutter")


def test_kinds_for_react_native_excludes_widget() -> None:
    assert _kinds_for("react-native") == ["unit", "integration"]


def test_kinds_for_unknown_defaults() -> None:
    assert _kinds_for(None) == ["unit", "integration"]


# --------------------------------------------------------------------------- #
# coverage tool with fake runner
# --------------------------------------------------------------------------- #


class _FakeRunner:
    """DockerRunner stand-in returning canned coverage output."""

    def __init__(self, output: str = "All files | 80 %") -> None:
        self._output = output
        self.commands: list[str] = []

    def ensure_image(self, tag: str, dockerfile: str) -> None:
        ...

    def run_command(
        self,
        files: dict[str, str],
        image: str,
        command: str,
        install_cmd: Optional[str] = None,
    ) -> CommandResult:
        self.commands.append(command)
        return CommandResult(0, self._output)


def test_run_coverage_parses_percent() -> None:
    runner = _FakeRunner("All files | 88.0 %")
    result = run_coverage_tool(
        cast(DockerRunner, runner), {"src/a.ts": "x"}, "react-native"
    )
    assert result.available is True
    assert result.percent == 88.0
    assert any("npm test" in c for c in runner.commands)


def test_run_coverage_flutter_profile() -> None:
    runner = _FakeRunner("All files | 75 %")
    run_coverage_tool(cast(DockerRunner, runner), {"lib/main.dart": "x"}, "flutter")
    assert any("flutter test" in c for c in runner.commands)


# --------------------------------------------------------------------------- #
# agent (mock LLM + fake runner)
# --------------------------------------------------------------------------- #


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


_SUITE: dict[str, Any] = {
    "summary": "Unit tests for auth service.",
    "files": [
        {
            "path": "src/__tests__/auth.test.ts",
            "content": "describe('auth', () => { it('works', () => {}); });",
            "kind": "unit",
            "target": "auth service",
        }
    ],
}


def _agent(
    suite: dict[str, Any],
    runner: Optional[_FakeRunner],
    costs: tuple[float, float] = (0.0, 0.09),
) -> TestGeneratorAgent:
    client = MagicMock()
    client.completion.return_value = _fake_response(json.dumps(suite))
    client.get_metrics.side_effect = [
        {"total_cost_usd": costs[0]},
        {"total_cost_usd": costs[1]},
    ]
    return TestGeneratorAgent(
        client=client,
        system_prompt="SYSTEM",
        docker_runner=cast(DockerRunner, runner) if runner else None,
        target_coverage=70.0,
    )


def test_generate_unit_tests_returns_suite() -> None:
    suite, cost = _agent(_SUITE, _FakeRunner()).generate_unit_tests(
        {"src/auth.ts": "export const x = 1;"}
    )
    assert isinstance(suite, TestSuite)
    assert suite.files[0].kind == "unit"
    assert cost == pytest.approx(0.09)


def test_run_merges_tests_and_passes_when_coverage_meets_target() -> None:
    agent = _agent(_SUITE, _FakeRunner("All files | 82 %"))
    update = agent.run({"source_code": {"src/auth.ts": "x"}, "platform": "react-native"})

    assert update["source_code"] == {
        "src/__tests__/auth.test.ts": _SUITE["files"][0]["content"]
    }
    assert update["tests_passed"] is True
    assert update["status"] == "test_generation"
    assert update["messages"][0].name == "test_generator"


def test_run_fails_when_coverage_below_target() -> None:
    agent = _agent(_SUITE, _FakeRunner("All files | 55 %"))
    update = agent.run({"source_code": {"src/auth.ts": "x"}, "platform": "react-native"})
    assert update["tests_passed"] is False


def test_run_proceeds_when_docker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No injected runner + DockerRunner() construction fails → coverage skipped.
    monkeypatch.setattr(
        "src.agents.test_generator.agent.DockerRunner",
        MagicMock(side_effect=DockerError("daemon down")),
    )
    agent = _agent(_SUITE, None)
    update = agent.run({"source_code": {"src/auth.ts": "x"}, "platform": "react-native"})
    assert update["tests_passed"] is True  # cannot verify offline; proceed
