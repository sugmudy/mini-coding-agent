from __future__ import annotations

import difflib
from pathlib import Path
from typing import Iterable

from safety import ApprovalCallback, RiskLevel, SafetyPolicy


class WorkspaceError(RuntimeError):
    """Raised when a file operation is invalid for the configured workspace."""


class FileTools:
    """Safe, deterministic file operations confined to one workspace."""

    DEFAULT_IGNORED_DIRS = {
        ".git",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
        "target",
    }
    MAX_LIST_ENTRIES = 500
    MAX_READ_CHARS = 40_000
    MAX_DIFF_CHARS = 20_000

    def __init__(
        self,
        workspace: str | Path,
        *,
        safety_policy: SafetyPolicy | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.safety_policy = safety_policy or SafetyPolicy("balanced")
        self.approval_callback = approval_callback

    def _resolve(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise WorkspaceError(f"Path escapes workspace: {relative_path}")
        return path

    def _should_ignore(self, path: Path) -> bool:
        try:
            parts = path.relative_to(self.workspace).parts
        except ValueError:
            return True
        return any(part in self.DEFAULT_IGNORED_DIRS for part in parts)

    @staticmethod
    def _line_slice(lines: list[str], start_line: int | None, end_line: int | None) -> tuple[int, int, list[str]]:
        total = len(lines)
        start = 1 if start_line is None else start_line
        end = total if end_line is None else end_line
        if start < 1:
            raise WorkspaceError("start_line must be >= 1.")
        if total == 0:
            return 1, 0, []
        if start > total:
            raise WorkspaceError(f"start_line {start} exceeds file length {total}.")
        if end < start:
            raise WorkspaceError("end_line must be >= start_line.")
        end = min(end, total)
        return start, end, lines[start - 1 : end]

    @staticmethod
    def _number_lines(lines: Iterable[str], start: int) -> str:
        numbered: list[str] = []
        for offset, line in enumerate(lines):
            numbered.append(f"{start + offset:>6} | {line.rstrip(chr(10))}")
        return "\n".join(numbered)

    def list_files(self, path: str = ".") -> dict[str, object]:
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Path does not exist: {path}")
        if not target.is_dir():
            raise WorkspaceError(f"Path is not a directory: {path}")

        entries: list[str] = []
        truncated = False
        for item in sorted(target.rglob("*"), key=lambda p: str(p).lower()):
            if self._should_ignore(item):
                continue
            relative = item.relative_to(self.workspace).as_posix()
            if not relative:
                continue
            entries.append(relative + ("/" if item.is_dir() else ""))
            if len(entries) >= self.MAX_LIST_ENTRIES:
                truncated = True
                break

        return {
            "path": target.relative_to(self.workspace).as_posix() or ".",
            "entries": entries,
            "truncated": truncated,
            "ignored_directories": sorted(self.DEFAULT_IGNORED_DIRS),
        }

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        include_line_numbers: bool = True,
    ) -> dict[str, object]:
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceError(f"File does not exist: {path}")
        if not target.is_file():
            raise WorkspaceError(f"Path is not a file: {path}")

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        start, end, selected = self._line_slice(lines, start_line, end_line)
        selected_text = "".join(selected)
        truncated = False

        if len(selected_text) > self.MAX_READ_CHARS:
            truncated = True
            selected_text = selected_text[: self.MAX_READ_CHARS]
            # Reconstruct line count after truncation so metadata remains honest.
            selected = selected_text.splitlines(keepends=True)
            end = start + max(len(selected) - 1, 0)

        display = self._number_lines(selected, start) if include_line_numbers else selected_text
        return {
            "path": target.relative_to(self.workspace).as_posix(),
            "start_line": start,
            "end_line": end,
            "total_lines": len(lines),
            "content": display,
            "truncated": truncated,
            "hint": (
                "Use start_line/end_line to read a smaller range."
                if truncated
                else None
            ),
        }

    def write_file(self, path: str, content: str) -> dict[str, object]:
        target = self._resolve(path)
        if target == self.workspace:
            raise WorkspaceError("Cannot write to the workspace directory itself.")

        existed = target.exists()
        old_content = target.read_text(encoding="utf-8", errors="replace") if existed and target.is_file() else ""
        relative = target.relative_to(self.workspace).as_posix()
        safety = self.safety_policy.classify_rewrite(relative, old_content, content)
        approved = safety.level is RiskLevel.SAFE
        if safety.level is not RiskLevel.SAFE:
            approved = self.safety_policy.authorize(safety, self.approval_callback)
            if not approved:
                raise WorkspaceError(f"SafetyPolicy denied write_file: {safety.reason}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return {
            "path": relative,
            "created": not existed,
            "characters_written": len(content),
            "diff": self._build_diff(relative, old_content, content) if existed else None,
            "safety": {
                "level": safety.level.value,
                "reason": safety.reason,
                "approved": approved,
            },
        }

    def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, object]:
        if not old_text:
            raise WorkspaceError("old_text must not be empty.")

        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceError(f"File does not exist: {path}")
        if not target.is_file():
            raise WorkspaceError(f"Path is not a file: {path}")

        content = target.read_text(encoding="utf-8", errors="replace")
        match_count = content.count(old_text)
        if match_count == 0:
            raise WorkspaceError(
                "old_text was not found exactly once. Re-read the relevant file range and provide an exact snippet."
            )
        if match_count > 1:
            raise WorkspaceError(
                f"old_text matches {match_count} locations. Provide a more specific snippet so the edit is unambiguous."
            )

        updated = content.replace(old_text, new_text, 1)
        target.write_text(updated, encoding="utf-8")
        relative = target.relative_to(self.workspace).as_posix()
        line_number = content[: content.index(old_text)].count("\n") + 1
        return {
            "path": relative,
            "match_count": 1,
            "start_line": line_number,
            "characters_removed": len(old_text),
            "characters_inserted": len(new_text),
            "diff": self._build_diff(relative, content, updated),
        }

    def _build_diff(self, relative_path: str, before: str, after: str) -> str:
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                n=3,
            )
        )
        if len(diff) <= self.MAX_DIFF_CHARS:
            return diff
        half = self.MAX_DIFF_CHARS // 2
        return diff[:half] + "\n... diff truncated ...\n" + diff[-half:]
