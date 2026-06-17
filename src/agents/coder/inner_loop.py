"""Inner self-fix loop: lint/test in Docker, fix, repeat (Sprint 4).

This is the *imperative* loop the graph's ``inner_loop_check`` node delegates to.
It encapsulates the whole self-fix cycle (decision: keep the loop here, not in the
graph topology) so the Coder's error-context never has to be threaded through
graph state:

    run checks → pass?  ──► done
                 fail ──► CoderAgent.self_fix(errors) → run checks → …

bounded by ``max_inner_loop_iterations`` (guardrails). When the cap is hit while
still failing, it returns the last (failing) result; the downstream graph edge
then proceeds and lets the security/review gates handle it.

Platform → toolchain mapping lives in ``_PROFILES``. This is deliberately a small
internal table for now (Node/React-Native + Flutter); generalizing it into a
pluggable ``TargetProfile`` is tracked as post-Sprint-4 work, not done here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.agents.coder.agent import CoderAgent
from src.core.config import settings
from src.core.logging import logger
from src.integrations.docker_runner import DockerRunner, RunResult

_DEFAULT_MAX_ITERATIONS = 3


@dataclass(frozen=True)
class _Profile:
    """A platform's container image + lint/test command set."""

    image: str
    dockerfile: str
    install_cmd: str
    lint_cmd: str
    test_cmd: str


# Node toolchain covers react-native (and is the sensible default for other
# JS/TS targets); Flutter gets the Dart/Flutter image.
_NODE_PROFILE = _Profile(
    image="mobile-agent-node",
    dockerfile="docker/Dockerfile.node",
    install_cmd="npm install",
    lint_cmd="npm run lint --if-present",
    test_cmd="npm test --if-present",
)
_FLUTTER_PROFILE = _Profile(
    image="mobile-agent-flutter",
    dockerfile="docker/Dockerfile.dart",
    install_cmd="flutter pub get",
    lint_cmd="flutter analyze",
    test_cmd="flutter test",
)
_PROFILES: dict[str, _Profile] = {
    "react-native": _NODE_PROFILE,
    "flutter": _FLUTTER_PROFILE,
}


def _profile_for(platform: Optional[str]) -> _Profile:
    """Resolve a platform to its toolchain profile (Node is the default)."""
    return _PROFILES.get(platform or "", _NODE_PROFILE)


@dataclass(frozen=True)
class InnerLoopResult:
    """Outcome of an inner-loop run over a file set."""

    files: dict[str, str]
    lint_passed: bool
    tests_passed: bool
    iterations: int
    cost: float

    @property
    def passed(self) -> bool:
        """True when both lint and tests passed."""
        return self.lint_passed and self.tests_passed


class InnerLoopRunner:
    """Drives the Docker lint/test → self-fix cycle to a bounded fixpoint."""

    def __init__(
        self,
        coder: Optional[CoderAgent] = None,
        docker_runner: Optional[DockerRunner] = None,
        max_iterations: Optional[int] = None,
    ) -> None:
        """Wire the runner to a Coder and a DockerRunner (both injectable)."""
        self.coder = coder or CoderAgent()
        self.docker = docker_runner or DockerRunner()
        self.max_iterations = int(
            max_iterations
            if max_iterations is not None
            else settings.guardrails.get(
                "max_inner_loop_iterations", _DEFAULT_MAX_ITERATIONS
            )
        )

    def run(
        self, files: dict[str, str], platform: Optional[str]
    ) -> InnerLoopResult:
        """Run lint/test, self-fixing up to the iteration cap.

        Args:
            files: The generated ``{path: content}`` map to validate.
            platform: Target platform, selects the toolchain profile.

        Returns:
            An :class:`InnerLoopResult` with the (possibly fixed) files, the
            final lint/test verdicts, the number of self-fix iterations spent,
            and the accumulated self-fix cost.
        """
        profile = _profile_for(platform)
        self.docker.ensure_image(profile.image, profile.dockerfile)

        current = dict(files)
        result = self._check(current, profile)
        total_cost = 0.0
        iterations = 0

        while not result.passed and iterations < self.max_iterations:
            iterations += 1
            logger.info(
                "Inner loop: attempting self-fix",
                iteration=iterations,
                lint_passed=result.lint.passed,
                tests_passed=result.tests.passed,
            )
            _fix, cost, workspace = self.coder.self_fix(
                current, result.lint.output, result.tests.output
            )
            total_cost += cost
            current = dict(workspace.files)
            result = self._check(current, profile)

        logger.info(
            "Inner loop finished",
            iterations=iterations,
            lint_passed=result.lint.passed,
            tests_passed=result.tests.passed,
            cost_usd=round(total_cost, 6),
        )
        return InnerLoopResult(
            files=current,
            lint_passed=result.lint.passed,
            tests_passed=result.tests.passed,
            iterations=iterations,
            cost=total_cost,
        )

    def _check(self, files: dict[str, str], profile: _Profile) -> RunResult:
        """Run lint + tests for ``files`` using ``profile``'s toolchain."""
        return self.docker.run_checks(
            files,
            image=profile.image,
            lint_cmd=profile.lint_cmd,
            test_cmd=profile.test_cmd,
            install_cmd=profile.install_cmd,
        )
