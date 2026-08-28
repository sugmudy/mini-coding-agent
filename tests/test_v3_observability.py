from __future__ import annotations

import io
import json

import pytest
from types import SimpleNamespace

from agent import Agent
from session_logger import SessionLogger
from state import AgentState
from tools.registry import ToolRegistry
from ui import FinalReport, RichUI


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


class MeteredFakeLLM:
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.last_usage = {}
        self.last_retries = 0

    def complete(self, messages, tools):
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        self.last_retries = 1 if len(self.responses) == 2 else 0
        return self.responses.pop(0)


def test_agent_accumulates_usage_retry_and_runtime_metrics(tmp_path):
    fake = MeteredFakeLLM(
        [
            FakeMessage(tool_calls=[tool_call("c1", "run_command", {"command": 'python -c "print(1)"'})]),
            FakeMessage(content="Done"),
        ]
    )
    agent = Agent(
        llm=fake,
        tools=ToolRegistry(tmp_path),
        max_steps=4,
        verbose=False,
        session_logger=SessionLogger(enabled=False),
        workspace=tmp_path,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )
    assert agent.run("Run a simple validation") == "Done"
    summary = agent.state.summary()
    assert summary["llm_calls"] == 2
    assert summary["api_retries"] == 1
    assert summary["prompt_tokens"] == 200
    assert summary["completion_tokens"] == 40
    assert summary["total_tokens"] == 240
    assert summary["tool_calls"] == 1
    assert summary["duration_ms"] >= 0
    assert agent.state.estimated_cost_usd(1.0, 2.0) == pytest.approx(0.00028)


def test_session_logger_has_stable_session_id(tmp_path):
    logger = SessionLogger(tmp_path)
    assert logger.session_id
    assert logger.session_id in logger.path.name
    logger.log("hello")
    event = json.loads(logger.path.read_text(encoding="utf-8").splitlines()[0])
    assert event["session_id"] == logger.session_id


def test_rich_ui_renders_diff_and_final_report_without_crashing():
    from rich.console import Console

    output = io.StringIO()
    ui = RichUI(no_color=True)
    ui.console = Console(file=output, force_terminal=False, no_color=True, width=120)
    payload = json.dumps(
        {
            "ok": True,
            "result": {
                "path": "a.py",
                "diff": "--- a/a.py\n+++ b/a.py\n@@\n-old\n+new\n",
            },
        }
    )
    ui.tool_result("edit_file", payload)
    ui.final_report(
        FinalReport(
            final_text="Completed",
            state={"changed_files": ["a.py"], "commands_run": [], "llm_calls": 1, "tool_calls": 1},
            session_log=None,
        )
    )
    text = output.getvalue()
    assert "edited" in text
    assert "Completed" in text
    assert "Run Report" in text
