from __future__ import annotations

from copy import deepcopy

from context import ContextManager


def assistant_call(call_id: str, name: str, args: str):
    return {
        "role": "assistant",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}],
    }


def tool_result(call_id: str, content: str):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_tool_results_are_head_tail_truncated():
    manager = ContextManager(max_history_chars=20_000, max_tool_result_chars=2_000)
    text = "A" * 2_000 + "B" * 2_000
    trimmed = manager.truncate_tool_result(text)
    assert len(trimmed) <= 2_000
    assert trimmed.startswith("A")
    assert trimmed.endswith("B")
    assert "truncated" in trimmed


def test_prepare_compacts_only_complete_interaction_blocks():
    manager = ContextManager(max_history_chars=20_000, max_tool_result_chars=2_000)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    for i in range(15):
        messages.append(assistant_call(f"c{i}", "read_file", f'{{"path":"f{i}.py"}}'))
        messages.append(tool_result(f"c{i}", "x" * 2_000))

    original = deepcopy(messages)
    prepared = manager.prepare(messages)
    assert messages == original
    assert prepared[0]["role"] == "system"
    assert prepared[1]["role"] == "user"
    assert any("Context compaction summary" in m.get("content", "") for m in prepared)

    call_ids = {
        call["id"]
        for message in prepared
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    }
    for message in prepared:
        if message.get("role") == "tool":
            assert message["tool_call_id"] in call_ids


def test_prepare_leaves_small_history_semantically_unchanged():
    manager = ContextManager(max_history_chars=20_000, max_tool_result_chars=2_000)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert manager.prepare(messages) == messages
