"""Unit tests for the LiteLLM ↔ LangChain BaseChatModel bridge (mock client).

These verify the adapter contract end-to-end without any live LLM: message
conversion, plain-text responses, tool-call parsing (valid + malformed),
``bind_tools`` formatting, and that every call routes through the shared
``LiteLLMClient`` (so fallback/cost tracking is preserved).
"""

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from src.integrations.litellm_chat_model import LiteLLMChatModel
from src.integrations.litellm_client import LiteLLMClient


def _response(
    content: Optional[str] = None,
    tool_calls: Optional[list[SimpleNamespace]] = None,
    usage: Optional[SimpleNamespace] = None,
    model: str = "claude-3-5-sonnet-20241022",
) -> SimpleNamespace:
    """Build an OpenAI/LiteLLM-shaped response object."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=usage,
        model=model,
    )


def _tool_call(
    name: str, arguments: str, call_id: str = "call_1"
) -> SimpleNamespace:
    """Build an OpenAI-shaped tool call entry."""
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def _mock_client(response: Any) -> MagicMock:
    """A LiteLLMClient-shaped mock (``spec`` makes pydantic's isinstance pass)."""
    client = MagicMock(spec=LiteLLMClient)
    client.completion.return_value = response
    return client


def _model_with(response: Any) -> tuple[LiteLLMChatModel, MagicMock]:
    """Construct a bridge wired to a mock client returning ``response``."""
    client = _mock_client(response)
    model = LiteLLMChatModel(client=client, model_route="coder-model")
    return model, client


# --------------------------------------------------------------------------- #
# basic generation
# --------------------------------------------------------------------------- #


def test_plain_text_response() -> None:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    model, client = _model_with(_response(content="hello world", usage=usage))

    result = model.invoke([HumanMessage(content="hi")])

    assert isinstance(result, AIMessage)
    assert result.content == "hello world"
    assert result.tool_calls == []
    assert result.usage_metadata is not None
    assert result.usage_metadata["input_tokens"] == 10
    assert result.usage_metadata["output_tokens"] == 5
    assert result.usage_metadata["total_tokens"] == 15


def test_routes_through_client_with_model_route() -> None:
    model, client = _model_with(_response(content="x"))
    model.invoke([SystemMessage(content="sys"), HumanMessage(content="u")])

    client.completion.assert_called_once()
    _, kwargs = client.completion.call_args
    assert kwargs["model"] == "coder-model"
    # System + human converted to OpenAI dict messages.
    roles = [m["role"] for m in kwargs["messages"]]
    assert roles == ["system", "user"]


def test_temperature_and_stop_forwarded() -> None:
    client = _mock_client(_response(content="x"))
    model = LiteLLMChatModel(
        client=client, model_route="coder-model", temperature=0.2
    )
    model.invoke([HumanMessage(content="u")], stop=["STOP"])

    _, kwargs = client.completion.call_args
    assert kwargs["temperature"] == 0.2
    assert kwargs["stop"] == ["STOP"]


# --------------------------------------------------------------------------- #
# tool calls
# --------------------------------------------------------------------------- #


def test_valid_tool_call_parsed() -> None:
    tc = _tool_call("write_file", '{"path": "a.py", "content": "x"}')
    model, _ = _model_with(_response(content=None, tool_calls=[tc]))

    result = model.invoke([HumanMessage(content="write a file")])

    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call["name"] == "write_file"
    assert call["args"] == {"path": "a.py", "content": "x"}
    assert call["id"] == "call_1"
    assert result.invalid_tool_calls == []


def test_malformed_tool_args_become_invalid_tool_call() -> None:
    tc = _tool_call("write_file", "{not valid json")
    model, _ = _model_with(_response(content=None, tool_calls=[tc]))

    result = model.invoke([HumanMessage(content="write a file")])

    assert result.tool_calls == []
    assert len(result.invalid_tool_calls) == 1
    assert result.invalid_tool_calls[0]["name"] == "write_file"


# --------------------------------------------------------------------------- #
# bind_tools
# --------------------------------------------------------------------------- #


def test_bind_tools_formats_and_forwards() -> None:
    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file."""
        return "ok"

    model, client = _model_with(_response(content="done"))
    bound = model.bind_tools([write_file])
    bound.invoke([HumanMessage(content="go")])

    _, kwargs = client.completion.call_args
    assert "tools" in kwargs
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "write_file"


def test_bind_tools_tool_choice_forwarded() -> None:
    @tool
    def noop() -> str:
        """No-op."""
        return "ok"

    model, client = _model_with(_response(content="done"))
    bound = model.bind_tools([noop], tool_choice="auto")
    bound.invoke([HumanMessage(content="go")])

    _, kwargs = client.completion.call_args
    assert kwargs["tool_choice"] == "auto"


def test_llm_type() -> None:
    model, _ = _model_with(_response(content="x"))
    assert model._llm_type == "litellm-router"
