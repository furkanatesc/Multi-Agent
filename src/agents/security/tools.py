"""Evidence-gathering helpers for the Security agent.

The :class:`~src.agents.security.agent.SecurityAgent` is a single-shot
structured-output agent (project decision #2 — no tool-loop). These are *not*
LangChain tools; they are plain helpers the agent calls to collect scanner
evidence, which it then feeds into the LLM prompt as corroborating input.

* ``run_semgrep_tool`` / ``run_gitleaks_tool`` run the respective scanner inside
  the ``mobile-agent-security`` container via :class:`DockerRunner`. If Docker is
  unavailable they degrade gracefully (``available=False``) so the agent can
  still produce an LLM-only review.
* ``check_dependencies_tool`` is a deterministic, Docker-free heuristic over the
  dependency manifests (OWASP **M2**) — it flags unpinned/risky version specs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.core.logging import logger
from src.integrations.docker_runner import DockerError, DockerRunner

SECURITY_IMAGE = "mobile-agent-security"
SECURITY_DOCKERFILE = "docker/Dockerfile.security"

# Scanners write JSON to stdout; `|| true` keeps a findings exit-code from being
# treated as a tool failure (we read the report, not the exit status).
_SEMGREP_CMD = "semgrep scan --quiet --json . || true"
_GITLEAKS_CMD = (
    "gitleaks detect --no-git --source . "
    "--report-format json --report-path /dev/stdout || true"
)

# Manifest filename -> the version-spec patterns we consider risky (unpinned).
_RISKY_VERSION_TOKENS = ("*", "latest", "^", "~", "git+", "http://", "https://")


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one evidence-gathering helper."""

    name: str
    available: bool
    output: str

    def as_prompt_block(self) -> str:
        """Render this result as a labelled block for the LLM prompt."""
        if not self.available:
            return f"### {self.name}: unavailable (skipped)"
        body = self.output.strip() or "(no output / no findings)"
        return f"### {self.name}\n{body}"


def _run_scanner(
    runner: DockerRunner, files: dict[str, str], command: str, name: str
) -> ToolResult:
    """Run a scanner in the security image, degrading gracefully on Docker errors."""
    try:
        runner.ensure_image(SECURITY_IMAGE, SECURITY_DOCKERFILE)
        result = runner.run_command(files, image=SECURITY_IMAGE, command=command)
        return ToolResult(name=name, available=True, output=result.output)
    except DockerError as exc:
        logger.warning("Security scanner unavailable", scanner=name, error=str(exc))
        return ToolResult(name=name, available=False, output="")


def run_semgrep_tool(runner: DockerRunner, files: dict[str, str]) -> ToolResult:
    """Run semgrep SAST over the file set (OWASP code-pattern findings)."""
    return _run_scanner(runner, files, _SEMGREP_CMD, "semgrep")


def run_gitleaks_tool(runner: DockerRunner, files: dict[str, str]) -> ToolResult:
    """Run gitleaks secret detection over the file set (OWASP M1)."""
    return _run_scanner(runner, files, _GITLEAKS_CMD, "gitleaks")


def check_dependencies_tool(files: dict[str, str]) -> ToolResult:
    """Audit dependency manifests for unpinned/risky version specs (OWASP M2).

    Pure-Python and offline: parses ``package.json`` (npm) and scans
    ``pubspec.yaml`` (Dart) for version tokens that indicate floating or
    out-of-registry dependencies. Always ``available`` — needs no Docker.
    """
    notes: list[str] = []

    pkg = files.get("package.json")
    if pkg:
        notes.extend(_audit_package_json(pkg))

    pubspec = files.get("pubspec.yaml")
    if pubspec:
        notes.extend(_audit_pubspec(pubspec))

    if not (pkg or pubspec):
        output = "(no dependency manifest found)"
    elif not notes:
        output = "All declared dependencies use pinned versions."
    else:
        output = "\n".join(f"- {n}" for n in notes)

    return ToolResult(name="dependency-audit", available=True, output=output)


def _audit_package_json(content: str) -> list[str]:
    """Flag npm dependencies whose version spec is unpinned/risky."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return ["package.json is not valid JSON (cannot audit dependencies)."]

    notes: list[str] = []
    for section in ("dependencies", "devDependencies"):
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for name, spec in deps.items():
            if isinstance(spec, str) and _is_risky_spec(spec):
                notes.append(f"{section}: '{name}' uses unpinned/risky spec '{spec}'.")
    return notes


def _audit_pubspec(content: str) -> list[str]:
    """Flag Dart dependencies that float (``any``) or use git/path sources."""
    notes: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if (": any" in line) or line.endswith(": any"):
            notes.append(f"pubspec: floating dependency version — '{line}'.")
        if "git:" in line or "path:" in line:
            notes.append(f"pubspec: non-registry dependency source — '{line}'.")
    return notes


def _is_risky_spec(spec: str) -> bool:
    """True when a version spec is unpinned or points outside the registry."""
    stripped = spec.strip()
    if stripped in ("*", "latest", ""):
        return True
    return any(stripped.startswith(tok) for tok in _RISKY_VERSION_TOKENS)
