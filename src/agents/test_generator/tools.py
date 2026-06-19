"""Helpers for the Test Generator agent.

* ``analyze_code_structure_tool`` — Docker-free heuristic that splits the file
  map into testable source vs. existing tests and summarizes it for the prompt.
* ``run_coverage_tool`` — runs the platform's test+coverage command inside the
  inner-loop toolchain image via :class:`DockerRunner` and best-effort parses the
  reported line-coverage percentage. Degrades gracefully when Docker is down.

The coverage toolchain mirrors ``agents/coder/inner_loop.py``'s profiles (Node
for react-native/JS, Flutter for Dart); generalizing these into a shared
``TargetProfile`` is tracked as post-Sprint-5 work, not done here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.core.logging import logger
from src.integrations.docker_runner import DockerError, DockerRunner

# File extensions we consider testable source code.
_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".dart")
# Path fragments that mark a file as an existing test (not a generation target).
_TEST_MARKERS = (".test.", ".spec.", "_test.", "/__tests__/", "/test/", "test/")

_NUM = re.compile(r"\d+(?:\.\d+)?")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class CodeStructure:
    """Result of the (Docker-free) source/test split analysis."""

    source_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """A short human/LLM-readable description of what needs testing."""
        if not self.source_files and not self.test_files:
            return "No source files found to test."
        lines = [
            f"{len(self.source_files)} source file(s) to cover; "
            f"{len(self.test_files)} existing test file(s)."
        ]
        for path in self.source_files:
            lines.append(f"- source: {path}")
        for path in self.test_files:
            lines.append(f"- existing test: {path}")
        return "\n".join(lines)


@dataclass(frozen=True)
class CoverageResult:
    """Outcome of a Docker coverage run."""

    available: bool
    percent: float
    output: str


@dataclass(frozen=True)
class _CoverageProfile:
    """A platform's coverage toolchain (image reused from the inner loop)."""

    image: str
    dockerfile: str
    install_cmd: str
    coverage_cmd: str


_NODE_COVERAGE = _CoverageProfile(
    image="mobile-agent-node",
    dockerfile="docker/Dockerfile.node",
    install_cmd="npm install",
    coverage_cmd="npm test -- --coverage --watchAll=false || true",
)
_FLUTTER_COVERAGE = _CoverageProfile(
    image="mobile-agent-flutter",
    dockerfile="docker/Dockerfile.dart",
    install_cmd="flutter pub get",
    coverage_cmd="flutter test --coverage || true",
)
_COVERAGE_PROFILES: dict[str, _CoverageProfile] = {
    "react-native": _NODE_COVERAGE,
    "flutter": _FLUTTER_COVERAGE,
}


def _is_test_file(path: str) -> bool:
    """True when a path looks like an existing test file."""
    normalized = path.replace("\\", "/")
    return any(marker in normalized for marker in _TEST_MARKERS)


def analyze_code_structure_tool(files: dict[str, str]) -> CodeStructure:
    """Split ``files`` into testable source vs. existing tests (Docker-free)."""
    source: list[str] = []
    tests: list[str] = []
    for path in sorted(files):
        if not path.endswith(_SOURCE_EXTS):
            continue
        (tests if _is_test_file(path) else source).append(path)
    return CodeStructure(source_files=source, test_files=tests)


def parse_coverage_percent(output: str) -> float:
    """Best-effort parse of a line-coverage percentage from tool output.

    Prefers a Jest-style ``All files`` summary row (whose data columns carry no
    ``%`` sign) and takes its first metric. Otherwise falls back to the first
    explicit ``NN%`` token. Returns ``0.0`` when no number is present.
    """
    for line in output.splitlines():
        if "All files" in line:
            nums = _NUM.findall(line)
            if nums:
                return float(nums[0])
    nums = _PCT.findall(output)
    return float(nums[0]) if nums else 0.0


def run_coverage_tool(
    runner: DockerRunner, files: dict[str, str], platform: Optional[str]
) -> CoverageResult:
    """Run the platform's test+coverage command and parse the percentage.

    Args:
        runner: A :class:`DockerRunner` (the agent passes one only when Docker
            is reachable).
        files: The full ``{path: content}`` map (source + generated tests).
        platform: Target platform; selects the toolchain profile (Node default).

    Returns:
        A :class:`CoverageResult`; ``available=False`` if Docker errors out.
    """
    profile = _COVERAGE_PROFILES.get(platform or "", _NODE_COVERAGE)
    try:
        runner.ensure_image(profile.image, profile.dockerfile)
        result = runner.run_command(
            files,
            image=profile.image,
            command=profile.coverage_cmd,
            install_cmd=profile.install_cmd,
        )
        percent = parse_coverage_percent(result.output)
        logger.info("Coverage run complete", platform=platform, percent=percent)
        return CoverageResult(available=True, percent=percent, output=result.output)
    except DockerError as exc:
        logger.warning("Coverage unavailable (Docker down)", error=str(exc))
        return CoverageResult(available=False, percent=0.0, output="")
