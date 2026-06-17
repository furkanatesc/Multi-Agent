"""Unit tests for InnerLoopRunner with mocked Docker + Coder (no containers).

Verifies the self-fix loop: pass-first-try, fix-then-pass, and the iteration cap
when fixes never succeed. Also checks profile selection and that the image is
ensured before running.
"""

from unittest.mock import MagicMock

from src.agents.coder.inner_loop import (
    _FLUTTER_PROFILE,
    _NODE_PROFILE,
    InnerLoopRunner,
    _profile_for,
)
from src.agents.coder.tools import Workspace
from src.integrations.docker_runner import CommandResult, RunResult


def _run_result(lint_ok: bool, tests_ok: bool) -> RunResult:
    return RunResult(
        lint=CommandResult(0 if lint_ok else 1, "lint"),
        tests=CommandResult(0 if tests_ok else 1, "tests"),
    )


def _coder_returning(fixed_files: dict[str, str], cost: float = 0.05) -> MagicMock:
    """A mock CoderAgent whose self_fix returns ``fixed_files`` + ``cost``."""
    coder = MagicMock()
    coder.self_fix.return_value = (MagicMock(), cost, Workspace(fixed_files))
    return coder


# --------------------------------------------------------------------------- #
# profile selection
# --------------------------------------------------------------------------- #


def test_profile_for_flutter() -> None:
    assert _profile_for("flutter") is _FLUTTER_PROFILE


def test_profile_for_react_native() -> None:
    assert _profile_for("react-native") is _NODE_PROFILE


def test_profile_defaults_to_node() -> None:
    assert _profile_for(None) is _NODE_PROFILE
    assert _profile_for("native-ios") is _NODE_PROFILE


# --------------------------------------------------------------------------- #
# loop behavior
# --------------------------------------------------------------------------- #


def test_passes_first_try_no_self_fix() -> None:
    docker = MagicMock()
    docker.run_checks.return_value = _run_result(True, True)
    coder = MagicMock()
    runner = InnerLoopRunner(coder=coder, docker_runner=docker, max_iterations=3)

    result = runner.run({"a.js": "x"}, "react-native")

    assert result.passed is True
    assert result.iterations == 0
    assert result.cost == 0.0
    coder.self_fix.assert_not_called()
    docker.ensure_image.assert_called_once_with(
        _NODE_PROFILE.image, _NODE_PROFILE.dockerfile
    )


def test_fixes_then_passes() -> None:
    docker = MagicMock()
    # First check fails, second (after fix) passes.
    docker.run_checks.side_effect = [
        _run_result(False, False),
        _run_result(True, True),
    ]
    coder = _coder_returning({"a.js": "fixed"}, cost=0.05)
    runner = InnerLoopRunner(coder=coder, docker_runner=docker, max_iterations=3)

    result = runner.run({"a.js": "broken"}, "react-native")

    assert result.passed is True
    assert result.iterations == 1
    assert result.cost == 0.05
    assert result.files == {"a.js": "fixed"}
    coder.self_fix.assert_called_once()


def test_stops_at_iteration_cap_when_never_fixed() -> None:
    docker = MagicMock()
    docker.run_checks.return_value = _run_result(False, False)  # always failing
    coder = _coder_returning({"a.js": "still broken"}, cost=0.02)
    runner = InnerLoopRunner(coder=coder, docker_runner=docker, max_iterations=3)

    result = runner.run({"a.js": "broken"}, "react-native")

    assert result.passed is False
    assert result.iterations == 3  # capped
    assert coder.self_fix.call_count == 3
    assert result.cost == 0.06  # 3 * 0.02
    # initial check + one re-check per fix
    assert docker.run_checks.call_count == 4


def test_self_fix_receives_failure_output() -> None:
    docker = MagicMock()
    docker.run_checks.side_effect = [
        RunResult(CommandResult(1, "LINT-ERR"), CommandResult(1, "TEST-ERR")),
        _run_result(True, True),
    ]
    coder = _coder_returning({"a.js": "ok"})
    runner = InnerLoopRunner(coder=coder, docker_runner=docker, max_iterations=3)

    runner.run({"a.js": "x"}, "react-native")

    _args, kwargs = coder.self_fix.call_args
    passed_args = list(_args) + list(kwargs.values())
    assert "LINT-ERR" in passed_args
    assert "TEST-ERR" in passed_args


def test_flutter_platform_uses_flutter_profile() -> None:
    docker = MagicMock()
    docker.run_checks.return_value = _run_result(True, True)
    runner = InnerLoopRunner(coder=MagicMock(), docker_runner=docker, max_iterations=1)

    runner.run({"main.dart": "x"}, "flutter")

    docker.ensure_image.assert_called_once_with(
        _FLUTTER_PROFILE.image, _FLUTTER_PROFILE.dockerfile
    )
    _args, kwargs = docker.run_checks.call_args
    assert kwargs["image"] == _FLUTTER_PROFILE.image


def test_max_iterations_zero_skips_fixing() -> None:
    docker = MagicMock()
    docker.run_checks.return_value = _run_result(False, False)
    coder = MagicMock()
    runner = InnerLoopRunner(coder=coder, docker_runner=docker, max_iterations=0)

    result = runner.run({"a.js": "x"}, "react-native")

    assert result.passed is False
    assert result.iterations == 0
    coder.self_fix.assert_not_called()
