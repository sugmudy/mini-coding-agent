from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from typing import Any


class ContextManager:
    """Builds a bounded model-facing view while retaining full in-memory history."""

    def __init__(
        self,
        *,
        max_history_chars: int = 160_000,
        max_tool_result_chars: int = 30_000,
    ) -> None:
        if max_history_chars < 20_000:
            raise ValueError("max_history_chars must be at least 20000.")
        if max_tool_result_chars < 2_000:
            raise ValueError("max_tool_result_chars must be at least 2000.")
        self.max_history_chars = max_history_chars
        self.max_tool_result_chars = max_tool_result_chars

    @staticmethod
    def _message_chars(message: dict[str, Any]) -> int:
        return len(json.dumps(message, ensure_ascii=False, default=str))

    def truncate_tool_result(self, text: str) -> str:
        if len(text) <= self.max_tool_result_chars:
            return text
        marker = "\n... tool result truncated by ContextManager ...\n"
        remaining = self.max_tool_result_chars - len(marker)
        head = remaining // 2
        tail = remaining - head
        return text[:head] + marker + text[-tail:]

    @staticmethod
    def _interaction_blocks(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group assistant messages with all immediately following tool results."""
        blocks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "assistant":
                if current:
                    blocks.append(current)
                current = [message]
            elif current:
                current.append(message)
            else:
                blocks.append([message])
        if current:
            blocks.append(current)
        return blocks

    @staticmethod
    def _omission_summary(blocks: list[list[dict[str, Any]]]) -> dict[str, Any]:
        tool_counts: Counter[str] = Counter()
        touched_paths: set[str] = set()
        for block in blocks:
            for message in block:
                if message.get("role") != "assistant":
                    continue
                for call in message.get("tool_calls", []) or []:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    name = function.get("name")
                    if name:
                        tool_counts[name] += 1
                    raw = function.get("arguments", "{}")
                    try:
                        args = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        args = {}
                    path = args.get("path") if isinstance(args, dict) else None
                    if isinstance(path, str) and path:
                        touched_paths.add(path)

        details = {
            "omitted_interaction_blocks": len(blocks),
            "tool_counts": dict(sorted(tool_counts.items())),
            "paths_seen": sorted(touched_paths)[:40],
            "note": (
                "Older exact tool outputs were omitted to control context size. "
                "Re-read or search files when exact prior content is needed."
            ),
        }
        return {
            "role": "system",
            "content": "Context compaction summary: " + json.dumps(details, ensure_ascii=False),
        }

    def prepare(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return []
        prepared = deepcopy(messages)
        for message in prepared:
            if message.get("role") == "tool" and isinstance(message.get("content"), str):
                message["content"] = self.truncate_tool_result(message["content"])

        total = sum(self._message_chars(m) for m in prepared)
        if total <= self.max_history_chars:
            return prepared

        prefix: list[dict[str, Any]] = []
        remaining_start = 0
        for idx, message in enumerate(prepared):
            if idx < 2 and message.get("role") in {"system", "user"}:
                prefix.append(message)
                remaining_start = idx + 1
            else:
                break

        blocks = self._interaction_blocks(prepared[remaining_start:])
        prefix_cost = sum(self._message_chars(m) for m in prefix)
        kept_reversed: list[list[dict[str, Any]]] = []
        running = prefix_cost
        reserve = 3_000
        for block in reversed(blocks):
            block_cost = sum(self._message_chars(m) for m in block)
            if running + block_cost + reserve > self.max_history_chars and kept_reversed:
                break
            if running + block_cost > self.max_history_chars and not kept_reversed:
                kept_reversed.append(block)
                break
            kept_reversed.append(block)
            running += block_cost

        kept = list(reversed(kept_reversed))
        omitted_count = max(0, len(blocks) - len(kept))
        result = list(prefix)
        if omitted_count:
            result.append(self._omission_summary(blocks[:omitted_count]))
        for block in kept:
            result.extend(block)
        return result
