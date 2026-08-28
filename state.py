from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    step: int = 0
    tool_counts: Counter[str] = field(default_factory=Counter)
    changed_files: set[str] = field(default_factory=set)
    commands_run: list[str] = field(default_factory=list)
    llm_calls: int = 0
    api_retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_duration_ms: float = 0.0
    tool_duration_ms: float = 0.0
    context_compactions: int = 0
    safety_blocks: int = 0
    safety_approvals: int = 0
    validation_nudges: int = 0
    _started_at: float = field(default_factory=time.perf_counter, repr=False)
    _finished_at: float | None = field(default=None, repr=False)

    def observe_llm(self, *, duration_ms: float, usage: dict[str, Any] | None = None, retries: int = 0) -> None:
        self.llm_calls += 1
        self.llm_duration_ms += max(0.0, duration_ms)
        self.api_retries += max(0, retries)
        usage = usage or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = usage.get("total_tokens")
        if total is None:
            total = (usage.get("prompt_tokens") or usage.get("input_tokens") or 0) + (
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
        self.total_tokens += int(total or 0)

    def observe_tool(
        self,
        name: str,
        raw_arguments: str,
        tool_result: str,
        *,
        duration_ms: float = 0.0,
    ) -> None:
        self.tool_counts[name] += 1
        self.tool_duration_ms += max(0.0, duration_ms)
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result_payload = json.loads(tool_result)
        except json.JSONDecodeError:
            result_payload = {"ok": False}

        succeeded = bool(result_payload.get("ok"))
        if succeeded and name in {"write_file", "edit_file"}:
            path = args.get("path") if isinstance(args, dict) else None
            if isinstance(path, str):
                self.changed_files.add(path)
        if name == "run_command":
            command = args.get("command") if isinstance(args, dict) else None
            if isinstance(command, str):
                self.commands_run.append(command)

    def mark_context_compaction(self) -> None:
        self.context_compactions += 1

    def mark_safety_block(self) -> None:
        self.safety_blocks += 1

    def mark_safety_approval(self) -> None:
        self.safety_approvals += 1

    def finish(self) -> None:
        if self._finished_at is None:
            self._finished_at = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        end = self._finished_at if self._finished_at is not None else time.perf_counter()
        return max(0.0, (end - self._started_at) * 1000)


    def estimated_cost_usd(
        self,
        input_price_per_million: float | None,
        output_price_per_million: float | None,
    ) -> float | None:
        if input_price_per_million is None or output_price_per_million is None:
            return None
        return (
            self.prompt_tokens * input_price_per_million
            + self.completion_tokens * output_price_per_million
        ) / 1_000_000

    def _last_validation(self) -> str | None:
        if not self.commands_run:
            return None
        return self.commands_run[-1]

    def summary(self) -> dict[str, object]:
        return {
            "step": self.step,
            "tool_counts": dict(self.tool_counts),
            "tool_calls": sum(self.tool_counts.values()),
            "changed_files": sorted(self.changed_files),
            "commands_run": self.commands_run[-20:],
            "last_validation": self._last_validation(),
            "llm_calls": self.llm_calls,
            "api_retries": self.api_retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_duration_ms": round(self.llm_duration_ms, 2),
            "tool_duration_ms": round(self.tool_duration_ms, 2),
            "duration_ms": round(self.duration_ms, 2),
            "context_compactions": self.context_compactions,
            "safety_blocks": self.safety_blocks,
            "safety_approvals": self.safety_approvals,
            "validation_nudges": self.validation_nudges,
        }
