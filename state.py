from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnState:
    """Runtime facts for one user request inside a longer agent session."""

    turn_id: int
    user_input: str
    step: int = 0
    status: str = "running"
    final_text: str = ""
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

    def finish(self, *, status: str = "complete", final_text: str = "") -> None:
        self.status = status
        self.final_text = final_text
        if self._finished_at is None:
            self._finished_at = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        end = self._finished_at if self._finished_at is not None else time.perf_counter()
        return max(0.0, (end - self._started_at) * 1000)

    def summary(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "status": self.status,
            "step": self.step,
            "tool_counts": dict(self.tool_counts),
            "tool_calls": sum(self.tool_counts.values()),
            "changed_files": sorted(self.changed_files),
            "commands_run": self.commands_run[-20:],
            "last_validation": self.commands_run[-1] if self.commands_run else None,
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


@dataclass
class AgentState:
    """Session-wide runtime facts, with an explicit current-turn boundary."""

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
    turns: list[TurnState] = field(default_factory=list)
    current_turn: TurnState | None = field(default=None, repr=False)
    _started_at: float = field(default_factory=time.perf_counter, repr=False)
    _finished_at: float | None = field(default=None, repr=False)

    def begin_turn(self, user_input: str) -> TurnState:
        if self.current_turn is not None and self.current_turn.status == "running":
            raise RuntimeError("Cannot start a new turn while another turn is running.")
        turn = TurnState(turn_id=len(self.turns) + 1, user_input=user_input)
        self.turns.append(turn)
        self.current_turn = turn
        self.step = 0
        return turn

    def set_step(self, step: int) -> None:
        self.step = step
        if self.current_turn is not None:
            self.current_turn.step = step

    @staticmethod
    def _usage_counts(usage: dict[str, Any] | None) -> tuple[int, int, int]:
        usage = usage or {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_value = usage.get("total_tokens")
        total = int(total_value if total_value is not None else prompt + completion)
        return prompt, completion, total

    def observe_llm(self, *, duration_ms: float, usage: dict[str, Any] | None = None, retries: int = 0) -> None:
        duration_ms = max(0.0, duration_ms)
        retries = max(0, retries)
        prompt, completion, total = self._usage_counts(usage)
        for target in (self, self.current_turn):
            if target is None:
                continue
            target.llm_calls += 1
            target.llm_duration_ms += duration_ms
            target.api_retries += retries
            target.prompt_tokens += prompt
            target.completion_tokens += completion
            target.total_tokens += total

    def observe_tool(
        self,
        name: str,
        raw_arguments: str,
        tool_result: str,
        *,
        duration_ms: float = 0.0,
    ) -> None:
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result_payload = json.loads(tool_result)
        except json.JSONDecodeError:
            result_payload = {"ok": False}

        succeeded = bool(result_payload.get("ok"))
        result = result_payload.get("result")
        command_succeeded = (
            succeeded
            and isinstance(result, dict)
            and result.get("exit_code") == 0
            and not result.get("error")
        )
        path = args.get("path") if isinstance(args, dict) else None
        command = args.get("command") if isinstance(args, dict) else None
        duration_ms = max(0.0, duration_ms)
        for target in (self, self.current_turn):
            if target is None:
                continue
            target.tool_counts[name] += 1
            target.tool_duration_ms += duration_ms
            if succeeded and name in {"write_file", "edit_file"} and isinstance(path, str):
                target.changed_files.add(path)
            if command_succeeded and name == "run_command" and isinstance(command, str):
                target.commands_run.append(command)

    def mark_context_compaction(self) -> None:
        self.context_compactions += 1
        if self.current_turn is not None:
            self.current_turn.context_compactions += 1

    def mark_safety_block(self) -> None:
        self.safety_blocks += 1
        if self.current_turn is not None:
            self.current_turn.safety_blocks += 1

    def mark_safety_approval(self) -> None:
        self.safety_approvals += 1
        if self.current_turn is not None:
            self.current_turn.safety_approvals += 1

    def mark_validation_nudge(self) -> None:
        self.validation_nudges += 1
        if self.current_turn is not None:
            self.current_turn.validation_nudges += 1

    def finish_turn(self, *, status: str = "complete", final_text: str = "") -> TurnState:
        if self.current_turn is None:
            raise RuntimeError("No active turn to finish.")
        self.current_turn.finish(status=status, final_text=final_text)
        return self.current_turn

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

    def summary(self) -> dict[str, object]:
        completed_turns = [turn for turn in self.turns if turn.status != "running"]
        return {
            "step": self.step,
            "turn_count": len(self.turns),
            "completed_turns": len(completed_turns),
            "tool_counts": dict(self.tool_counts),
            "tool_calls": sum(self.tool_counts.values()),
            "changed_files": sorted(self.changed_files),
            "commands_run": self.commands_run[-20:],
            "last_validation": self.commands_run[-1] if self.commands_run else None,
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
