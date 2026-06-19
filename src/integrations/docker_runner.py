"""Sandboxed lint/test execution in disposable Docker containers (Sprint 4).

The Coder generates files into an in-memory workspace; to know whether that code
actually lints and passes tests, we run it in a throwaway container. This module
owns that container lifecycle and nothing else — the self-fix *loop* lives in
``agents/coder/inner_loop.py``.

Design choices (the main S4 risk is Docker cross-platform behavior):

* **Files are injected via ``put_archive`` (an in-memory tar), never bind-mounts.**
  Bind-mounting host paths is fragile on Windows (path translation, permissions);
  streaming a tar into the container is host-agnostic and deterministic.
* **Commands run through ``sh -c`` wrapped in coreutils ``timeout``**, so a
  runaway lint/test can't hang the run. The timeout default comes from
  ``guardrails.yaml``.
* **The container is always removed** (``finally``), even on failure, so repeated
  inner-loop iterations don't leak containers.
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from typing import Any, Optional

from docker.errors import ImageNotFound

import docker
from src.core.config import settings
from src.core.logging import logger

_DEFAULT_WORKDIR = "/app"
_DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a single command executed inside the container."""

    exit_code: int
    output: str

    @property
    def passed(self) -> bool:
        """True when the command exited 0."""
        return self.exit_code == 0


@dataclass(frozen=True)
class RunResult:
    """Combined lint + test outcome for one workspace snapshot."""

    lint: CommandResult
    tests: CommandResult

    @property
    def passed(self) -> bool:
        """True only when both lint and tests passed."""
        return self.lint.passed and self.tests.passed


class DockerError(Exception):
    """Raised when the Docker environment is unavailable or misbehaves."""


