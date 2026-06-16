"""Unit tests for the Architect agent (mock LLM) and its helper tools."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agents.architect.agent import ArchitectAgent
from src.agents.architect.schemas import ADRDocument, TechStack
from src.agents.architect.tools import analyze_requirements, default_folder_structure
from src.agents.base import AgentOutputError

# A complete, valid ADRDocument as the LLM would return it.
_VALID_ADR: dict[str, Any] = {
    "project_name": "ShopEasy",
    "summary": "Cross-platform e-commerce app with offline cart.",
    "architecture_pattern": "clean-architecture",
    "tech_stack": {
        "platform": "react-native",
        "language": "TypeScript",
        "framework": "React Native",
        "state_management": "Redux Toolkit",
        "key_libraries": ["react-navigation", "axios"],
    },
    "folder_structure": {
        "description": "Feature-first",
        "entries": [{"path": "src/features/cart/", "purpose": "Cart feature"}],
    },
    "decisions": [
        {
            "id": "ADR-001",
            "title": "Use React Native",
            "context": "Need fast cross-platform delivery for an e-commerce MVP.",
            "decision": "Adopt React Native with Redux Toolkit.",
            "consequences": "Shared codebase; JS ecosystem.",
            "alternatives_considered": ["Flutter", "Native"],
        }
    ],
}


def _fake_response(content: str) -> SimpleNamespace:
    """Build an OpenAI/LiteLLM-shaped response with the given message content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _agent_with_response(content: str, costs: tuple[float, float] = (0.0, 0.05)) -> ArchitectAgent:
    """Construct an ArchitectAgent wired to a mock client returning ``content``."""
    client = MagicMock()
    client.completion.return_value = _fake_response(content)
    # current_cost() is read before and after each completion.
    client.get_metrics.side_effect = [
        {"total_cost_usd": costs[0]},
        {"total_cost_usd": costs[1]},
    ]
    return ArchitectAgent(client=client, system_prompt="SYSTEM")


# --------------------------------------------------------------------------- #
# generate_adr / run
# --------------------------------------------------------------------------- #


def test_generate_adr_returns_valid_document() -> None:
    agent = _agent_with_response(json.dumps(_VALID_ADR))
    doc, cost = agent.generate_adr("Build an e-commerce app")

    assert isinstance(doc, ADRDocument)
    assert doc.project_name == "ShopEasy"
    assert doc.tech_stack.platform == "react-native"
    assert doc.architecture_pattern == "clean-architecture"
    assert cost == pytest.approx(0.05)


def test_run_writes_partial_state() -> None:
    agent = _agent_with_response(json.dumps(_VALID_ADR))
    update = agent.run({"prompt": "Build an e-commerce app", "platform": None})

    assert update["platform"] == "react-native"
    assert update["architecture_spec"]["project_name"] == "ShopEasy"
    assert update["total_cost_usd"] == pytest.approx(0.05)
    assert update["iteration_count"] == 1
    assert update["status"] == "coding"
    assert update["next_agent"] == "coder"


def test_folder_structure_backfilled_when_missing() -> None:
    adr = {**_VALID_ADR, "folder_structure": {"description": "", "entries": []}}
    agent = _agent_with_response(json.dumps(adr))
    doc, _ = agent.generate_adr("Build a Flutter game")

    # Empty entries -> default layout injected based on the tech stack.
    assert len(doc.folder_structure.entries) > 0


def test_non_json_output_raises() -> None:
    agent = _agent_with_response("not json at all")
    with pytest.raises(AgentOutputError):
        agent.generate_adr("Build something")


def test_schema_validation_error_raises() -> None:
    # Missing required fields (e.g. tech_stack) -> validation failure.
    agent = _agent_with_response(json.dumps({"project_name": "X"}))
    with pytest.raises(AgentOutputError):
        agent.generate_adr("Build something")


# --------------------------------------------------------------------------- #
# helper tools
# --------------------------------------------------------------------------- #


def test_analyze_requirements_suggests_react_native_for_ecommerce() -> None:
    result = analyze_requirements("Build an e-commerce marketplace with a social feed")
    assert result["suggested_platform"] == "react-native"


def test_analyze_requirements_suggests_flutter_for_performance() -> None:
    result = analyze_requirements("A high performance real-time gaming app with heavy graphics")
    assert result["suggested_platform"] == "flutter"


def test_analyze_requirements_neutral_when_no_signals() -> None:
    result = analyze_requirements("A simple utility")
    assert result["suggested_platform"] is None


def test_default_folder_structure_per_framework() -> None:
    rn = default_folder_structure(
        TechStack(platform="react-native", language="TS", framework="React Native", state_management="Redux")
    )
    flutter = default_folder_structure(
        TechStack(platform="flutter", language="Dart", framework="Flutter", state_management="Riverpod")
    )
    assert any(e.path.startswith("src/") for e in rn.entries)
    assert any(e.path.startswith("lib/") for e in flutter.entries)
