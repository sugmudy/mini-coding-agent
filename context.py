from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from typing import Any


class ContextManager:
    """Build a bounded model view without mutating the full multi-turn audit history."""

    SUMMARY_RESERVE_CHARS = 3_000

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
        self.last_prepare_compacted = False
        self.last_omitted_blocks = 0
        self.last_omitted_turns = 0

    @staticmethod
    def _message_chars(message: dict[str, Any]) -> int:
        return len(json.dumps(message, ensure_ascii=False, default=str))

    @staticmethod
    def _public_message(message: dict[str, Any]) -> dict[str, Any]:
        """Remove runtime-only metadata before sending messages to the provider."""
        return {key: value for key, value in message.items() if not str(key).startswith("_")}

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
        """Group each assistant message with its immediately following tool results."""
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
    def _split_session(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        """Split leading session messages from contiguous user turns.

        Agent-generated messages carry ``_turn_id``. Histories created by tests or
        third-party callers are supported by inferring a turn at each user message.
        """
        prefix: list[dict[str, Any]] = []
        turns: list[list[dict[str, Any]]] = []
        current_id: object | None = None
        inferred_id = 0
        has_explicit_turns = any(message.get("_turn_id") is not None for message in messages)
        for message in messages:
            explicit_id = message.get("_turn_id")
            if explicit_id is None and not turns and message.get("role") == "system":
                prefix.append(message)
                continue
            # Preserve the V2/V3 contract for untagged histories: the original
            # user task is a stable prefix. Agent-produced V4 histories use the
            # explicit branch below so all real user requests remain turn-aware.
            if (
                not has_explicit_turns
                and explicit_id is None
                and not turns
                and message.get("role") == "user"
            ):
                prefix.append(message)
                current_id = "legacy-body"
                continue
            if explicit_id is None and message.get("role") == "user":
                inferred_id += 1
                explicit_id = f"inferred-{inferred_id}"
            elif explicit_id is None:
                explicit_id = current_id if current_id is not None else f"inferred-{inferred_id or 1}"
            if not turns or explicit_id != current_id:
                turns.append([])
                current_id = explicit_id
            turns[-1].append(message)
        return prefix, turns

    @staticmethod
    def _omission_summary(
        blocks: list[list[dict[str, Any]]],
        *,
        omitted_turns: int,
    ) -> dict[str, Any]:
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
            "omitted_turns": omitted_turns,
            "omitted_interaction_blocks": len(blocks),
            "tool_counts": dict(sorted(tool_counts.items())),
            "paths_seen": sorted(touched_paths)[:40],
            "note": (
                "Older exact conversation/tool content was omitted to control context size. "
                "Re-read or search files when exact prior content is needed."
            ),
        }
        return {
            "role": "system",
            "content": "Context compaction summary: " + json.dumps(details, ensure_ascii=False),
        }

    def _compact_single_turn(
        self,
        turn: list[dict[str, Any]],
        available_chars: int,
    ) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        first_assistant = next(
            (index for index, message in enumerate(turn) if message.get("role") == "assistant"),
            len(turn),
        )
        anchor = turn[:first_assistant]
        blocks = self._interaction_blocks(turn[first_assistant:])
        running = sum(self._message_chars(message) for message in anchor)
        kept_reversed: list[list[dict[str, Any]]] = []
        for block in reversed(blocks):
            block_cost = sum(self._message_chars(message) for message in block)
            if kept_reversed and running + block_cost > available_chars:
                break
            kept_reversed.append(block)
            running += block_cost
            if running > available_chars:
                break
        kept_blocks = list(reversed(kept_reversed))
        kept = list(anchor)
        for block in kept_blocks:
            kept.extend(block)
        omitted = blocks[: max(0, len(blocks) - len(kept_blocks))]
        return kept, omitted

    def prepare(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_prepare_compacted = False
        self.last_omitted_blocks = 0
        self.last_omitted_turns = 0
        if not messages:
            return []

        internal = deepcopy(messages)
        for message in internal:
            if message.get("role") == "tool" and isinstance(message.get("content"), str):
                message["content"] = self.truncate_tool_result(message["content"])

        prefix_internal, turns_internal = self._split_session(internal)
        prefix = [self._public_message(message) for message in prefix_internal]
        turns = [[self._public_message(message) for message in turn] for turn in turns_internal]
        prepared = prefix + [message for turn in turns for message in turn]
        if sum(self._message_chars(message) for message in prepared) <= self.max_history_chars:
            return prepared

        prefix_cost = sum(self._message_chars(message) for message in prefix)
        kept_reversed: list[list[dict[str, Any]]] = []
        omitted_turns: list[list[dict[str, Any]]] = []
        omitted_blocks: list[list[dict[str, Any]]] = []
        running = prefix_cost
        budget_with_summary = max(0, self.max_history_chars - self.SUMMARY_RESERVE_CHARS)

        for index in range(len(turns) - 1, -1, -1):
            turn = turns[index]
            turn_cost = sum(self._message_chars(message) for message in turn)
            if running + turn_cost <= budget_with_summary:
                kept_reversed.append(turn)
                running += turn_cost
                continue
            if not kept_reversed:
                compacted, dropped = self._compact_single_turn(turn, budget_with_summary - running)
                kept_reversed.append(compacted)
                omitted_blocks.extend(dropped)
                omitted_turns.extend(turns[:index])
            else:
                omitted_turns.extend(turns[: index + 1])
            break

        for turn in omitted_turns:
            omitted_blocks.extend(self._interaction_blocks(turn))

        kept = list(reversed(kept_reversed))
        self.last_prepare_compacted = bool(omitted_blocks)
        self.last_omitted_blocks = len(omitted_blocks)
        self.last_omitted_turns = len(omitted_turns)
        result = list(prefix)
        if omitted_blocks:
            result.append(self._omission_summary(omitted_blocks, omitted_turns=len(omitted_turns)))
        for turn in kept:
            result.extend(turn)
        return result
