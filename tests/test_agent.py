from __future__ import annotations

import json
from types import SimpleNamespace

from agent import Agent
from context import ContextManager
from loop_detector import LoopDetector
from session_logger import SessionLogger
from tools.registry import ToolRegistry


def tool_call(call_id: str, name: str, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class FakeMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant"}
        if self.content is not None:
            result["content"] = self.content
        if self.tool_calls is not None:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return result


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return self.responses.pop(0)


def test_agent_runs_precise_edit_validation_and_final_response(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    fake = FakeLLM(
        [
            FakeMessage(tool_calls=[tool_call("c1", "read_file", {"path": "calc.py"})]),
            FakeMessage(
                tool_calls=[
                    tool_call(
                        "c2",
                        "edit_file",
                        {"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"},
                    )
                ]
            ),
            FakeMessage(
                tool_calls=[
                    tool_call(
                        "c3",
                        "run_command",
                        {"command": 'python -c "from calc import add; assert add(2,3)==5"'},
                    )
                ]
            ),
            FakeMessage(content="Fixed calc.py and validated the behavior."),
        ]
    )
    logger = SessionLogger(tmp_path / "logs")
    agent = Agent(
        llm=fake,
        tools=ToolRegistry(tmp_path),
        max_steps=10,
        verbose=False,
        context_manager=ContextManager(max_history_chars=20_000, max_tool_result_chars=2_000),
        loop_detector=LoopDetector(),
        session_logger=logger,
    )
    final = agent.run("Fix add")
    assert "validated" in final
    assert "return a + b" in (tmp_path / "calc.py").read_text(encoding="utf-8")
    assert agent.state.changed_files == {"calc.py"}
    assert agent.state.commands_run
    assert logger.path.exists()
    # Tool-call protocol is preserved in the full history.
    tool_messages = [m for m in agent.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2", "c3"]


def test_agent_nudges_once_when_files_changed_without_validation(tmp_path):
    (tmp_path / "x.py").write_text("value = 1\n", encoding="utf-8")
    fake = FakeLLM(
        [
            FakeMessage(
                tool_calls=[
                    tool_call(
                        "c1",
                        "edit_file",
                        {"path": "x.py", "old_text": "value = 1", "new_text": "value = 2"},
                    )
                ]
            ),
            FakeMessage(content="Done."),
            FakeMessage(content="No executable validation is appropriate for this tiny requested constant change."),
        ]
    )
    agent = Agent(llm=fake, tools=ToolRegistry(tmp_path), max_steps=5, verbose=False)
    final = agent.run("Change value to 2")
    assert "No executable validation" in final
    assert len(fake.calls) == 3
    assert any(
        m.get("role") == "user" and "Runtime validation guard" in m.get("content", "")
        for m in agent.messages
    )
