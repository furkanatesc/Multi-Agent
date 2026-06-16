"""ArchitectAgent: produces a structured ADR document from a user request.

Built directly on :class:`BaseAgent` (LiteLLM + structured output) per the
project's #2 LLM-access decision — see ``agents/base.py``. The agent enriches the
prompt with a cheap keyword pre-analysis, asks the LLM for JSON matching
``ADRDocument``, validates it, and backfills a default folder structure if the
model omitted one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.architect.schemas import ADRDocument, TechStack
from src.agents.architect.tools import analyze_requirements, default_folder_structure
from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.logging import logger
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    """Load (and cache) the Architect system prompt from config/prompts/."""
    path = settings.BASE_DIR / "config" / "prompts" / "architect_system.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _adr_schema_json() -> str:
    """Compact JSON schema of ADRDocument, embedded in the user prompt."""
    return json.dumps(ADRDocument.model_json_schema())


class ArchitectAgent(BaseAgent):
    """Generates Architecture Decision Records for mobile app requests."""

    name = "architect"
    model_route = "architect-model"

    def __init__(
        self,
        client: Optional[LiteLLMClient] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        super().__init__(client)
        self._system_prompt = system_prompt or _load_system_prompt()

    # --- public API (per sprint plan) ------------------------------------- #

    def analyze_requirements(self, prompt: str) -> dict[str, Any]:
        """Cheap heuristic pre-analysis of the request (domain/platform hints)."""
        return analyze_requirements(prompt)

    def select_tech_stack(
        self, prompt: str, platform_hint: Optional[str] = None
    ) -> tuple[TechStack, float]:
        """Ask the LLM for just the technology stack (focused sub-decision)."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Select ONLY the technology stack for this app.\n"
                    f"Request: {prompt}\n"
                    f"{self._hint_line(platform_hint, prompt)}\n"
                    f"Return JSON matching this schema:\n"
                    f"{json.dumps(TechStack.model_json_schema())}"
                ),
            },
        ]
        return self.complete_structured(messages, TechStack)

    def generate_adr(
        self, prompt: str, platform_hint: Optional[str] = None
    ) -> tuple[ADRDocument, float]:
        """Generate and validate the full ADR document for a request.

        Returns the validated :class:`ADRDocument` and the incremental LLM cost.
        Backfills a default folder structure when the model returns none.
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"User request:\n{prompt}\n\n"
                    f"{self._hint_line(platform_hint, prompt)}\n\n"
                    f"Return ONLY a JSON object matching this ADRDocument schema:\n"
                    f"{_adr_schema_json()}"
                ),
            },
        ]
        doc, cost = self.complete_structured(messages, ADRDocument)

        if not doc.folder_structure.entries:
            logger.info("Architect ADR missing folder structure; using default")
            doc.folder_structure = default_folder_structure(doc.tech_stack)

        return doc, cost

    # --- graph node entry point ------------------------------------------- #

    def run(self, state: AgentState) -> dict[str, Any]:
        """Generate the ADR and return a partial state update for the graph."""
        prompt = state.get("prompt", "") or ""
        platform_hint = state.get("platform")

        doc, cost = self.generate_adr(prompt, platform_hint)

        logger.info(
            "Architect produced ADR",
            project=doc.project_name,
            platform=doc.tech_stack.platform,
            pattern=doc.architecture_pattern,
        )
        return {
            "messages": [
                AIMessage(
                    content=f"[architect] ADR for '{doc.project_name}' "
                    f"({doc.tech_stack.platform}, {doc.architecture_pattern})",
                    name=self.name,
                )
            ],
            "architecture_spec": doc.model_dump(),
            "platform": doc.tech_stack.platform,
            "total_cost_usd": cost,
            "iteration_count": 1,
            "status": "coding",
            "next_agent": "coder",
        }

    # --- helpers ---------------------------------------------------------- #

    def _hint_line(self, platform_hint: Optional[str], prompt: str) -> str:
        """Build an advisory hint line from an explicit hint + heuristic analysis."""
        analysis = self.analyze_requirements(prompt)
        suggested = platform_hint or analysis.get("suggested_platform")
        if suggested:
            return f"Advisory platform hint (not binding): {suggested}."
        return "No platform hint; choose the best fit and justify it."
