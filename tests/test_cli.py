"""Unit tests for the minimal CLI runner (`python -m src`).

The live `run()` needs a real model + Docker, so it is not exercised here;
instead we test the importable, side-effect-free pieces: argument parsing and
the environment pre-flight report.
"""

from __future__ import annotations

import pytest

from src.__main__ import EnvReport, _parse_args, check_environment, main, run
from src.integrations.docker_runner import DockerError

# --------------------------------------------------------------------------- #
# argument parsing
# --------------------------------------------------------------------------- #


def test_parse_args_prompt_and_platform() -> None:
    ns = _parse_args(["--prompt", "Build a todo app", "--platform", "flutter"])
    assert ns.prompt == "Build a todo app"
    assert ns.platform == "flutter"


def test_parse_args_platform_defaults_none() -> None:
    ns = _parse_args(["-p", "an app"])
    assert ns.platform is None


def test_parse_args_rejects_unknown_platform() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["-p", "x", "--platform", "windows-phone"])


def test_parse_args_requires_prompt() -> None:
    with pytest.raises(SystemExit):
        _parse_args([])


# --------------------------------------------------------------------------- #
# environment pre-flight
# --------------------------------------------------------------------------- #


def test_env_report_blocks_without_key() -> None:
    report = EnvReport(has_llm_key=False, docker_up=True)
    assert report.blocking_error() is not None


def test_env_report_warns_when_docker_down() -> None:
    report = EnvReport(has_llm_key=True, docker_up=False)
    assert report.blocking_error() is None
    assert any("Docker" in w for w in report.warnings())


def test_env_report_clean_when_ready() -> None:
    report = EnvReport(has_llm_key=True, docker_up=True)
    assert report.blocking_error() is None
    assert report.warnings() == []


def test_check_environment_detects_docker_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.__main__.DockerRunner",
        lambda *a, **k: (_ for _ in ()).throw(DockerError("down")),
    )
    monkeypatch.setattr("src.__main__.settings.OPENAI_API_KEY", "sk-test")
    report = check_environment()
    assert report.has_llm_key is True
    assert report.docker_up is False


# --------------------------------------------------------------------------- #
# main() guard: exits non-zero (without running the pipeline) when no key
# --------------------------------------------------------------------------- #


def test_run_drives_through_hitl_gates_to_completion() -> None:
    """run() auto-approves the HITL gates (CLI demo) and completes the pipeline.

    Uses the autouse offline agent stubs (conftest.py); the deploy gate would
    otherwise pause the graph, so this verifies run()'s checkpointer wiring and
    interrupt-resume loop.
    """
    response = run("Build a todo app")
    assert response.status == "completed"


# --------------------------------------------------------------------------- #
# main() guard: exits non-zero (without running the pipeline) when no key
# --------------------------------------------------------------------------- #


def test_main_exits_when_no_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.__main__.check_environment",
        lambda: EnvReport(has_llm_key=False, docker_up=True),
    )
    # run() must NOT be called when the key check fails.
    monkeypatch.setattr(
        "src.__main__.run",
        lambda *a, **k: pytest.fail("run() should not be called without a key"),
    )
    assert main(["--prompt", "an app"]) == 1
