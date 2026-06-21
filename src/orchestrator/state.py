"""LangGraph state definition and external boundary models.

Design (per project Boundary Rule):
* **Inner state** -> :class:`AgentState` is a ``TypedDict`` using LangGraph
  reducer channels (``add_messages`` / ``operator.add`` / dict-merge). It is
  fast, hashable-by-channel, and serializable by the checkpointer.
* **Outer boundaries** -> :class:`UserRequest` and :class:`AgentResponse` are
  Pydantic ``BaseModel`` instances used for API validation (user input/output).

Nodes never mutate the state in place. Each node returns a *partial* dict and
the registered reducers merge it into the running state. ``operator.add`` channels
accumulate (cost, global step counter); plain channels overwrite (latest value).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Type aliases
# --------------------------------------------------------------------------- #

Platform = Literal["react-native", "flutter", "native-ios", "native-android"]
"""Supported target mobile platforms."""

WorkflowStatus = Literal[
    "pending",
    "architecting",
    "coding",
    "inner_loop",
    "security_scan",
    "test_generation",
    "review",
    "awaiting_hitl",
    "deploying",
    "completed",
    "failed",
]
"""High-level lifecycle status of a project run through the graph."""

ReviewDecision = Literal["PASS", "FAIL"]
"""Outcome emitted by the Reviewer agent."""

HITLDecision = Literal["approve", "reject"]
"""Human verdict recorded by a HITL gate node (drives ``edges.hitl_route``)."""

# Files map: relative path -> file content.
SourceCode = dict[str, str]


# --------------------------------------------------------------------------- #
# Reducers
# --------------------------------------------------------------------------- #


def merge_source_code(left: Optional[SourceCode], right: Optional[SourceCode]) -> SourceCode:
    """Reducer that incrementally merges generated files.

    The Coder agent emits files module-by-module, so later updates must be
    folded into the accumulated map rather than replacing it. Keys present in
    ``right`` overwrite keys in ``left`` (a regenerated file wins). ``None`` on
    either side is treated as an empty map so the channel is safe to leave unset.

    Args:
        left: The previously accumulated file map (running state).
        right: The new partial file map returned by a node.

    Returns:
        A new merged ``{path: content}`` dictionary.
    """
    merged: SourceCode = dict(left or {})
    merged.update(right or {})
    return merged


# --------------------------------------------------------------------------- #
# Inner graph state (TypedDict + reducer channels)
# --------------------------------------------------------------------------- #


class AgentState(TypedDict, total=False):
    """Mutable state shared across all LangGraph nodes.

    ``total=False`` so nodes may return partial updates. Use
    :func:`create_initial_state` to construct a fully-populated starting state
    (reducer channels such as ``operator.add`` require a concrete initial value).
    """

    # --- Conversation & accumulators (reducer channels) -------------------- #
    messages: Annotated[list[AnyMessage], add_messages]
    """Full message history; ``add_messages`` appends/merges by id."""

    total_cost_usd: Annotated[float, operator.add]
    """Accumulated USD spend across every agent invocation."""

    iteration_count: Annotated[int, operator.add]
    """Monotonic global step counter (never reset; guards runaway loops)."""

    source_code: Annotated[SourceCode, merge_source_code]
    """Incrementally merged ``{path: content}`` map of generated files."""

    # --- Request context (overwrite channels) ------------------------------ #
    project_id: Optional[str]
    """Persisted project identifier (matches ``db.models.Project.id``)."""

    prompt: str
    """Original natural-language request from the user."""

    platform: Optional[Platform]
    """Resolved/preferred target platform (may start as a user hint)."""

    # --- Agent outputs (overwrite channels) -------------------------------- #
    architecture_spec: Optional[dict[str, Any]]
    """Architect ADR output (validated against agent schemas in S3)."""

    review_notes: Optional[str]
    """Latest Reviewer feedback (overwritten each review pass)."""

    review_decision: Optional[ReviewDecision]
    """Latest Reviewer verdict, ``PASS`` or ``FAIL``."""

    hitl_decision: Optional[HITLDecision]
    """Latest human verdict from a HITL gate; routed on by ``edges.hitl_route``."""

    pr_number: Optional[int]
    """Pull-request number for the build, when one exists (enables auto-merge)."""

    repo: Optional[str]
    """GitHub ``owner/name`` slug for the build's PR (enables auto-merge)."""

    security_score: Optional[int]
    """Security posture score 0-100 from the Security agent."""

    security_critical: bool
    """True when a critical/HIGH severity finding requires a HITL gate."""

    lint_passed: Optional[bool]
    """Result of the most recent inner-loop lint run."""

    tests_passed: Optional[bool]
    """Result of the most recent inner-loop / generated test run."""

    # --- Loop control (overwrite channels; resettable) --------------------- #
    inner_loop_count: int
    """Current inner-loop (lint/test self-fix) iteration; reset per module."""

    outer_loop_count: int
    """Current outer-loop (review->coder) iteration."""

    # --- Routing & lifecycle ----------------------------------------------- #
    next_agent: Optional[str]
    """Supervisor's chosen handoff target for the next step."""

    status: WorkflowStatus
    """Current lifecycle status of the run."""

    error: Optional[str]
    """Last error message, if the run entered a failure path."""


