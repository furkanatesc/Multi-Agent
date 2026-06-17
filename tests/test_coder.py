"""Unit tests for the Coder agent, its workspace/file tools, and schemas.

The real tool-loop (``create_react_agent``) is replaced by a fake that drives the
*actual* file tools, so workspace behavior is exercised without any live LLM; the
structured-summary call uses a mock client (as in ``test_architect.py``).
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agents.coder.agent import CoderAgent
from src.agents.coder.schemas import GeneratedModule, SelfFixResult
from src.agents.coder.tools import Workspace, WorkspacePathError, make_file_tools
from src.integrations.litellm_client import LiteLLMClient

# --------------------------------------------------------------------------- #
# Workspace
# --------------------------------------------------------------------------- #


def test_workspace_write_read_list() -> None:
    ws = Workspace()
    assert ws.write("src/App.tsx", "code") == "wrote src/App.tsx (4 bytes)"
    assert ws.read("src/App.tsx") == "code"
    assert ws.list_paths() == ["src/App.tsx"]


def test_workspace_normalizes_backslashes() -> None:
    ws = Workspace()
    ws.write("src\\components\\Btn.tsx", "x")
    assert "src/components/Btn.tsx" in ws.files


def test_workspace_seeds_from_existing_files() -> None:
    ws = Workspace({"a.py": "1"})
    assert ws.read("a.py") == "1"


@pytest.mark.parametrize("bad", ["/etc/passwd", "C:/x", "../escape", "", "  "])
def test_workspace_rejects_unsafe_paths(bad: str) -> None:
    ws = Workspace()
    with pytest.raises(WorkspacePathError):
        ws.write(bad, "x")


def test_workspace_read_missing_raises() -> None:
    with pytest.raises(WorkspacePathError):
        Workspace().read("nope.py")


# --------------------------------------------------------------------------- #
# file tools
# --------------------------------------------------------------------------- #


def test_tools_write_and_read_via_invoke() -> None:
    ws = Workspace()
    tools = {t.name: t for t in make_file_tools(ws)}

    msg = tools["write_file"].invoke({"path": "main.py", "content": "print(1)"})
    assert "wrote main.py" in msg
    assert tools["read_file"].invoke({"path": "main.py"}) == "print(1)"
    assert "main.py" in tools["list_files"].invoke({})


def test_tools_return_error_string_on_bad_path() -> None:
    ws = Workspace()
    tools = {t.name: t for t in make_file_tools(ws)}
    out = tools["write_file"].invoke({"path": "../x", "content": "y"})
    assert out.startswith("ERROR:")


def test_list_files_empty_message() -> None:
    tools = {t.name: t for t in make_file_tools(Workspace())}
    assert tools["list_files"].invoke({}) == "(workspace is empty)"


# --------------------------------------------------------------------------- #
# CoderAgent (tool-loop faked, summary via mock client)
# --------------------------------------------------------------------------- #


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class _FakeReactAgent:
    """Stands in for create_react_agent's result; writes files via the tools."""

    def __init__(self, tools: list[Any], writes: dict[str, str]) -> None:
        self._tools = {t.name: t for t in tools}
        self._writes = writes

    def invoke(self, _inp: Any, config: Any = None) -> dict[str, Any]:
        for path, content in self._writes.items():
            self._tools["write_file"].invoke({"path": path, "content": content})
        return {"messages": []}


def _agent_with(
    monkeypatch: pytest.MonkeyPatch,
    summary: dict[str, Any],
    writes: dict[str, str],
) -> CoderAgent:
    """Build a CoderAgent whose tool-loop writes ``writes`` and summary is mocked."""
    client = MagicMock(spec=LiteLLMClient)
    client.get_metrics.return_value = {"total_cost_usd": 0.0}
    client.completion.return_value = _fake_response(json.dumps(summary))

    def _fake_create(model: Any, tools: Any, prompt: Any = None) -> _FakeReactAgent:
        return _FakeReactAgent(tools, writes)

    monkeypatch.setattr("src.agents.coder.agent.create_react_agent", _fake_create)
    return CoderAgent(client=client, system_prompt="SYS")


def test_generate_module_writes_files_and_returns_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {"summary": "Built the app", "files_written": ["src/App.tsx"]}
    agent = _agent_with(monkeypatch, summary, {"src/App.tsx": "code"})

    ws = Workspace()
    module, cost = agent.generate_module({"project_name": "X"}, "build it", ws)

    assert isinstance(module, GeneratedModule)
    assert module.summary == "Built the app"
    assert ws.files == {"src/App.tsx": "code"}
    assert isinstance(cost, float)


def test_run_returns_partial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = {"summary": "done", "files_written": ["lib/main.dart"]}
    agent = _agent_with(monkeypatch, summary, {"lib/main.dart": "void main(){}"})

    update = agent.run({"architecture_spec": {"project_name": "X"}, "prompt": "go"})

    assert update["source_code"] == {"lib/main.dart": "void main(){}"}
    assert update["lint_passed"] is None
    assert update["tests_passed"] is None
    assert update["status"] == "inner_loop"
    assert update["next_agent"] == "inner_loop_check"
    assert update["iteration_count"] == 1


def test_run_carries_forward_existing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {"summary": "patched", "files_written": ["b.py"]}
    agent = _agent_with(monkeypatch, summary, {"b.py": "new"})

    update = agent.run(
        {
            "architecture_spec": {},
            "prompt": "go",
            "source_code": {"a.py": "kept"},
        }
    )

    # Prior file retained, new file added.
    assert update["source_code"] == {"a.py": "kept", "b.py": "new"}


def test_self_fix_returns_result_and_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {
        "summary": "fixed import",
        "files_written": ["a.py"],
        "resolved": True,
        "remaining_issues": [],
    }
    agent = _agent_with(monkeypatch, summary, {"a.py": "import os"})

    result, cost, ws = agent.self_fix({"a.py": "improt os"}, lint_output="E999")

    assert isinstance(result, SelfFixResult)
    assert result.resolved is True
    assert ws.files["a.py"] == "import os"
    assert isinstance(cost, float)
