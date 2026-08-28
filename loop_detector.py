from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSignature:
    generation: int
    name: str
    arguments: str


class LoopDetector:
    """Detects repeated tool behavior without blocking legitimate post-edit rechecks."""

    STATE_CHANGING_TOOLS = {"write_file", "edit_file"}

    def __init__(self, *, repeat_limit: int = 3, history_size: int = 18) -> None:
        if repeat_limit < 2:
            raise ValueError("repeat_limit must be >= 2.")
        self.repeat_limit = repeat_limit
        self._history: deque[ToolSignature] = deque(maxlen=history_size)
        self._generation = 0

    @staticmethod
    def _normalize_arguments(raw_arguments: str) -> str:
        try:
            value = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return raw_arguments.strip()
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def check(self, name: str, raw_arguments: str) -> str | None:
        signature = ToolSignature(
            generation=self._generation,
            name=name,
            arguments=self._normalize_arguments(raw_arguments),
        )
        same_generation = [item for item in self._history if item.generation == self._generation]

        if len(same_generation) >= self.repeat_limit - 1:
            tail = same_generation[-(self.repeat_limit - 1) :]
            if all(item.name == signature.name and item.arguments == signature.arguments for item in tail):
                return (
                    f"Repeated tool call blocked: {name} with identical arguments has already been "
                    f"attempted {self.repeat_limit - 1} consecutive times without a code change. "
                    "Use existing observations, refine the arguments, or take a different action."
                )

        candidate = same_generation + [signature]
        for period in (2, 3):
            needed = period * 3
            if len(candidate) < needed:
                continue
            tail = candidate[-needed:]
            pattern = tail[:period]
            if all(tail[i] == pattern[i % period] for i in range(needed)):
                names = " -> ".join(item.name for item in pattern)
                return (
                    f"Repeated tool cycle blocked: detected '{names}' repeated three times without a code change. "
                    "Reassess the evidence or make progress with a different action."
                )
        return None

    def record(self, name: str, raw_arguments: str, *, succeeded: bool) -> None:
        self._history.append(
            ToolSignature(
                generation=self._generation,
                name=name,
                arguments=self._normalize_arguments(raw_arguments),
            )
        )
        if succeeded and name in self.STATE_CHANGING_TOOLS:
            self._generation += 1
