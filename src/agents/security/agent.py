"""SecurityAgent: SAST + secret/dependency review producing a scored report.

Built directly on :class:`BaseAgent` (LiteLLM + structured output) per the
project's #2 decision — like the Architect, this is a single-shot structured
agent, not a tool-loop. The flow:

    gather evidence (dependency audit + semgrep/gitleaks if Docker is up)
      → ask the LLM for a ``SecurityScan`` (summary + findings)
      → compute ``SecurityReport`` (score + has_critical) deterministically
        from the findings via ``owasp_rules`` — the gate never trusts LLM math.

When Docker is unavailable the scanners are skipped and the agent still produces
an LLM-only review (degraded but functional).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.base import BaseAgent
from src.agents.security.owasp_rules import compute_score, has_critical
from src.agents.security.schemas import SecurityReport, SecurityScan
from src.agents.security.tools import (
    ToolResult,
    check_dependencies_tool,
    run_gitleaks_tool,
    run_semgrep_tool,
)
from src.core.config import settings
from src.core.logging import logger
from src.integrations.docker_runner import DockerError, DockerRunner
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState

# Cap how much source we inline into the prompt (defensive token budget).
_MAX_PROMPT_CHARS = 24_000


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    """Load (and cache) the Security system prompt from config/prompts/."""
    path = settings.BASE_DIR / "config" / "prompts" / "security_system.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _scan_schema_json() -> str:
    """Compact JSON schema of SecurityScan, embedded in the user prompt."""
    return json.dumps(SecurityScan.model_json_schema())


class SecurityAgent(BaseAgent):
    """Scans generated code against the OWASP Mobile Top 10 and scores it."""

    name = "security"
    model_route = "security-model"

    def __init__(
        self,
        client: Optional[LiteLLMClient] = None,
        system_prompt: Optional[str] = None,
        docker_runner: Optional[DockerRunner] = None,
    ) -> None:
        super().__init__(client)
        self._system_prompt = system_prompt or _load_system_prompt()
        # Explicitly injected runner (tests) bypasses lazy connection.
        self._docker_runner = docker_runner

    # --- public API (per sprint plan) ------------------------------------- #

    def scan_code(self, files: dict[str, str]) -> tuple[SecurityReport, float]:
        """Review ``files`` and return a scored :class:`SecurityReport` + cost."""
        evidence = self._gather_evidence(files)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Review these source files for security issues.\n\n"
                    f"=== SCANNER EVIDENCE ===\n{evidence}\n\n"
                    f"=== SOURCE FILES ===\n{self._render_files(files)}\n\n"
                    f"Return ONLY JSON matching this SecurityScan schema:\n"
                    f"{_scan_schema_json()}"
                ),
            },
        ]
        scan, cost = self.complete_structured(messages, SecurityScan)
        return self._build_report(scan), cost

    def audit_dependencies(self, files: dict[str, str]) -> ToolResult:
        """Run the Docker-free dependency manifest audit (OWASP M2)."""
        return check_dependencies_tool(files)

    def detect_secrets(self, files: dict[str, str]) -> ToolResult:
        """Run gitleaks secret detection (OWASP M1); unavailable without Docker."""
        runner = self._runner()
        if runner is None:
            return ToolResult(name="gitleaks", available=False, output="")
        return run_gitleaks_tool(runner, files)

    # --- graph node entry point ------------------------------------------- #

    def run(self, state: AgentState) -> dict[str, Any]:
        """Scan the current source and return a partial state update.

        Writes ``security_score`` and ``security_critical`` so the downstream
        ``security_gate`` edge can route (proceed / fix / block_hitl).
        """
        files = state.get("source_code") or {}
        report, cost = self.scan_code(files)

        logger.info(
            "Security scan complete",
            score=report.score,
            has_critical=report.has_critical,
            findings=len(report.findings),
        )
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"[security] score={report.score}/100, "
                        f"{len(report.findings)} finding(s), "
                        f"critical={report.has_critical}"
                    ),
                    name=self.name,
                )
            ],
            "security_score": report.score,
            "security_critical": report.has_critical,
            "total_cost_usd": cost,
            "iteration_count": 1,
            "status": "security_scan",
        }

    # --- internals -------------------------------------------------------- #

    @staticmethod
    def _build_report(scan: SecurityScan) -> SecurityReport:
        """Derive the gate-critical score/critical flag from the LLM findings."""
        severities = [f.severity for f in scan.findings]
        return SecurityReport(
            score=compute_score(severities),
            has_critical=has_critical(severities),
            summary=scan.summary,
            findings=scan.findings,
        )

    def _runner(self) -> Optional[DockerRunner]:
        """Return a DockerRunner, or ``None`` if the daemon is unavailable."""
        if self._docker_runner is not None:
            return self._docker_runner
        try:
            self._docker_runner = DockerRunner()
        except DockerError:
            logger.warning("Docker unavailable; security scanners skipped")
            return None
        return self._docker_runner

    def _gather_evidence(self, files: dict[str, str]) -> str:
        """Collect dependency-audit + (if Docker is up) semgrep/gitleaks output."""
        blocks = [check_dependencies_tool(files).as_prompt_block()]

        runner = self._runner()
        if runner is not None:
            blocks.append(run_semgrep_tool(runner, files).as_prompt_block())
            blocks.append(run_gitleaks_tool(runner, files).as_prompt_block())
        else:
            blocks.append("### semgrep: unavailable (skipped)")
            blocks.append("### gitleaks: unavailable (skipped)")

        return "\n\n".join(blocks)

    @staticmethod
    def _render_files(files: dict[str, str]) -> str:
        """Render the file map as labelled blocks, bounded by a char budget."""
        if not files:
            return "(no source files were generated)"
        out: list[str] = []
        used = 0
        for path, content in files.items():
            block = f"--- FILE: {path} ---\n{content}"
            if used + len(block) > _MAX_PROMPT_CHARS:
                out.append(f"--- (remaining files omitted for length) ---")
                break
            out.append(block)
            used += len(block)
        return "\n\n".join(out)
