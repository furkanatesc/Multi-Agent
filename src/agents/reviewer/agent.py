"""ReviewerAgent: senior-engineer code review with a deterministic verdict.

Built directly on :class:`BaseAgent` (LiteLLM + structured output) per the
project's #2 decision — like the Architect and Security agents, this is a
single-shot structured agent, not a tool-loop. The flow:

    (optionally) analyze CI logs → CILogAnalysis
      → ask the LLM for a ``CodeReview`` (summary + severity-tagged comments)
      → compute ``ReviewReport`` (PASS/FAIL) deterministically from the comment
        severities via ``review_rules`` — the gate never trusts LLM math.

The graph node entry point (:meth:`run`) is pure: it reviews the in-state source
and writes ``review_decision`` / ``review_notes`` / ``outer_loop_count`` for the
``review_decision`` edge. GitHub I/O (pushing code, opening a PR, posting the
review, auto-merge) is a *separate*, explicitly-invoked capability
(:meth:`create_pr_review`) so the orchestration graph stays offline-testable —
exactly as the Security agent's ``run`` does not require Docker.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.base import BaseAgent
from src.agents.reviewer.review_rules import decide_verdict, is_blocking
from src.agents.reviewer.schemas import (
    CILogAnalysis,
    CodeReview,
    ReviewComment,
    ReviewReport,
)
from src.core.config import settings
from src.core.logging import logger
from src.integrations.github_client import GitHubClient
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState

# Cap how much source we inline into the prompt (defensive token budget).
_MAX_PROMPT_CHARS = 24_000


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    """Load (and cache) the Reviewer system prompt from config/prompts/."""
    path = settings.BASE_DIR / "config" / "prompts" / "reviewer_system.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _review_schema_json() -> str:
    """Compact JSON schema of CodeReview, embedded in the user prompt."""
    return json.dumps(CodeReview.model_json_schema())


@lru_cache(maxsize=1)
def _ci_schema_json() -> str:
    """Compact JSON schema of CILogAnalysis, embedded in the user prompt."""
    return json.dumps(CILogAnalysis.model_json_schema())


class ReviewerAgent(BaseAgent):
    """Reviews generated code for SOLID/Clean-Code quality and decides PASS/FAIL."""

    name = "reviewer"
    model_route = "reviewer-model"

    def __init__(
        self,
        client: Optional[LiteLLMClient] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        super().__init__(client)
        self._system_prompt = system_prompt or _load_system_prompt()

    # --- public API (per sprint plan) ------------------------------------- #

    def review_code(
        self,
        files: dict[str, str],
        ci_analysis: Optional[CILogAnalysis] = None,
    ) -> tuple[ReviewReport, float]:
        """Review ``files`` and return a :class:`ReviewReport` (verdict) + cost.

        Args:
            files: ``{path: content}`` map of the change under review.
            ci_analysis: Optional CI-log analysis to fold in as evidence — a
                failing build is strong signal for a blocking comment.
        """
        ci_block = self._render_ci_evidence(ci_analysis)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Review this change for correctness and design quality.\n\n"
                    f"{ci_block}"
                    f"=== SOURCE FILES ===\n{self._render_files(files)}\n\n"
                    f"Return ONLY JSON matching this CodeReview schema:\n"
                    f"{_review_schema_json()}"
                ),
            },
        ]
        review, cost = self.complete_structured(messages, CodeReview)
        return self._build_report(review), cost

    def analyze_ci_logs(self, logs: str) -> tuple[CILogAnalysis, float]:
        """Summarize raw CI logs into a structured root-cause + fix.

        Skips the LLM entirely (zero cost) when there is nothing to analyze, so a
        clean/green run does not burn a request.
        """
        if not logs.strip():
            return CILogAnalysis(passed=True, root_cause="n/a"), 0.0
        messages = [
            {
                "role": "system",
                "content": (
                    "You analyze continuous-integration logs for a code-review "
                    "agent. Identify whether the run passed, the first failing "
                    "step, the root cause, and a concrete fix. Respond with JSON "
                    "only, matching the provided schema."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"=== CI LOGS ===\n{logs[:_MAX_PROMPT_CHARS]}\n\n"
                    f"Return ONLY JSON matching this CILogAnalysis schema:\n"
                    f"{_ci_schema_json()}"
                ),
            },
        ]
        return self.complete_structured(messages, CILogAnalysis)

    def create_pr_review(
        self,
        report: ReviewReport,
        github: GitHubClient,
        repo: str,
        pr_number: int,
        *,
        auto_merge: bool = False,
    ) -> int:
        """Post ``report`` as a GitHub PR review; optionally auto-merge on PASS.

        Maps the verdict to a review event (PASS→APPROVE, FAIL→REQUEST_CHANGES)
        and line-anchored comments to inline review comments. Returns the created
        review's id.
        """
        event = "APPROVE" if report.verdict == "PASS" else "REQUEST_CHANGES"
        inline = self._to_inline_comments(report.comments)
        review_id = github.submit_review(
            repo=repo,
            pr_number=pr_number,
            event=event,
            body=report.summary,
            comments=inline,
        )
        if report.verdict == "PASS" and auto_merge:
            github.auto_merge(repo, pr_number)
        return review_id

    # --- graph node entry point ------------------------------------------- #

    def run(self, state: AgentState) -> dict[str, Any]:
        """Review the current source and return a partial state update.

        Writes ``review_decision`` (PASS/FAIL) + ``review_notes`` and increments
        ``outer_loop_count`` so the downstream ``review_decision`` edge can route
        (approve→deploy, reject→coder, escalate→END once the outer cap is hit).
        """
        files = state.get("source_code") or {}
        report, cost = self.review_code(files)
        outer = int(state.get("outer_loop_count", 0)) + 1

        logger.info(
            "Code review complete",
            verdict=report.verdict,
            comments=len(report.comments),
            outer_loop=outer,
        )
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"[reviewer] {report.verdict}: {len(report.comments)} "
                        f"comment(s), {len(report.blocking_comments)} blocking "
                        f"(outer loop {outer})"
                    ),
                    name=self.name,
                )
            ],
            "review_decision": report.verdict,
            "review_notes": report.summary,
            "outer_loop_count": outer,
            "total_cost_usd": cost,
            "iteration_count": 1,
            "status": "review",
        }

    # --- internals -------------------------------------------------------- #

    @staticmethod
    def _build_report(review: CodeReview) -> ReviewReport:
        """Derive the gate-critical PASS/FAIL verdict from the LLM comments."""
        verdict = decide_verdict([c.severity for c in review.comments])
        return ReviewReport(
            verdict=verdict, summary=review.summary, comments=review.comments
        )

    @staticmethod
    def _to_inline_comments(comments: list[ReviewComment]) -> list[dict[str, Any]]:
        """Map line-anchored review comments to PyGithub inline-comment dicts.

        Only comments with a concrete ``line`` become inline comments (GitHub
        requires a position); the rest are conveyed via the review body summary.
        """
        inline: list[dict[str, Any]] = []
        for c in comments:
            if c.line is None:
                continue
            marker = "⛔" if is_blocking(c.severity) else "💬"
            body = f"{marker} **[{c.severity}/{c.category}]** {c.message}"
            if c.suggestion:
                body += f"\n\n```suggestion\n{c.suggestion}\n```"
            inline.append({"path": c.file, "line": c.line, "body": body})
        return inline

    @staticmethod
    def _render_ci_evidence(ci: Optional[CILogAnalysis]) -> str:
        """Render optional CI-log analysis as a labelled prompt block."""
        if ci is None:
            return ""
        status = "PASSED" if ci.passed else "FAILED"
        lines = [
            "=== CI ANALYSIS ===",
            f"status: {status}",
            f"root_cause: {ci.root_cause}",
        ]
        if ci.failing_step:
            lines.append(f"failing_step: {ci.failing_step}")
        if ci.suggested_fix:
            lines.append(f"suggested_fix: {ci.suggested_fix}")
        return "\n".join(lines) + "\n\n"

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
                out.append("--- (remaining files omitted for length) ---")
                break
            out.append(block)
            used += len(block)
        return "\n\n".join(out)
