from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from agent import Agent
from context import ContextManager
from loop_detector import LoopDetector
from main import run_interactive
from session_logger import SessionLogger
from tools.registry import ToolRegistry
from ui import BaseUI


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
        message = {"role": "assistant"}
        if self.content is not None:
            message["content"] = self.content
        if self.tool_calls is not None:
            message["tool_calls"] = [
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
        return message


class FakeLLM:
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        self.last_retries = 0

    def complete(self, messages, tools):
        self.calls.append(messages)
        return self.responses.pop(0)


def test_two_turns_preserve_prior_user_and_assistant_context(tmp_path):
    llm = FakeLLM([FakeMessage(content="The answer is 4."), FakeMessage(content="I used the prior answer.")])
    agent = Agent(llm=llm, tools=ToolRegistry(tmp_path), verbose=False)

    agent.start_session()
    assert agent.run_turn("What is two plus two?", render_report=False) == "The answer is 4."
    assert agent.run_turn("Refer to your previous answer.", render_report=False) == "I used the prior answer."
    agent.finish_session(render_report=False)

    second_model_view = llm.calls[1]
    assert [message["role"] for message in second_model_view] == ["system", "user", "assistant", "user"]
    assert second_model_view[1]["content"] == "What is two plus two?"
    assert second_model_view[2]["content"] == "The answer is 4."
    assert all(not any(key.startswith("_") for key in message) for message in second_model_view)
    assert agent.state.summary()["completed_turns"] == 2


def test_validation_guard_is_scoped_to_the_turn_that_changed_files(tmp_path):
    (tmp_path / "value.py").write_text("value = 1\n", encoding="utf-8")
    llm = FakeLLM(
        [
            FakeMessage(
                tool_calls=[
                    tool_call(
                        "edit-1",
                        "edit_file",
                        {"path": "value.py", "old_text": "value = 1", "new_text": "value = 2"},
                    )
                ]
            ),
            FakeMessage(content="Changed it."),
            FakeMessage(content="No executable validation is appropriate."),
            FakeMessage(content="The second turn only explains the result."),
        ]
    )
    agent = Agent(llm=llm, tools=ToolRegistry(tmp_path), max_steps=5, verbose=False)
    agent.start_session()
    agent.run_turn("Change the value", render_report=False)
    agent.run_turn("Explain that change", render_report=False)
    agent.finish_session(render_report=False)

    assert len(llm.calls) == 4
    assert agent.state.validation_nudges == 1
    assert agent.state.turns[0].validation_nudges == 1
    assert agent.state.turns[1].validation_nudges == 0
    assert agent.state.turns[1].changed_files == set()


def test_loop_detector_resets_repetition_history_between_user_turns():
    detector = LoopDetector(repeat_limit=3)
    arguments = '{"path":"same.py"}'
    detector.record("read_file", arguments, succeeded=True)
    detector.record("read_file", arguments, succeeded=True)
    assert detector.check("read_file", arguments) is not None
    detector.begin_turn()
    assert detector.check("read_file", arguments) is None


def test_context_compaction_preserves_latest_turn_and_tool_protocol():
    manager = ContextManager(max_history_chars=20_000, max_tool_result_chars=2_000)
    messages = [{"role": "system", "content": "system"}]
    for turn_id in range(1, 4):
        messages.append({"role": "user", "content": f"request {turn_id}", "_turn_id": turn_id})
        for call_index in range(4):
            call_id = f"{turn_id}-{call_index}"
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                        }
                    ],
                    "_turn_id": turn_id,
                }
            )
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": "x" * 2_000, "_turn_id": turn_id}
            )

    prepared = manager.prepare(messages)
    assert manager.last_prepare_compacted
    assert any(message.get("content") == "request 3" for message in prepared)
    assert all(not any(key.startswith("_") for key in message) for message in prepared)
    call_ids = {
        call["id"]
        for message in prepared
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    }
    assert all(
        message.get("tool_call_id") in call_ids
        for message in prepared
        if message.get("role") == "tool"
    )


class QueueUI(BaseUI):
    def __init__(self, inputs):
        self.inputs = iter(inputs)
        self.turn_reports = []
        self.status_calls = 0
        self.history_calls = 0

    def read_user_input(self):
        return next(self.inputs, None)

    def turn_report(self, report):
        self.turn_reports.append(report)

    def status_report(self, state, *, session_log):
        self.status_calls += 1

    def history(self, turns):
        self.history_calls += 1


def test_interactive_mode_handles_commands_without_sending_them_to_model(tmp_path):
    ui = QueueUI(["first", "/status", "/history", "/help", "second", "/exit"])
    llm = FakeLLM([FakeMessage(content="one"), FakeMessage(content="two")])
    agent = Agent(llm=llm, tools=ToolRegistry(tmp_path), verbose=False, ui=ui)

    assert run_interactive(agent, ui) == 0
    assert len(llm.calls) == 2
    assert len(ui.turn_reports) == 2
    assert ui.status_calls == 1
    assert ui.history_calls == 1
    assert not agent.session_active


def test_session_logger_keeps_usage_metrics_but_redacts_credentials(tmp_path):
    logger = SessionLogger(tmp_path)
    logger.log(
        "metrics",
        usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        api_key="secret-value",
    )
    payload = json.loads(logger.path.read_text(encoding="utf-8"))
    assert payload["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert payload["api_key"] == "[REDACTED]"


def test_same_agent_rejects_overlapping_turns(tmp_path):
    class BlockingLLM:
        model = "blocking-model"

        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()

        def complete(self, messages, tools):
            self.started.set()
            assert self.release.wait(timeout=3)
            return FakeMessage(content="first complete")

    llm = BlockingLLM()
    agent = Agent(llm=llm, tools=ToolRegistry(tmp_path), verbose=False)
    outcomes = []
    worker = threading.Thread(
        target=lambda: outcomes.append(agent.run_turn("first", render_report=False)),
        daemon=True,
    )
    worker.start()
    assert llm.started.wait(timeout=3)

    try:
        try:
            agent.run_turn("overlap", render_report=False)
        except RuntimeError as exc:
            assert "already has a running turn" in str(exc)
        else:
            raise AssertionError("Expected overlapping turn to be rejected")
    finally:
        llm.release.set()
        worker.join(timeout=3)

    assert outcomes == ["first complete"]
    agent.finish_session(render_report=False)


def test_failed_turn_is_marked_explicitly_in_followup_context(tmp_path):
    class FailingOnceLLM(FakeLLM):
        def complete(self, messages, tools):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise RuntimeError("provider details should not enter model history")
            return FakeMessage(content="recovered")

    llm = FailingOnceLLM([])
    agent = Agent(llm=llm, tools=ToolRegistry(tmp_path), verbose=False)
    try:
        agent.run_turn("first", render_report=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected first turn to fail")

    assert agent.run_turn("continue", render_report=False) == "recovered"
    failure_markers = [
        message["content"]
        for message in llm.calls[1]
        if message.get("role") == "system" and "before a final answer" in message.get("content", "")
    ]
    assert len(failure_markers) == 1
    assert "provider details" not in failure_markers[0]
    agent.finish_session(render_report=False)
