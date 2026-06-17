"""Pydantic output schemas for the Coder agent.

The Coder runs a tool-loop (``create_react_agent`` over the
:class:`~src.integrations.litellm_chat_model.LiteLLMChatModel` bridge) and writes
files into an in-memory workspace via its tools. After the loop ends, the agent
asks the model for a final structured summary validated against
:class:`GeneratedModule` so the orchestrator gets a typed result rather than free
text. ``SelfFixResult`` is the same idea for a self-fix pass.

Mirrors ``agents/architect/schemas.py``: a shared ``_Schema`` base that ignores
unexpected LLM fields rather than hard-failing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    """Base config: ignore unexpected LLM fields rather than hard-failing."""

    model_config = ConfigDict(extra="ignore")


class GeneratedModule(_Schema):
    """Structured summary of a Coder generation pass.

    The actual file contents live in the workspace (written via tools); this
    schema is the model's own report of what it produced, surfaced to the graph.
    """

    summary: str = Field(
        description="One-paragraph summary of what was generated/changed."
    )
    files_written: list[str] = Field(
        default_factory=list,
        description="Relative paths the agent created or modified this pass.",
    )
    entry_point: str | None = Field(
        default=None,
        description="Primary entry file for the module, if applicable.",
    )
    notes: str | None = Field(
        default=None,
        description="Caveats, TODOs, or assumptions worth surfacing downstream.",
    )


class SelfFixResult(_Schema):
    """Structured summary of a self-fix pass over failing lint/test output."""

    summary: str = Field(description="What was diagnosed and how it was fixed.")
    files_written: list[str] = Field(
        default_factory=list,
        description="Relative paths modified to resolve the failures.",
    )
    resolved: bool = Field(
        description="True if the agent believes the reported failures are fixed."
    )
    remaining_issues: list[str] = Field(
        default_factory=list,
        description="Failures the agent could not resolve this pass.",
    )
