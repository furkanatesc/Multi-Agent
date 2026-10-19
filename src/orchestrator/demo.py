"""Keyless demo/mock orchestration graph (Sprint 8, PR-A).

Mirrors the real pipeline topology (:mod:`src.orchestrator.graph`) and the
**real** HITL gate mechanics, but replaces every LLM/Docker-backed agent node
with a deterministic stub that emits canned output after a small ``delay``. This
lets the dashboard stream a full run — pausing at both HITL gates — with no API
keys and no Docker (spec §4.3).

The security stub intentionally reports a critical finding so the security HITL
gate fires; the deploy gate always fires after the (stub) PASS review. Gates use
``HITLGate(..., persist=False)`` so no database is required.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.orchestrator import edges
from src.orchestrator.hitl import HITLGate
from src.orchestrator.state import AgentState

_STUB_COST = 0.01


def _make_nodes(delay: float) -> dict[str, Any]:
    """Build the stub node callables, closing over the per-step ``delay``."""

    def _sleep() -> None:
        if delay > 0:
            time.sleep(delay)

    def _msg(name: str, content: str, **updates: Any) -> dict[str, Any]:
        update: dict[str, Any] = {
            "messages": [AIMessage(content=content, name=name)],
            "iteration_count": 1,
            "total_cost_usd": _STUB_COST,
        }
        update.update(updates)
        return update

    def supervisor(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "supervisor",
            "[supervisor] demo run started; dispatching to architect",
            status="architecting",
            next_agent="architect",
        )

    def architect(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "architect",
            "[architect] demo ADR generated",
            architecture_spec={
                "project_name": "DemoApp",
                "tech_stack": {"platform": "react-native"},
                "summary": "A demo mobile app scaffolded by the mock pipeline.",
            },
            platform="react-native",
            status="coding",
            next_agent="coder",
        )

    def coder(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "coder",
            "[coder] demo module written",
            source_code={"src/App.tsx": "// demo generated component\n"},
            lint_passed=None,
            tests_passed=None,
            status="inner_loop",
            next_agent="inner_loop_check",
        )

    def inner_loop_check(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "inner_loop",
            "[inner_loop] demo lint+tests passed (0 self-fix iters)",
            lint_passed=True,
            tests_passed=True,
            inner_loop_count=0,
            status="security_scan",
        )

    def security_scan(state: AgentState) -> dict[str, Any]:
        _sleep()
        # Force the security HITL gate to fire so the full HITL UI is exercised.
        return _msg(
            "security",
            "[security] demo scan: score=60, critical finding requires approval",
            security_score=60,
            security_critical=True,
            status="security_scan",
        )

    def security_gate(state: AgentState) -> dict[str, Any]:
        resolution = HITLGate("security", persist=False).request(state)
        if resolution.approved:
            return {
                "messages": [
                    AIMessage(
                        content="[hitl] security approved — accepting risk",
                        name="hitl",
                    )
                ],
                "iteration_count": 1,
                "status": "test_generation",
                "hitl_decision": "approve",
            }
        return {
            "messages": [
                AIMessage(
                    content="[hitl] security rejected — back to coder", name="hitl"
                )
            ],
            "iteration_count": 1,
            "status": "coding",
            "hitl_decision": "reject",
        }

    def test_generator(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "test_generator",
            "[test_generator] demo tests generated",
            source_code={"src/App.test.tsx": "// demo test\n"},
            tests_passed=True,
            status="test_generation",
        )

    def reviewer(state: AgentState) -> dict[str, Any]:
        _sleep()
        outer = int(state.get("outer_loop_count", 0)) + 1
        return _msg(
            "reviewer",
            "[reviewer] demo review: PASS",
            review_decision="PASS",
            review_notes="LGTM (demo review)",
            outer_loop_count=outer,
            status="review",
        )

    def deploy_gate(state: AgentState) -> dict[str, Any]:
        resolution = HITLGate("deploy", persist=False).request(state)
        if resolution.approved:
            return {
                "messages": [
                    AIMessage(content="[hitl] deploy approved", name="hitl")
                ],
                "iteration_count": 1,
                "status": "deploying",
                "hitl_decision": "approve",
            }
        return {
            "messages": [
                AIMessage(content="[hitl] deploy rejected — aborted", name="hitl")
            ],
            "iteration_count": 1,
            "status": "failed",
            "hitl_decision": "reject",
            "error": "Deployment rejected by human reviewer.",
        }

    def deployer(state: AgentState) -> dict[str, Any]:
        _sleep()
        return _msg(
            "deployer",
            "[deployer] demo deploy complete",
            status="completed",
            next_agent=None,
        )

    return {
        "supervisor": supervisor,
        "architect": architect,
        "coder": coder,
        "inner_loop_check": inner_loop_check,
        "security_scan": security_scan,
        "hitl_gate": security_gate,
        "test_generator": test_generator,
        "reviewer": reviewer,
        "deploy_gate": deploy_gate,
        "deployer": deployer,
    }


def build_demo_graph(delay: float = 0.5) -> Any:
    """Compile the keyless demo graph (InMemorySaver, stub nodes, real gates).

    Args:
        delay: Seconds each stub node sleeps to simulate progress (0 in tests).
    """
    nodes = _make_nodes(delay)
    builder = StateGraph(AgentState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor", edges.cost_check, {"halt": END, "continue": "architect"}
    )
    builder.add_edge("architect", "coder")
    builder.add_edge("coder", "inner_loop_check")
    builder.add_conditional_edges(
        "inner_loop_check",
        edges.should_continue_inner_loop,
        {"fix": "coder", "proceed": "security_scan"},
    )
    builder.add_conditional_edges(
        "security_scan",
        edges.security_gate,
        {"block_hitl": "hitl_gate", "fix": "coder", "proceed": "test_generator"},
    )
    builder.add_conditional_edges(
        "hitl_gate",
        edges.hitl_route,
        {"approve": "test_generator", "reject": "coder"},
    )
    builder.add_edge("test_generator", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        edges.review_decision,
        {"approve": "deploy_gate", "reject": "coder", "escalate": END},
    )
    builder.add_conditional_edges(
        "deploy_gate", edges.hitl_route, {"approve": "deployer", "reject": END}
    )
    builder.add_edge("deployer", END)

    return builder.compile(checkpointer=InMemorySaver())
