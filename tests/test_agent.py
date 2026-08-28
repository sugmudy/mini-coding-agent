from __future__ import annotations

from dataclasses import dataclass

from agent import Agent
from tools.registry import ToolRegistry


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


class FakeMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        payload = {"role": "assistant"}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [
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
        return payload


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return FakeMessage(
                tool_calls=[
                    FakeToolCall(
                        id="call_1",
                        function=FakeFunction(
                            name="write_file",
                            arguments='{"path":"hello.py","content":"print(123)\\n"}',
                        ),
                    )
                ]
            )
        return FakeMessage(content="Created hello.py and finished the task.")


def test_agent_executes_tool_and_continues(tmp_path):
    agent = Agent(
        llm=FakeLLM(),
        tools=ToolRegistry(tmp_path),
        max_steps=3,
        verbose=False,
    )
    final = agent.run("Create hello.py")
    assert "finished" in final
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print(123)\n"
    assert any(message.get("role") == "tool" for message in agent.messages)
