from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class AgentState:
    step: int = 0
    tool_counts: Counter[str] = field(default_factory=Counter)
    changed_files: set[str] = field(default_factory=set)
    commands_run: list[str] = field(default_factory=list)

    def observe_tool(self, name: str, raw_arguments: str, tool_result: str) -> None:
        self.tool_counts[name] += 1
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

    def summary(self) -> dict[str, object]:
        return {
            "step": self.step,
            "tool_counts": dict(self.tool_counts),
            "changed_files": sorted(self.changed_files),
            "commands_run": self.commands_run[-20:],
        }
