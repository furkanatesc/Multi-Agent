"""LangGraph ``StateGraph`` assembly and compilation.

Wires the stub nodes (``nodes.py``) together with the conditional routers
(``edges.py``) into a compiled graph with a checkpointer attached. The topology
already reflects the full target pipeline so later sprints only swap stub node
implementations — the edges and gates stay put.

Flow::

    START -> supervisor -(cost_check)-> architect | END
    architect -> coder -> inner_loop_check
    inner_loop_check -(should_continue_inner_loop)-> coder | security_scan
    security_scan -(security_gate)-> coder | hitl_gate | test_generator
    hitl_gate -> test_generator -> reviewer
    reviewer -(review_decision)-> deployer | coder | END
    deployer -> END
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from src.core.logging import logger
from src.orchestrator import edges, nodes
from src.orchestrator.state import AgentState


def build_graph(checkpointer: Optional[Any] = None) -> Any:
    """Construct and compile the orchestration graph.

    Args:
        checkpointer: A LangGraph checkpointer (e.g. ``InMemorySaver`` for tests,
            ``PostgresSaver`` for production). When ``None`` the graph compiles
            without persistence.

    Returns:
        The compiled graph, ready for ``.invoke`` / ``.stream``.
    """
    builder = StateGraph(AgentState)

    # --- Nodes ------------------------------------------------------------- #
    builder.add_node("supervisor", nodes.supervisor)
    builder.add_node("architect", nodes.architect)
    builder.add_node("coder", nodes.coder)
    builder.add_node("inner_loop_check", nodes.inner_loop_check)
    builder.add_node("security_scan", nodes.security_scan)
    builder.add_node("hitl_gate", nodes.hitl_gate)
    builder.add_node("test_generator", nodes.test_generator)
    builder.add_node("reviewer", nodes.reviewer)
    builder.add_node("deployer", nodes.deployer)

    # --- Edges ------------------------------------------------------------- #
    builder.add_edge(START, "supervisor")

    # Budget gate before any work begins.
    builder.add_conditional_edges(
        "supervisor",
        edges.cost_check,
        {"halt": END, "continue": "architect"},
    )

    builder.add_edge("architect", "coder")
    builder.add_edge("coder", "inner_loop_check")

    # Inner self-fix loop: keep fixing until lint/test pass or cap reached.
    builder.add_conditional_edges(
        "inner_loop_check",
        edges.should_continue_inner_loop,
        {"fix": "coder", "proceed": "security_scan"},
    )

    # Security gate: block (HITL), send back to coder, or proceed.
    builder.add_conditional_edges(
        "security_scan",
        edges.security_gate,
        {"block_hitl": "hitl_gate", "fix": "coder", "proceed": "test_generator"},
    )

    builder.add_edge("hitl_gate", "test_generator")
    builder.add_edge("test_generator", "reviewer")

    # Outer review loop: ship, retry via coder, or escalate and stop.
    builder.add_conditional_edges(
        "reviewer",
        edges.review_decision,
        {"approve": "deployer", "reject": "coder", "escalate": END},
    )

    builder.add_edge("deployer", END)

    compiled = builder.compile(checkpointer=checkpointer)
    logger.info(
        "Orchestration graph compiled",
        checkpointer=type(checkpointer).__name__ if checkpointer else None,
    )
    return compiled
