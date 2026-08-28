from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class RiskLevel(str, Enum):
    SAFE = "safe"
    REVIEW = "review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SafetyDecision:
    level: RiskLevel
    reason: str
    action: str


ApprovalCallback = Callable[[SafetyDecision], bool]


class SafetyPolicy:
    """Classifies potentially mutating actions before local execution.

    Modes:
    - balanced: safe actions run automatically; review actions require approval.
    - strict: review actions are rejected as well as blocked actions.
    - permissive: review actions run automatically; blocked actions stay blocked.

    Blocked actions remain blocked in every mode because the coding agent should not
    rewrite repository history, push remote changes, or perform destructive cleanup.
    """

    MODES = {"balanced", "strict", "permissive"}

    def __init__(self, mode: str = "balanced") -> None:
        normalized = mode.strip().lower()
        if normalized not in self.MODES:
            raise ValueError(f"Unknown safety mode '{mode}'. Expected one of: {', '.join(sorted(self.MODES))}.")
        self.mode = normalized

    @staticmethod
    def _argv(command: str) -> list[str]:
        try:
            return shlex.split(command)
        except ValueError:
            return []

    def classify_command(self, command: str) -> SafetyDecision:
        argv = self._argv(command)
        if not argv:
            return SafetyDecision(RiskLevel.BLOCKED, "Command could not be parsed safely.", command)

        executable = Path(argv[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        args = [item.lower() for item in argv[1:]]

        if executable == "git":
            sub = args[0] if args else ""
            joined = " ".join(args)
            blocked = (
                sub in {"commit", "push", "rebase", "cherry-pick"}
                or (sub == "reset" and "--hard" in args)
                or sub == "clean"
                or "--force" in args
                or "--force-with-lease" in args
                or (sub in {"checkout", "restore"} and ("." in args or "--source" in args))
            )
            if blocked:
                return SafetyDecision(
                    RiskLevel.BLOCKED,
                    "Repository-history or destructive Git operations are intentionally disabled for the agent.",
                    command,
                )
            if sub in {"add", "checkout", "switch", "restore", "stash", "merge"}:
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"git {sub} mutates repository state and should be explicitly approved.",
                    command,
                )
            return SafetyDecision(RiskLevel.SAFE, "Read-only or validation-oriented Git command.", command)

        if executable in {"pip", "pip3"}:
            sub = args[0] if args else ""
            if sub in {"install", "uninstall"}:
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"{executable} {sub} changes the Python environment.",
                    command,
                )

        if executable in {"npm", "npx"}:
            sub = args[0] if args else ""
            if sub in {"install", "uninstall", "update", "ci"}:
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"{executable} {sub} can modify dependencies or the local environment.",
                    command,
                )

        if executable == "cargo" and args and args[0] in {"install", "uninstall"}:
            return SafetyDecision(RiskLevel.REVIEW, "Cargo package installation mutates the environment.", command)

        if executable == "go" and args and args[0] in {"get", "install"}:
            return SafetyDecision(RiskLevel.REVIEW, "Go dependency installation mutates the environment.", command)

        return SafetyDecision(RiskLevel.SAFE, "Command is within the normal development-command policy.", command)

    @staticmethod
    def classify_rewrite(path: str, before: str, after: str) -> SafetyDecision:
        if not before:
            return SafetyDecision(RiskLevel.SAFE, "New file creation.", path)

        before_lines = max(1, len(before.splitlines()))
        after_lines = len(after.splitlines())
        before_chars = max(1, len(before))
        after_chars = len(after)
        line_ratio = after_lines / before_lines
        char_ratio = after_chars / before_chars

        if before_chars >= 2_000 and after_chars == 0:
            return SafetyDecision(
                RiskLevel.REVIEW,
                f"write_file would erase a non-trivial existing file ({before_chars} characters).",
                path,
            )
        if (before_lines >= 80 and line_ratio < 0.35) or (before_chars >= 4_000 and char_ratio < 0.35):
            return SafetyDecision(
                RiskLevel.REVIEW,
                (
                    "write_file would replace an existing file with less than 35% of its previous size "
                    f"({before_lines}->{after_lines} lines, {before_chars}->{after_chars} characters)."
                ),
                path,
            )
        return SafetyDecision(RiskLevel.SAFE, "Replacement size is not suspicious.", path)

    def authorize(self, decision: SafetyDecision, approval_callback: ApprovalCallback | None = None) -> bool:
        if decision.level is RiskLevel.SAFE:
            return True
        if decision.level is RiskLevel.BLOCKED:
            return False
        if self.mode == "permissive":
            return True
        if self.mode == "strict":
            return False
        return bool(approval_callback and approval_callback(decision))
