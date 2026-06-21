"""Pydantic output schemas for the Test Generator agent.

``TestSuite`` is the LLM-facing structured-output contract: a summary plus the
generated test files. Each :class:`GeneratedTestFile` carries its target path,
content, and kind so the agent can merge them into the project's ``source_code``
map and report what was produced.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TestKind = Literal["unit", "widget", "integration"]
"""The category of a generated test (widget ≈ component/UI tests)."""


class _Schema(BaseModel):
    """Base config: ignore unexpected LLM fields rather than hard-failing."""

    model_config = ConfigDict(extra="ignore")


class GeneratedTestFile(_Schema):
    """A single generated test file."""

    path: str = Field(
        description="Relative path for the test file, e.g. 'src/__tests__/auth.test.ts'."
    )
    content: str = Field(description="Complete, runnable test file source.")
    kind: TestKind = Field(description="unit | widget | integration.")
    target: str = Field(
        description="What this test exercises (module/component/flow name)."
    )


class TestSuite(_Schema):
    """LLM-facing structured output: a summary plus all generated test files."""

    summary: str = Field(
        description="One-paragraph summary of the tests produced and their intent."
    )
    files: list[GeneratedTestFile] = Field(
        default_factory=list,
        description="The generated test files; empty only if nothing is testable.",
    )
