"""TestGeneratorAgent: generates tests for the produced code and checks coverage.

Built directly on :class:`BaseAgent` (LiteLLM + structured output) per the
project's #2 decision — single-shot structured, like the Architect/Security
agents. The flow:

    analyze structure (Docker-free) → ask the LLM for a ``TestSuite`` covering
    the appropriate kinds → merge tests into source_code → (if Docker is up) run
    coverage and compare to the ≥70% target.

When Docker is unavailable, coverage is skipped and the run proceeds with the
generated tests (the downstream Reviewer still sees them).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.base import BaseAgent
from src.agents.test_generator.schemas import TestKind, TestSuite
from src.agents.test_generator.tools import (
    CodeStructure,
    CoverageResult,
    analyze_code_structure_tool,
    run_coverage_tool,
)
from src.core.config import settings
from src.core.logging import logger
from src.integrations.docker_runner import DockerError, DockerRunner
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState

# Coverage target (also stated in the prompt); overridable via guardrails.yaml.
_DEFAULT_TARGET_COVERAGE = 70.0
# Cap how much source we inline into the prompt (defensive token budget).
_MAX_PROMPT_CHARS = 24_000


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    """Load (and cache) the Test Generator system prompt from config/prompts/."""
    path = settings.BASE_DIR / "config" / "prompts" / "test_generator_system.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _suite_schema_json() -> str:
    """Compact JSON schema of TestSuite, embedded in the user prompt."""
    return json.dumps(TestSuite.model_json_schema())


def _kinds_for(platform: Optional[str]) -> list[TestKind]:
    """Which test kinds to request for a platform (Flutter adds widget tests)."""
    if platform == "flutter":
        return ["unit", "widget", "integration"]
    return ["unit", "integration"]


class TestGeneratorAgent(BaseAgent):
    """Generates a test suite for the generated code and verifies coverage."""

    name = "test_generator"
    model_route = "test-generator-model"

    def __init__(
        self,
        client: Optional[LiteLLMClient] = None,
        system_prompt: Optional[str] = None,
        docker_runner: Optional[DockerRunner] = None,
        target_coverage: Optional[float] = None,
    ) -> None:
        super().__init__(client)
        self._system_prompt = system_prompt or _load_system_prompt()
        self._docker_runner = docker_runner
        self.target_coverage = float(
            target_coverage
            if target_coverage is not None
            else settings.guardrails.get(
                "min_test_coverage", _DEFAULT_TARGET_COVERAGE
            )
        )

    # --- public API (per sprint plan) ------------------------------------- #

    def generate_unit_tests(self, files: dict[str, str]) -> tuple[TestSuite, float]:
        """Generate unit tests for the given source files."""
        return self._generate(files, ["unit"])

    def generate_widget_tests(self, files: dict[str, str]) -> tuple[TestSuite, float]:
        """Generate widget/component tests for the given source files."""
        return self._generate(files, ["widget"])

    def generate_integration_tests(
        self, files: dict[str, str]
    ) -> tuple[TestSuite, float]:
        """Generate integration tests for the given source files."""
        return self._generate(files, ["integration"])

    # --- graph node entry point ------------------------------------------- #

    def run(self, state: AgentState) -> dict[str, Any]:
        """Generate tests for the current source and return a partial state update.

        Writes the generated test files into ``source_code`` (merged by the
        state reducer) and sets ``tests_passed`` from the coverage check when it
        could run, else leaves the pipeline flowing.
        """
        files = state.get("source_code") or {}
        platform = state.get("platform")

        suite, cost = self._generate(files, _kinds_for(platform))
        test_files = {f.path: f.content for f in suite.files}

        coverage = self._measure_coverage({**files, **test_files}, platform)
        if coverage.available:
            tests_passed = coverage.percent >= self.target_coverage
            cov_note = f"coverage={coverage.percent:.1f}% (target {self.target_coverage:.0f}%)"
        else:
            tests_passed = True  # cannot verify offline; let the Reviewer judge
            cov_note = "coverage not measured (Docker unavailable)"

        logger.info(
            "Test generation complete",
            files=len(test_files),
            coverage_available=coverage.available,
            coverage_percent=coverage.percent,
            tests_passed=tests_passed,
        )
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"[test_generator] generated {len(test_files)} test file(s); "
                        f"{cov_note}"
                    ),
                    name=self.name,
                )
            ],
            "source_code": test_files,
            "tests_passed": tests_passed,
            "total_cost_usd": cost,
            "iteration_count": 1,
            "status": "test_generation",
        }

    # --- internals -------------------------------------------------------- #

    def _generate(
        self, files: dict[str, str], kinds: list[TestKind]
    ) -> tuple[TestSuite, float]:
        """Ask the LLM for a structured :class:`TestSuite` of the given kinds."""
        structure = analyze_code_structure_tool(files)
        kinds_str = ", ".join(kinds)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Generate {kinds_str} tests for the project below, targeting "
                    f"at least {self.target_coverage:.0f}% line coverage.\n\n"
                    f"=== CODE STRUCTURE ===\n{structure.summary}\n\n"
                    f"=== SOURCE FILES ===\n{self._render_files(files, structure)}\n\n"
                    f"Return ONLY JSON matching this TestSuite schema:\n"
                    f"{_suite_schema_json()}"
                ),
            },
        ]
        return self.complete_structured(messages, TestSuite)

    def _measure_coverage(
        self, files: dict[str, str], platform: Optional[str]
    ) -> CoverageResult:
        """Run coverage in Docker if reachable, else report unavailable."""
        runner = self._runner()
        if runner is None:
            return CoverageResult(available=False, percent=0.0, output="")
        return run_coverage_tool(runner, files, platform)

    def _runner(self) -> Optional[DockerRunner]:
        """Return a DockerRunner, or ``None`` if the daemon is unavailable."""
        if self._docker_runner is not None:
            return self._docker_runner
        try:
            self._docker_runner = DockerRunner()
        except DockerError:
            logger.warning("Docker unavailable; coverage check skipped")
            return None
        return self._docker_runner

    @staticmethod
    def _render_files(files: dict[str, str], structure: CodeStructure) -> str:
        """Render the source files (tests excluded) bounded by a char budget."""
        targets = structure.source_files or list(files)
        if not targets:
            return "(no source files were generated)"
        out: list[str] = []
        used = 0
        for path in targets:
            block = f"--- FILE: {path} ---\n{files.get(path, '')}"
            if used + len(block) > _MAX_PROMPT_CHARS:
                out.append("--- (remaining files omitted for length) ---")
                break
            out.append(block)
            used += len(block)
        return "\n\n".join(out)
