"""LiteLLM ↔ LangChain ``BaseChatModel`` bridge (Sprint 4, decision #3).

Most agents are single-shot structured generators and run directly on
:class:`~src.integrations.litellm_client.LiteLLMClient` (decision #2). The Coder,
however, needs a genuine *tool-loop* — read a file, write a file, observe the
result, decide the next call — which is exactly what ``langgraph.prebuilt``'s
``create_react_agent`` provides. That prebuilt requires a LangChain
``BaseChatModel`` that supports ``.bind_tools()``.

This module is the thin adapter that lets the Coder use ``create_react_agent``
**without abandoning the Sprint 1 investment**: every model call still flows
through :class:`LiteLLMClient`, so Router fallback chains and token/cost tracking
remain intact. Concretely the bridge:

* converts LangChain messages → OpenAI-shaped dicts (incl. tool results),
* forwards the call to ``LiteLLMClient.completion`` (fallback + cost tracked),
* converts the OpenAI-shaped response (incl. ``tool_calls``) → an ``AIMessage``,
* exposes ``bind_tools`` so the react-agent can register its file tools.

Because cost accrues inside the shared :class:`LiteLLMClient`, the Coder measures
a tool-loop's spend by reading ``client.get_metrics()`` before and after the run
(the same ``BaseAgent.track_cost`` pattern the Architect uses).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Optional, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    InvalidToolCall,
    ToolCall,
    convert_to_openai_messages,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

from src.core.logging import logger
from src.integrations.litellm_client import LiteLLMClient


class LiteLLMChatModel(BaseChatModel):
    """A LangChain chat model that delegates to the LiteLLM Router client.

    Use this only where a tool-loop is required (the Coder). Single-shot
    structured agents should keep using ``BaseAgent.complete_structured``.

    Attributes:
        client: The shared LiteLLM client (carries fallback + cost state). Reuse
            one instance per run so cost accounting stays consistent.
        model_route: The LiteLLM router alias to call (e.g. ``"coder-model"``).
        temperature: Optional sampling temperature applied to every call.
    """

    client: LiteLLMClient
    model_route: str
    temperature: Optional[float] = None

    # LiteLLMClient is a plain (non-pydantic) object, so it must be allowed as a
    # field type. Merged with BaseChatModel's own config by pydantic v2.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        """LangChain model-type tag (used in tracing/serialization)."""
        return "litellm-router"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Parameters that identify this model instance (for caching/tracing)."""
        return {"model_route": self.model_route, "temperature": self.temperature}

    # --- core generation -------------------------------------------------- #

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Run one model turn through the LiteLLM client and adapt the result.

        ``kwargs`` carries anything bound via :meth:`bind_tools` (notably
        ``tools`` and ``tool_choice``) plus per-call overrides; these are passed
        straight through to ``LiteLLMClient.completion``.
        """
        oai_messages = convert_to_openai_messages(messages)

        call_kwargs: dict[str, Any] = {}
        if self.temperature is not None:
            call_kwargs["temperature"] = self.temperature
        if stop:
            call_kwargs["stop"] = stop
        call_kwargs.update(kwargs)

        response = self.client.completion(
            model=self.model_route,
            messages=oai_messages,
            **call_kwargs,
        )

        message = self._to_ai_message(response)
        return ChatResult(generations=[ChatGeneration(message=message)])

    # --- tool binding ----------------------------------------------------- #

    def bind_tools(
        self,
        tools: Sequence[Union[dict[str, Any], type, Callable[..., Any], BaseTool]],
        *,
        tool_choice: Optional[Union[str, dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Bind tools so ``create_react_agent`` can request tool calls.

        Tools are normalized to the OpenAI function-tool schema and attached as a
        default ``tools`` kwarg; the bound runnable forwards them into every
        :meth:`_generate` call.
        """
        formatted = [convert_to_openai_tool(tool) for tool in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self.bind(tools=formatted, **kwargs)

    # --- response adaptation ---------------------------------------------- #

    @staticmethod
    def _to_ai_message(response: Any) -> AIMessage:
        """Convert an OpenAI/LiteLLM response into a LangChain ``AIMessage``.

        Parses any ``tool_calls`` into LangChain's structured form so the
        react-agent can dispatch them; malformed tool arguments are preserved as
        ``invalid_tool_calls`` rather than raising (the agent then self-corrects).
        """
        try:
            message = response.choices[0].message
        except (AttributeError, IndexError, KeyError) as exc:
            raise ValueError("malformed LLM response (no message content)") from exc

        content: str = getattr(message, "content", None) or ""
        raw_tool_calls = getattr(message, "tool_calls", None) or []

        tool_calls: list[ToolCall] = []
        invalid_tool_calls: list[InvalidToolCall] = []
        for raw in raw_tool_calls:
            fn = raw.function
            raw_args = fn.arguments or "{}"
            try:
                args = json.loads(raw_args)
                tool_calls.append(
                    ToolCall(name=fn.name, args=args, id=raw.id, type="tool_call")
                )
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Tool call had non-JSON arguments",
                    tool=getattr(fn, "name", None),
                    error=str(exc),
                )
                invalid_tool_calls.append(
                    InvalidToolCall(
                        name=fn.name,
                        args=raw_args,
                        id=raw.id,
                        error=str(exc),
                        type="invalid_tool_call",
                    )
                )

        usage_metadata = LiteLLMChatModel._usage_from(response)

        return AIMessage(
            content=content,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid_tool_calls,
            usage_metadata=usage_metadata,
            response_metadata={"model_name": getattr(response, "model", None)},
        )

    @staticmethod
    def _usage_from(response: Any) -> Optional[UsageMetadata]:
        """Extract token usage from the response, if present."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
