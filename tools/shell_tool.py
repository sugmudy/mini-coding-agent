from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path


class CommandPolicyError(RuntimeError):
    """Raised when a command is outside the V1 development-command policy."""


class ShellTool:
    MAX_OUTPUT_CHARS = 30_000
    ALLOWED_EXECUTABLES = {
        "python", "python3", "py", "pytest", "pip", "pip3", "git", "node", "npm", "npx",
        "java", "javac", "gcc", "g++", "clang", "clang++", "cmake", "make", "cargo", "go",
    }

    def __init__(self, workspace: str | Path, timeout: int = 30) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    def _trim(self, text: str) -> str:
        if len(text) <= self.MAX_OUTPUT_CHARS:
            return text
        head = self.MAX_OUTPUT_CHARS // 2
        tail = self.MAX_OUTPUT_CHARS - head
        return text[:head] + "\n... command output truncated ...\n" + text[-tail:]

    def _parse(self, command: str) -> list[str]:
        if not command.strip():
            raise CommandPolicyError("Command cannot be empty.")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise CommandPolicyError(f"Cannot parse command: {exc}") from exc
        if not argv:
            raise CommandPolicyError("Command cannot be empty.")

        executable = Path(argv[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable not in self.ALLOWED_EXECUTABLES:
            allowed = ", ".join(sorted(self.ALLOWED_EXECUTABLES))
            raise CommandPolicyError(
                f"Executable '{argv[0]}' is not allowed in V1. Allowed: {allowed}"
            )
        return argv

    def run_command(self, command: str) -> str:
        argv = self._parse(command)
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
            payload = {
                "command": command,
                "exit_code": completed.returncode,
                "stdout": self._trim(completed.stdout),
                "stderr": self._trim(completed.stderr),
            }
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            payload = {
                "command": command,
                "exit_code": None,
                "stdout": self._trim(stdout),
                "stderr": self._trim(stderr),
                "error": f"Command timed out after {self.timeout} seconds.",
            }
        except OSError as exc:
            payload = {
                "command": command,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "error": f"Failed to start command: {exc}",
            }

        return json.dumps(payload, ensure_ascii=False, indent=2)
