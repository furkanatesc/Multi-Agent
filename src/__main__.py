"""Minimal CLI runner for the multi-agent pipeline.

Wraps :func:`build_graph` so the pipeline can be invoked live with a prompt::

    python -m src --prompt "Build a todo list app" --platform react-native

This is a **developer / demo harness**, not the production API (Sprint 7). The
Reviewer, Deployer, and HITL gate are still stubs (Sprint 6/7), so a run
produces an ADR + source + generated tests but auto-PASSes review and
fake-deploys. It requires:

* a live LLM key in ``.env`` (Gemini / Anthropic / OpenAI), and
* a running **Docker daemon** — the inner self-fix loop hard-requires it to lint
  and test the generated code. Security/coverage tools degrade gracefully, but
  ``inner_loop_check`` will error without Docker.

The pieces here (``check_environment`` / ``run``) are kept small and importable
so they can be unit-tested without a live model.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional, Sequence, get_args

from src.core.config import settings
from src.core.logging import logger
from src.integrations.docker_runner import DockerError, DockerRunner
from src.orchestrator.graph import build_graph
from src.orchestrator.state import (
    AgentResponse,
    Platform,
    UserRequest,
    build_response,
    create_initial_state,
)


@dataclass(frozen=True)
class EnvReport:
    """Pre-flight readiness of the environment for a live run."""

    has_llm_key: bool
    docker_up: bool

    def blocking_error(self) -> Optional[str]:
        """Return a fatal-error message if the run cannot proceed, else None."""
        if not self.has_llm_key:
            return (
                "No LLM API key found in .env (need one of GEMINI/ANTHROPIC/"
                "OPENAI_API_KEY). A live run calls a real model."
            )
        return None

    def warnings(self) -> list[str]:
        """Return non-fatal warnings to print before running."""
        notes: list[str] = []
        if not self.docker_up:
            notes.append(
                "Docker daemon is not reachable — the inner self-fix loop "
                "(lint/test) will fail. Start Docker Desktop before running."
            )
        return notes


def check_environment() -> EnvReport:
    """Inspect API-key presence and Docker reachability (no side effects)."""
    has_key = any(
        (settings.GEMINI_API_KEY, settings.ANTHROPIC_API_KEY, settings.OPENAI_API_KEY)
    )
    try:
        DockerRunner()
        docker_up = True
    except DockerError:
        docker_up = False
    return EnvReport(has_llm_key=has_key, docker_up=docker_up)


def run(prompt: str, platform: Optional[Platform] = None) -> AgentResponse:
    """Invoke the full pipeline once and return the boundary response.

    Args:
        prompt: The natural-language app idea.
        platform: Optional target platform hint.

    Returns:
        The validated :class:`AgentResponse` snapshot of the final state.
    """
    graph = build_graph()
    initial = create_initial_state(UserRequest(prompt=prompt, platform=platform))
    logger.info("Pipeline run starting", platform=platform)
    final = graph.invoke(initial)
    return build_response(final)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments for the runner."""
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="Run the multi-agent mobile-app pipeline once on a prompt.",
    )
    parser.add_argument(
        "--prompt", "-p", required=True, help="Natural-language app idea/spec."
    )
    parser.add_argument(
        "--platform",
        choices=list(get_args(Platform)),
        default=None,
        help="Optional target platform hint.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    env = check_environment()
    error = env.blocking_error()
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for note in env.warnings():
        print(f"WARNING: {note}", file=sys.stderr)

    response = run(args.prompt, args.platform)

    print("\n=== Pipeline result ===")
    print(f"status        : {response.status}")
    print(f"platform      : {response.architecture_spec and response.architecture_spec.get('tech_stack', {}).get('platform')}")
    print(f"security score: {response.security_score}")
    print(f"review        : {response.review_decision}")
    print(f"files         : {len(response.source_code)} generated")
    print(f"cost (USD)    : {response.total_cost_usd:.4f}")
    print(f"iterations    : {response.iteration_count}")
    if response.error:
        print(f"error         : {response.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
