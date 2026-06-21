"""CoderAgent: turns an architecture spec into working source code.

Unlike the Architect (single-shot structured output), the Coder runs a genuine
**tool-loop**: it writes files, reads them back, and revises — via
``langgraph.prebuilt.create_react_agent`` over the
:class:`~src.integrations.litellm_chat_model.LiteLLMChatModel` bridge, so Router
fallback and cost tracking (Sprint 1) stay intact (decision #4, Sprint 4).

Flow per pass:

1. build a fresh react-agent bound to file tools over an in-memory
   :class:`~src.agents.coder.tools.Workspace`;
2. run the loop (the model writes/edits files through the tools);
3. ask the model for a final **structured summary** (``GeneratedModule`` /
   ``SelfFixResult``) so the graph receives typed output, not free text.

Cost is read off the shared client before/after the whole pass (the
``BaseAgent.track_cost`` pattern), since both the loop and the summary call accrue
into the same :class:`LiteLLMClient`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from src.agents.base import BaseAgent
from src.agents.coder.schemas import GeneratedModule, SelfFixResult
from src.agents.coder.tools import Workspace, make_file_tools
from src.core.config import settings
from src.core.logging import logger
from src.integrations.litellm_chat_model import LiteLLMChatModel
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState

# Cap tool-loop iterations so a misbehaving model can't run unbounded.
_RECURSION_LIMIT = 50


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    """Load (and cache) the Coder system prompt from config/prompts/."""
    path = settings.BASE_DIR / "config" / "prompts" / "coder_system.md"
    return path.read_text(encoding="utf-8")


class CoderAgent(BaseAgent):
    """Generates and self-fixes source code via a tool-using react-agent."""

    name = "coder"
    model_route = "coder-model"

    def __init__(
        self,
        client: Optional[LiteLLMClient] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        super().__init__(client)
        self._system_prompt = system_prompt or _load_system_prompt()
        self._temperature = temperature

    # --- public API (per sprint plan) ------------------------------------- #

    def generate_module(
        self,
        architecture_spec: dict[str, Any],
        prompt: str,
        workspace: Optional[Workspace] = None,
    ) -> tuple[GeneratedModule, float]:
        """Generate source code for the given architecture into ``workspace``.

        Runs the tool-loop then returns a validated :class:`GeneratedModule` and
        the incremental LLM cost. The (possibly pre-seeded) ``workspace`` is
        mutated in place; read ``workspace.files`` afterwards for the file map.
        """
        ws = workspace if workspace is not None else Workspace()
        before = self.current_cost()

        instruction = self._generation_instruction(architecture_spec, prompt)
        self._run_tool_loop(ws, instruction)
        summary = self._summarize(ws, GeneratedModule)

        cost = self.track_cost(before)
        logger.info(
            "Coder generated module",
            files=len(ws.files),
            cost_usd=round(cost, 6),
        )
        return summary, cost

    def self_fix(
        self,
        files: dict[str, str],
        lint_output: str = "",
        test_output: str = "",
    ) -> tuple[SelfFixResult, float, Workspace]:
        """Attempt to fix failing lint/test output over an existing file set.

        Returns the validated :class:`SelfFixResult`, incremental cost, and the
        mutated :class:`Workspace` (its ``files`` are the post-fix sources).
        """
        ws = Workspace(files)
        before = self.current_cost()

        instruction = self._fix_instruction(lint_output, test_output)
        self._run_tool_loop(ws, instruction)
        result = self._summarize(ws, SelfFixResult)

        cost = self.track_cost(before)
        logger.info(
            "Coder self-fix pass complete",
            resolved=result.resolved,
            files=len(ws.files),
            cost_usd=round(cost, 6),
        )
        return result, cost, ws

    # --- graph node entry point ------------------------------------------- #

    def run(self, state: AgentState) -> dict[str, Any]:
        """Generate code for the current architecture and update graph state.

        Carries forward any existing ``source_code`` (so outer-loop revisions
        build on prior files), resets the inner-loop lint/test flags, and routes
        to the inner-loop check.
        """
        spec = state.get("architecture_spec") or {}
        prompt = state.get("prompt", "") or ""
        workspace = Workspace(state.get("source_code"))

        module, cost = self.generate_module(spec, prompt, workspace)

        return {
            "messages": [
                AIMessage(
                    content=f"[coder] {module.summary}",
                    name=self.name,
                )
            ],
            "source_code": dict(workspace.files),
            "lint_passed": None,
            "tests_passed": None,
            "total_cost_usd": cost,
            "iteration_count": 1,
            "status": "inner_loop",
            "next_agent": "inner_loop_check",
        }

    # --- internals -------------------------------------------------------- #

    def _chat_model(self) -> LiteLLMChatModel:
        """Build the LangChain chat model that routes through our client."""
        return LiteLLMChatModel(
            client=self.client,
            model_route=self.model_route,
            temperature=self._temperature,
        )

    def _run_tool_loop(self, workspace: Workspace, instruction: str) -> None:
        """Run one react-agent tool-loop, mutating ``workspace`` via its tools."""
        agent = create_react_agent(
            self._chat_model(),
            make_file_tools(workspace),
            prompt=self._system_prompt,
        )
        agent.invoke(
            {"messages": [HumanMessage(content=instruction)]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )

    def _summarize(
        self, workspace: Workspace, schema: type[GeneratedModule] | type[SelfFixResult]
    ) -> Any:
        """Ask the model for a structured summary of the finished workspace."""
        paths = workspace.list_paths()
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    "You have finished working. Files currently in the workspace:\n"
                    f"{json.dumps(paths)}\n\n"
                    "Return ONLY a JSON object matching this schema:\n"
                    f"{json.dumps(schema.model_json_schema())}"
                ),
            },
        ]
        result, _cost = self.complete_structured(messages, schema)
        return result

    def _generation_instruction(
        self, architecture_spec: dict[str, Any], prompt: str
    ) -> str:
        """Build the user instruction that kicks off code generation."""
        return (
            f"User request:\n{prompt}\n\n"
            f"Architecture specification (ADR) to implement:\n"
            f"{json.dumps(architecture_spec, indent=2)}\n\n"
            "Generate the project source code now using your file tools. "
            "Write complete, runnable files following the specified folder "
            "structure. When finished, stop calling tools."
        )

    def _fix_instruction(self, lint_output: str, test_output: str) -> str:
        """Build the user instruction for a self-fix pass."""
        return (
            "The generated code failed its checks. Diagnose and fix the issues "
            "using your file tools (read the offending files, then rewrite them). "
            "Change only what is needed.\n\n"
            f"Lint output:\n{lint_output or '(none)'}\n\n"
            f"Test output:\n{test_output or '(none)'}"
        )