# --------------------------------------------------------------------------- #
# Boundary models (Pydantic v2 — API input/output validation)
# --------------------------------------------------------------------------- #


class UserRequest(BaseModel):
    """Validated external input that kicks off a project run."""

    prompt: str = Field(min_length=1, description="Natural-language app idea/spec.")
    platform: Optional[Platform] = Field(
        default=None, description="Optional preferred target platform."
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict, description="Free-form user preferences/constraints."
    )
    max_cost_usd: Optional[float] = Field(
        default=None, gt=0, description="Per-project budget override (defaults to guardrails)."
    )


class AgentResponse(BaseModel):
    """Validated external snapshot of a run's state for API responses."""

    project_id: Optional[str] = None
    status: WorkflowStatus = "pending"
    architecture_spec: Optional[dict[str, Any]] = None
    source_code: SourceCode = Field(default_factory=dict)
    review_decision: Optional[ReviewDecision] = None
    security_score: Optional[int] = None
    total_cost_usd: float = 0.0
    iteration_count: int = 0
    error: Optional[str] = None


# --------------------------------------------------------------------------- #
# State factories / boundary converters
# --------------------------------------------------------------------------- #


def create_initial_state(
    request: UserRequest, project_id: Optional[str] = None
) -> AgentState:
    """Build a fully-populated initial :class:`AgentState` from a request.

    Reducer channels are seeded with concrete zero values so the first
    ``operator.add`` / merge does not fail. Use this as the input to
    ``graph.invoke`` / ``graph.stream``.

    Args:
        request: The validated user request.
        project_id: Optional persisted project id to thread into state.

    Returns:
        A complete starting state.
    """
    return AgentState(
        messages=[],
        total_cost_usd=0.0,
        iteration_count=0,
        source_code={},
        project_id=project_id,
        prompt=request.prompt,
        platform=request.platform,
        architecture_spec=None,
        review_notes=None,
        review_decision=None,
        hitl_decision=None,
        pr_number=None,
        repo=None,
        security_score=None,
        security_critical=False,
        lint_passed=None,
        tests_passed=None,
        inner_loop_count=0,
        outer_loop_count=0,
        next_agent=None,
        status="pending",
        error=None,
    )


def build_response(state: AgentState) -> AgentResponse:
    """Project the inner graph state onto the external response boundary.

    Reads defensively (``.get``) because nodes may have populated only a subset
    of the channels at the time the snapshot is taken.

    Args:
        state: The current (possibly partial) graph state.

    Returns:
        A validated :class:`AgentResponse`.
    """
    return AgentResponse(
        project_id=state.get("project_id"),
        status=state.get("status", "pending"),
        architecture_spec=state.get("architecture_spec"),
        source_code=state.get("source_code", {}),
        review_decision=state.get("review_decision"),
        security_score=state.get("security_score"),
        total_cost_usd=state.get("total_cost_usd", 0.0),
        iteration_count=state.get("iteration_count", 0),
        error=state.get("error"),
    )
