"""Pydantic output schemas for the Architect agent.

These define the *structured* contract the LLM must produce. ``ADRDocument`` is
the top-level result; the orchestrator validates the LLM's JSON into it and then
stores ``ADRDocument.model_dump()`` in ``AgentState.architecture_spec``.

``Platform`` is reused from ``orchestrator.state`` so the agent and the graph
agree on the supported platform values (single source of truth).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.orchestrator.state import Platform

ADRStatus = Literal["proposed", "accepted", "deprecated", "superseded"]
ArchitecturePattern = Literal[
    "clean-architecture",
    "mvvm",
    "mvc",
    "mvi",
    "layered",
    "feature-based",
]


class _Schema(BaseModel):
    """Base config: ignore unexpected LLM fields rather than hard-failing."""

    model_config = ConfigDict(extra="ignore")


class TechStack(_Schema):
    """The selected technology stack for the project."""

    platform: Platform = Field(description="Target mobile platform.")
    language: str = Field(description="Primary language, e.g. TypeScript or Dart.")
    framework: str = Field(description="UI framework, e.g. React Native or Flutter.")
    state_management: str = Field(
        description="State management approach, e.g. Redux Toolkit or Riverpod."
    )
    ui_library: Optional[str] = Field(
        default=None, description="UI/component library, if any."
    )
    backend: Optional[str] = Field(
        default=None, description="Backend/BaaS choice, e.g. Firebase or Supabase."
    )
    database: Optional[str] = Field(
        default=None, description="Local/remote database, e.g. SQLite or PostgreSQL."
    )
    key_libraries: list[str] = Field(
        default_factory=list, description="Other notable libraries (navigation, http, ...)."
    )


class FolderEntry(_Schema):
    """A single path in the proposed project layout and its purpose."""

    path: str = Field(description="Relative path, e.g. 'src/features/auth/'.")
    purpose: str = Field(description="What lives here / its responsibility.")


class FolderStructure(_Schema):
    """The proposed project folder layout."""

    description: str = Field(description="One-line summary of the layout rationale.")
    entries: list[FolderEntry] = Field(
        default_factory=list, description="Key directories/files and their purpose."
    )


class ArchitectureDecision(_Schema):
    """A single Architecture Decision Record (Nygard style)."""

    id: str = Field(description="ADR identifier, e.g. 'ADR-001'.")
    title: str = Field(description="Short decision title.")
    status: ADRStatus = Field(default="accepted", description="ADR status.")
    context: str = Field(description="Forces and background driving the decision.")
    decision: str = Field(description="The decision that was made.")
    consequences: str = Field(description="Resulting trade-offs, positive and negative.")
    alternatives_considered: list[str] = Field(
        default_factory=list, description="Other options that were weighed."
    )


class ADRDocument(_Schema):
    """Top-level Architect output: the full architecture decision document."""

    project_name: str = Field(description="Concise project name derived from the request.")
    summary: str = Field(description="Executive summary of the chosen architecture.")
    architecture_pattern: ArchitecturePattern = Field(
        description="Overall architectural pattern."
    )
    tech_stack: TechStack = Field(description="Selected technology stack.")
    folder_structure: FolderStructure = Field(description="Proposed project layout.")
    decisions: list[ArchitectureDecision] = Field(
        default_factory=list,
        description="One or more ADRs capturing the key choices.",
    )
