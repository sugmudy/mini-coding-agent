from __future__ import annotations

from types import SimpleNamespace

from llm_client import LLMClient


def ns(**values):
    return SimpleNamespace(**values)


class Usage:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return dict(self.values)


def chunk(*deltas, usage=None):
    return ns(choices=[ns(delta=delta) for delta in deltas], usage=usage)


def tool_delta(index, *, call_id=None, name=None, arguments=None):
    return ns(
        index=index,
        id=call_id,
        type="function" if call_id else None,
        function=ns(name=name, arguments=arguments),
    )


def test_stream_assembles_text_reasoning_tools_and_usage():
    chunks = [
        chunk(ns(role="assistant", content=None, reasoning_content="Inspecting ", tool_calls=None)),
        chunk(
            ns(
                role=None,
                content=None,
                reasoning_content="workspace",
                tool_calls=[
                    tool_delta(0, call_id="call_1", name="write_", arguments='{"pa'),
                    tool_delta(1, call_id="call_2", name="list_files", arguments="{"),
                ],
            )
        ),
        chunk(
            ns(
                role=None,
                content=None,
                reasoning_content=None,
                tool_calls=[
                    tool_delta(0, name="file", arguments='th":"a.py"}'),
                    tool_delta(1, arguments="}"),
                ],
            )
        ),
        chunk(usage=Usage(prompt_tokens=20, completion_tokens=8, total_tokens=28)),
    ]

    message, usage = LLMClient._consume_stream(chunks)

    assert message == {
        "role": "assistant",
        "reasoning_content": "Inspecting workspace",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "write_file", "arguments": '{"path":"a.py"}'},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "list_files", "arguments": "{}"},
            },
        ],
    }
    assert usage == {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}


def test_stream_assembles_plain_text_message():
    message, usage = LLMClient._consume_stream(
        [
            chunk(ns(role="assistant", content="hel", reasoning_content=None, tool_calls=None)),
            chunk(ns(role=None, content="lo", reasoning_content=None, tool_calls=None)),
        ]
    )

    assert message == {"role": "assistant", "content": "hello"}
    assert usage == {}


def test_complete_requests_streaming_and_commits_usage_after_success():
    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client.stream = True
    client.parallel_tool_calls = False
    client.reasoning_effort = "low"
    client.max_retries = 0
    client.retry_backoff = 0
    client.sleep_fn = lambda _: None
    client.last_usage = {}
    client._openai_error_type = lambda: Exception
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return [
            chunk(ns(role="assistant", content="ok", reasoning_content=None, tool_calls=None)),
            chunk(usage=Usage(total_tokens=7)),
        ]

    client.client = ns(chat=ns(completions=ns(create=create)))

    result = client.complete([{"role": "user", "content": "hi"}], [])

    assert result == {"role": "assistant", "content": "ok"}
    assert client.last_usage == {"total_tokens": 7}
    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["parallel_tool_calls"] is False
    assert captured["reasoning_effort"] == "low"


def test_stream_iteration_failure_retries_the_whole_request():
    class FakeConnectionError(Exception):
        pass

    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client.stream = True
    client.parallel_tool_calls = False
    client.reasoning_effort = None
    client.max_retries = 1
    client.retry_backoff = 0
    client.sleep_fn = lambda _: None
    client.last_usage = {}
    client._openai_error_type = lambda: FakeConnectionError
    client._is_retryable = lambda exc: isinstance(exc, FakeConnectionError)
    calls = {"count": 0}

    def create(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            def broken_stream():
                yield chunk(ns(role="assistant", content="partial", reasoning_content=None, tool_calls=None))
                raise FakeConnectionError("connection dropped")

            return broken_stream()
        return [chunk(ns(role="assistant", content="complete", reasoning_content=None, tool_calls=None))]

    client.client = ns(chat=ns(completions=ns(create=create)))

    result = client.complete([{"role": "user", "content": "hi"}], [])

    assert result == {"role": "assistant", "content": "complete"}
    assert calls["count"] == 2
    assert client.last_retries == 1
    assert client.last_usage == {}
