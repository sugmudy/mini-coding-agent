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
    GIT_BLOCKED_SUBCOMMANDS = {"commit", "push", "rebase", "cherry-pick", "clean"}
    GIT_REVIEW_SUBCOMMANDS = {
        "add",
        "branch",
        "checkout",
        "config",
        "merge",
        "mv",
        "restore",
        "rm",
        "stash",
        "switch",
        "tag",
    }
    GIT_SAFE_SUBCOMMANDS = {
        "blame",
        "describe",
        "diff",
        "grep",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    }
    GIT_OPTIONS_WITH_VALUE = {
        "-c",
        "-C",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }

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

    @classmethod
    def _git_subcommand(cls, argv: list[str]) -> tuple[str, list[str], list[str]]:
        """Return ``(subcommand, subcommand_args, global_options)``.

        Git accepts global options before its subcommand (for example ``git -C .
        status``). A policy that assumes ``argv[1]`` is always the subcommand is
        vulnerable to trivial option-prefix bypasses.
        """
        index = 1
        global_options: list[str] = []
        while index < len(argv):
            token = argv[index]
            if token == "--":
                index += 1
                break
            if not token.startswith("-") or token == "-":
                break

            global_options.append(token)
            option_name = token.split("=", 1)[0]
            consumes_next = option_name in cls.GIT_OPTIONS_WITH_VALUE and "=" not in token
            # ``-cname=value`` and ``-Cpath`` carry their values in the same token.
            if token.startswith("-c") and token != "-c":
                consumes_next = False
            if token.startswith("-C") and token != "-C":
                consumes_next = False
            if consumes_next and index + 1 < len(argv):
                global_options.append(argv[index + 1])
                index += 2
            else:
                index += 1

        if index >= len(argv):
            return "", [], global_options
        return argv[index].lower(), [item.lower() for item in argv[index + 1 :]], global_options

    @staticmethod
    def _has_flag(args: list[str], flag: str) -> bool:
        return any(item == flag or item.startswith(flag + "=") for item in args)

    @staticmethod
    def _python_module(args: list[str]) -> tuple[str, list[str]]:
        """Extract ``python -m MODULE ...`` while tolerating interpreter flags."""
        for index, item in enumerate(args):
            if item == "-m" and index + 1 < len(args):
                return args[index + 1], args[index + 2 :]
        return "", []

    def classify_command(self, command: str) -> SafetyDecision:
        argv = self._argv(command)
        if not argv:
            return SafetyDecision(RiskLevel.BLOCKED, "Command could not be parsed safely.", command)

        executable = Path(argv[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        args = [item.lower() for item in argv[1:]]

        if executable == "git":
            sub, sub_args, global_options = self._git_subcommand(argv)
            normalized_options = [item.lower() for item in global_options]
            alias_override = any(
                item.startswith("alias.")
                or item.startswith("-calias.")
                or "=alias." in item
                for item in normalized_options
            )
            blocked = (
                alias_override
                or sub in self.GIT_BLOCKED_SUBCOMMANDS
                or (sub == "reset" and self._has_flag(sub_args, "--hard"))
                or self._has_flag(sub_args, "--force")
                or self._has_flag(sub_args, "--force-with-lease")
                or (sub in {"checkout", "restore"} and ("." in sub_args or "--source" in sub_args))
            )
            if blocked:
                return SafetyDecision(
                    RiskLevel.BLOCKED,
                    "Repository-history or destructive Git operations are intentionally disabled for the agent.",
                    command,
                )
            if sub in self.GIT_SAFE_SUBCOMMANDS:
                return SafetyDecision(RiskLevel.SAFE, "Read-only or validation-oriented Git command.", command)
            if sub in self.GIT_REVIEW_SUBCOMMANDS or sub == "reset":
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"git {sub} mutates repository state and should be explicitly approved.",
                    command,
                )
            return SafetyDecision(
                RiskLevel.REVIEW,
                f"Unknown or potentially mutating git subcommand '{sub or '<missing>'}' requires approval.",
                command,
            )

        if executable in {"python", "python3", "py"}:
            module, module_args = self._python_module(args)
            pip_actions = {"install", "uninstall", "download", "wheel"}
            requested_action = next((item for item in module_args if item in pip_actions), None)
            if module == "pip" and requested_action:
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"{executable} -m pip {requested_action} changes dependencies or local files.",
                    command,
                )

        if executable in {"pip", "pip3"}:
            actions = {"install", "uninstall", "download", "wheel"}
            sub = next((item for item in args if item in actions), "")
            if sub:
                return SafetyDecision(
                    RiskLevel.REVIEW,
                    f"{executable} {sub} changes the Python environment.",
                    command,
                )

        if executable == "npx":
            return SafetyDecision(
                RiskLevel.REVIEW,
                "npx can download and execute packages and therefore requires approval.",
                command,
            )

        if executable == "npm":
            actions = {"add", "ci", "i", "install", "remove", "rm", "uninstall", "update"}
            sub = next((item for item in args if item in actions), "")
            if sub:
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
