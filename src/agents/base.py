"""Abstract base class shared by all worker agents.

Per the project's LLM-access decision (Sprint 3), agents are built **directly on
:class:`LiteLLMClient`** rather than on ``create_react_agent``. This preserves the
Sprint 1 investment — Router fallback chains and token/cost tracking — which a
raw LangChain chat model would bypass. Agents whose job is structured single-shot
generation (e.g. the Architect) use :meth:`BaseAgent.complete_structured`. The
``create_react_agent`` tool-loop is deferred to agents that genuinely need it
(Coder, Sprint 4), where a LangChain ``BaseChatModel`` wrapper will be added.

Contract for subclasses:
* set the class attributes :attr:`name` and :attr:`model_route`;
* implement :meth:`run`, returning a *partial* ``AgentState`` dict (the graph's
  reducers merge it — see ``orchestrator/state.py``). The returned dict should
  add the run's incremental cost to ``total_cost_usd``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from src.core.logging import logger
from src.integrations.litellm_client import LiteLLMClient
from src.orchestrator.state import AgentState

TModel = TypeVar("TModel", bound=BaseModel)


class AgentError(Exception):
    """Base class for agent-level failures."""


class AgentOutputError(AgentError):
    """Raised when an LLM response cannot be parsed/validated into the schema."""


class BaseAgent(ABC):
    """Common interface and LLM plumbing for all worker agents."""

    #: Stable agent identifier (also used as the message author / log key).
    name: ClassVar[str]
    #: LiteLLM router model alias for this agent (see config/litellm_config.yaml).
    model_route: ClassVar[str]

    def __init__(self, client: Optional[LiteLLMClient] = None) -> None:
        """Bind the agent to a LiteLLM client (a shared one may be injected)."""
        self.client = client or LiteLLMClient()

    # --- model / cost helpers --------------------------------------------- #

    def get_model(self) -> str:
        """Return the LiteLLM router alias this agent routes through."""
        return self.model_route

    def current_cost(self) -> float:
        """Return the client's cumulative spend (USD) so far."""
        return float(self.client.get_metrics()["total_cost_usd"])

    def track_cost(self, since: float) -> float:
        """Return spend incurred since a prior :meth:`current_cost` reading."""
        return self.current_cost() - since

    # --- LLM invocation --------------------------------------------------- #

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[TModel],
        **kwargs: Any,
    ) -> tuple[TModel, float]:
        """Request a JSON completion and validate it into ``schema``.

        Routes through the LiteLLM client (with fallback) using JSON-object
        response formatting — the lowest common denominator across Gemini /
        Claude / GPT, so the fallback chain stays intact. The system prompt is
        responsible for describing the exact JSON shape.

        Args:
            messages: Chat messages (system + user) for the completion.
            schema: Pydantic model the response must validate against.
            **kwargs: Extra params forwarded to the client (e.g. ``temperature``).

        Returns:
            A tuple of (validated model instance, incremental cost in USD).

        Raises:
            AgentOutputError: If the response is malformed, not valid JSON, or
                fails schema validation.
        """
        before = self.current_cost()
        kwargs.setdefault("response_format", {"type": "json_object"})

        response = self.client.completion(
            model=self.model_route, messages=messages, **kwargs
        )
        cost = self.track_cost(before)

        content = self._extract_content(response)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error(
                "Agent produced non-JSON output",
                agent=self.name,
                error=str(exc),
            )
            raise AgentOutputError(
                f"{self.name}: response was not valid JSON"
            ) from exc

        try:
            validated = schema.model_validate(data)
        except ValidationError as exc:
            logger.error(
                "Agent output failed schema validation",
                agent=self.name,
                schema=schema.__name__,
                error=str(exc),
            )
            raise AgentOutputError(
                f"{self.name}: output did not match {schema.__name__}"
            ) from exc

        logger.info(
            "Agent structured completion succeeded",
            agent=self.name,
            schema=schema.__name__,
            cost_usd=round(cost, 6),
        )
        return validated, cost

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Pull the assistant message text out of a LiteLLM/OpenAI-shaped response."""
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as exc:
            raise AgentOutputError("malformed LLM response (no message content)") from exc
        return content or ""

    # --- subclass contract ------------------------------------------------ #

    @abstractmethod
    def run(self, state: AgentState) -> dict[str, Any]:
        """Execute the agent and return a partial ``AgentState`` update."""
        raise NotImplementedError