class DockerRunner:
    """Runs lint/test commands for a file set in a disposable container."""

    def __init__(
        self,
        client: Optional[Any] = None,
        timeout: Optional[int] = None,
        workdir: str = _DEFAULT_WORKDIR,
    ) -> None:
        """Bind to a Docker client (created from env if not injected).

        Args:
            client: A ``docker.DockerClient`` (injected in tests). When ``None``,
                one is created via ``docker.from_env()``.
            timeout: Per-command timeout in seconds (defaults to the guardrail
                ``timeout_seconds``).
            workdir: Working directory inside the container.
        """
        self._client = client if client is not None else self._connect()
        self.timeout = int(
            timeout
            if timeout is not None
            else settings.guardrails.get("timeout_seconds", _DEFAULT_TIMEOUT)
        )
        self.workdir = workdir

    @staticmethod
    def _connect() -> Any:
        """Create a Docker client from the environment, or fail clearly."""
        try:
            return docker.from_env()  # type: ignore[attr-defined]
        except Exception as exc:  # docker raises various errors when daemon is down
            raise DockerError(
                "could not connect to the Docker daemon — is Docker running?"
            ) from exc

    # --- public API ------------------------------------------------------- #

    def ensure_image(self, tag: str, dockerfile: str) -> None:
        """Build ``tag`` from ``dockerfile`` if it isn't already present locally.

        Idempotent: a present image is left untouched, so repeated inner-loop
        runs pay the (slow) build cost at most once. The build context is the
        repository root so the Dockerfile can reference project files if needed.

        Args:
            tag: Local image tag to ensure (e.g. ``"mobile-agent-node"``).
            dockerfile: Path to the Dockerfile, relative to the repo root.

        Raises:
            DockerError: If the build fails.
        """
        try:
            self._client.images.get(tag)
            return
        except ImageNotFound:
            pass
        except Exception as exc:
            raise DockerError(f"could not query image {tag!r}") from exc

        context = str(settings.BASE_DIR)
        logger.info("Building Docker image", tag=tag, dockerfile=dockerfile)
        try:
            self._client.images.build(
                path=context, dockerfile=dockerfile, tag=tag, rm=True
            )
        except Exception as exc:
            raise DockerError(f"failed to build image {tag!r}") from exc

    def run_checks(
        self,
        files: dict[str, str],
        image: str,
        lint_cmd: str,
        test_cmd: str,
        install_cmd: Optional[str] = None,
    ) -> RunResult:
        """Materialize ``files`` in a container and run lint then tests.

        Args:
            files: ``{relative_path: content}`` to write into the workspace.
            image: Docker image to run (e.g. a pre-built ``mobile-agent-node``).
            lint_cmd: Shell command for linting (e.g. ``"npm run lint"``).
            test_cmd: Shell command for tests (e.g. ``"npm test"``).
            install_cmd: Optional dependency install run before lint/test
                (e.g. ``"npm install"``). Its failure short-circuits the run.

        Returns:
            A :class:`RunResult` with both command outcomes.

        Raises:
            DockerError: If the container cannot be created/started.
        """
        container = self._create_container(image)
        try:
            container.start()
            self._upload(container, files)

            if install_cmd:
                install = self._exec(container, install_cmd)
                if not install.passed:
                    # Deps failed — surface it as a lint failure; skip the rest.
                    logger.warning(
                        "Inner-loop install step failed",
                        exit_code=install.exit_code,
                    )
                    return RunResult(lint=install, tests=install)

            lint = self._exec(container, lint_cmd)
            tests = self._exec(container, test_cmd)
            logger.info(
                "Docker checks complete",
                image=image,
                lint_passed=lint.passed,
                tests_passed=tests.passed,
            )
            return RunResult(lint=lint, tests=tests)
        finally:
            self._cleanup(container)

    def run_command(
        self,
        files: dict[str, str],
        image: str,
        command: str,
        install_cmd: Optional[str] = None,
    ) -> CommandResult:
        """Materialize ``files`` and run a single command, returning its result.

        A general-purpose counterpart to :meth:`run_checks` for tools that are
        not lint/test shaped — e.g. a security scanner (``semgrep`` / ``gitleaks``)
        whose single combined output we capture and hand to the Security agent.
        Reuses the same container lifecycle, tar upload, timeout wrapping, and
        guaranteed cleanup.

        Args:
            files: ``{relative_path: content}`` to write into the workspace.
            image: Docker image to run the command in.
            command: Shell command to execute (timeout-wrapped like the checks).
            install_cmd: Optional setup command run first; its failure
                short-circuits and is returned as the result.

        Returns:
            The :class:`CommandResult` for ``command`` (or the failed install).

        Raises:
            DockerError: If the container cannot be created/started.
        """
        container = self._create_container(image)
        try:
            container.start()
            self._upload(container, files)

            if install_cmd:
                install = self._exec(container, install_cmd)
                if not install.passed:
                    logger.warning(
                        "run_command install step failed",
                        exit_code=install.exit_code,
                    )
                    return install

            result = self._exec(container, command)
            logger.info(
                "Docker command complete",
                image=image,
                exit_code=result.exit_code,
            )
            return result
        finally:
            self._cleanup(container)

    # --- internals -------------------------------------------------------- #

    def _create_container(self, image: str) -> Any:
        """Create (not start) an idle container we exec commands into."""
        try:
            return self._client.containers.create(
                image,
                command="sleep infinity",
                working_dir=self.workdir,
                tty=False,
                network_disabled=False,
            )
        except Exception as exc:
            raise DockerError(f"failed to create container from {image!r}") from exc

    def _upload(self, container: Any, files: dict[str, str]) -> None:
        """Stream ``files`` into the container workdir as an in-memory tar."""
        tar_bytes = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
            for path, content in files.items():
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=path.replace("\\", "/"))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        tar_bytes.seek(0)
        container.put_archive(self.workdir, tar_bytes.getvalue())

    def _exec(self, container: Any, command: str) -> CommandResult:
        """Run a shell command under a coreutils timeout; capture combined output."""
        wrapped = ["sh", "-c", f"timeout {self.timeout} {command}"]
        result = container.exec_run(wrapped, workdir=self.workdir, demux=False)
        raw = result.output
        output = raw.decode("utf-8", errors="replace") if raw else ""
        return CommandResult(exit_code=int(result.exit_code), output=output)

    @staticmethod
    def _cleanup(container: Any) -> None:
        """Force-remove the container, logging (not raising) on failure."""
        try:
            container.remove(force=True)
        except Exception as exc:
            logger.warning("Failed to remove container", error=str(exc))
