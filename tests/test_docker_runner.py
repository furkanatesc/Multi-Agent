"""Unit tests for DockerRunner with a fully mocked Docker client.

No real containers are created — a fake client records the exec commands and
returns scripted exit codes, so we verify lifecycle (create→start→upload→exec→
remove), the install short-circuit, timeout wrapping, and result aggregation.
"""

import tarfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.integrations.docker_runner import (
    CommandResult,
    DockerError,
    DockerRunner,
    RunResult,
)


class _FakeContainer:
    """Records uploads/exec calls and returns scripted exec results."""

    def __init__(self, exec_results: dict[str, tuple[int, bytes]]) -> None:
        self._exec_results = exec_results
        self.exec_calls: list[str] = []
        self.uploaded: bytes | None = None
        self.started = False
        self.removed = False

    def start(self) -> None:
        self.started = True

    def put_archive(self, path: str, data: bytes) -> None:
        self.uploaded = data

    def exec_run(self, cmd: list[str], workdir: str, demux: bool) -> SimpleNamespace:
        # cmd is ["sh", "-c", "timeout N <command>"] — record the inner command.
        inner = cmd[2]
        self.exec_calls.append(inner)
        for key, (code, out) in self._exec_results.items():
            if key in inner:
                return SimpleNamespace(exit_code=code, output=out)
        return SimpleNamespace(exit_code=0, output=b"")

    def remove(self, force: bool) -> None:
        self.removed = True


def _runner_with(container: _FakeContainer, timeout: int = 30) -> DockerRunner:
    client = MagicMock()
    client.containers.create.return_value = container
    return DockerRunner(client=client, timeout=timeout)


# --------------------------------------------------------------------------- #
# result models
# --------------------------------------------------------------------------- #


def test_command_result_passed() -> None:
    assert CommandResult(0, "ok").passed is True
    assert CommandResult(1, "err").passed is False


def test_run_result_passed_requires_both() -> None:
    ok, bad = CommandResult(0, ""), CommandResult(1, "")
    assert RunResult(lint=ok, tests=ok).passed is True
    assert RunResult(lint=ok, tests=bad).passed is False
    assert RunResult(lint=bad, tests=ok).passed is False


# --------------------------------------------------------------------------- #
# happy path & lifecycle
# --------------------------------------------------------------------------- #


def test_run_checks_passes_and_cleans_up() -> None:
    container = _FakeContainer(
        {"lint": (0, b"lint ok"), "test": (0, b"tests ok")}
    )
    runner = _runner_with(container)

    result = runner.run_checks(
        {"src/a.js": "x"},
        image="node-img",
        lint_cmd="npm run lint",
        test_cmd="npm test",
    )

    assert result.passed is True
    assert container.started is True
    assert container.removed is True  # cleaned up even on success
    assert container.uploaded is not None


def test_uploaded_archive_contains_files() -> None:
    container = _FakeContainer({"lint": (0, b""), "test": (0, b"")})
    runner = _runner_with(container)

    runner.run_checks(
        {"src/App.tsx": "code", "package.json": "{}"},
        image="img",
        lint_cmd="lint",
        test_cmd="test",
    )

    import io

    with tarfile.open(fileobj=io.BytesIO(container.uploaded or b"")) as tar:
        names = set(tar.getnames())
    assert names == {"src/App.tsx", "package.json"}


def test_timeout_wraps_commands() -> None:
    container = _FakeContainer({"lint": (0, b""), "test": (0, b"")})
    runner = _runner_with(container, timeout=15)

    runner.run_checks({}, image="img", lint_cmd="npm run lint", test_cmd="npm test")

    assert any(c.startswith("timeout 15 ") for c in container.exec_calls)


# --------------------------------------------------------------------------- #
# failures
# --------------------------------------------------------------------------- #


def test_lint_failure_reported() -> None:
    container = _FakeContainer(
        {"lint": (1, b"eslint error"), "test": (0, b"")}
    )
    runner = _runner_with(container)

    result = runner.run_checks({}, image="img", lint_cmd="lint", test_cmd="test")

    assert result.passed is False
    assert result.lint.passed is False
    assert "eslint error" in result.lint.output


def test_install_failure_short_circuits() -> None:
    container = _FakeContainer(
        {"install": (1, b"npm ERR"), "lint": (0, b""), "test": (0, b"")}
    )
    runner = _runner_with(container)

    result = runner.run_checks(
        {}, image="img", lint_cmd="lint", test_cmd="test", install_cmd="npm install"
    )

    assert result.passed is False
    # Lint/test never ran — only the install command was executed.
    assert container.exec_calls == ["timeout 30 npm install"]


def test_container_removed_on_exec_error() -> None:
    container = _FakeContainer({})
    container.exec_run = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    runner = _runner_with(container)

    with pytest.raises(RuntimeError):
        runner.run_checks({}, image="img", lint_cmd="lint", test_cmd="test")
    assert container.removed is True  # cleanup still happened


def test_create_failure_raises_docker_error() -> None:
    client = MagicMock()
    client.containers.create.side_effect = RuntimeError("no image")
    runner = DockerRunner(client=client, timeout=30)

    with pytest.raises(DockerError):
        runner.run_checks({}, image="missing", lint_cmd="lint", test_cmd="test")
