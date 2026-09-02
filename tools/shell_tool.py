from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from safety import ApprovalCallback, RiskLevel, SafetyPolicy


class CommandPolicyError(RuntimeError):
    """Raised when a command is outside the development-command or safety policy."""


class ShellTool:
    MAX_OUTPUT_CHARS = 30_000
    ALLOWED_EXECUTABLES = {
        "python", "python3", "py", "pytest", "pip", "pip3", "git", "node", "npm", "npx",
        "java", "javac", "gcc", "g++", "clang", "clang++", "cmake", "make", "cargo", "go",
    }
    SHELL_OPERATORS = {"|", "||", "&&", ";", "&", "<", ">", "2>", "2>>"}

    def __init__(
        self,
        workspace: str | Path,
        timeout: int = 30,
        *,
        safety_policy: SafetyPolicy | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.safety_policy = safety_policy or SafetyPolicy("balanced")
        self.approval_callback = approval_callback

    def _trim(self, text: str) -> str:
        if len(text) <= self.MAX_OUTPUT_CHARS:
            return text
        marker = "\n... command output truncated ...\n"
        remaining = self.MAX_OUTPUT_CHARS - len(marker)
        head = remaining // 2
        tail = remaining - head
        return text[:head] + marker + text[-tail:]

    def _parse(self, command: str) -> list[str]:
        if not command.strip():
            raise CommandPolicyError("Command cannot be empty.")
        if "\n" in command or "\r" in command:
            raise CommandPolicyError(
                "Multi-line commands and heredocs are not supported because commands run with shell=False. "
                "Use one direct cross-platform command such as python -c instead."
            )
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise CommandPolicyError(f"Cannot parse command: {exc}") from exc
        if not argv:
            raise CommandPolicyError("Command cannot be empty.")
        unsupported = next(
            (
                item
                for item in argv
                if item in self.SHELL_OPERATORS
                or item.startswith(("<<", ">>"))
                or "&&" in item
                or "||" in item
            ),
            None,
        )
        if unsupported is not None:
            raise CommandPolicyError(
                f"Shell operator '{unsupported}' is not supported because commands run with shell=False. "
                "Run one allowed executable at a time."
            )

        executable = Path(argv[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable not in self.ALLOWED_EXECUTABLES:
            allowed = ", ".join(sorted(self.ALLOWED_EXECUTABLES))
            raise CommandPolicyError(
                f"Executable '{argv[0]}' is not allowed. Allowed development executables: {allowed}"
            )
        return argv

    def _authorize(self, command: str) -> dict[str, object]:
        decision = self.safety_policy.classify_command(command)
        approved = self.safety_policy.authorize(decision, self.approval_callback)
        if not approved:
            raise CommandPolicyError(
                f"SafetyPolicy denied command ({decision.level.value}): {decision.reason}"
            )
        return {
            "level": decision.level.value,
            "reason": decision.reason,
            "approved": approved,
        }

    def run_command(self, command: str) -> dict[str, object]:
        argv = self._parse(command)
        safety = self._authorize(command)
        try:
            completed = subprocess.run(
                argv,
                cwd=self.workspace,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
            return {
                "command": command,
                "exit_code": completed.returncode,
                "stdout": self._trim(completed.stdout),
                "stderr": self._trim(completed.stderr),
                "safety": safety,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return {
                "command": command,
                "exit_code": None,
                "stdout": self._trim(stdout),
                "stderr": self._trim(stderr),
                "error": f"Command timed out after {self.timeout} seconds.",
                "safety": safety,
            }
        except OSError as exc:
            return {
                "command": command,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "error": f"Failed to start command: {exc}",
                "safety": safety,
            }
