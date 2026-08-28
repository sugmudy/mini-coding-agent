from __future__ import annotations

from pathlib import Path


class WorkspaceError(RuntimeError):
    """Raised when a file operation is invalid for the configured workspace."""


class FileTools:
    MAX_READ_CHARS = 100_000
    MAX_LIST_ENTRIES = 500

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise WorkspaceError(f"Path escapes workspace: {relative_path}")
        return path

    def list_files(self, path: str = ".") -> str:
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Path does not exist: {path}")
        if not target.is_dir():
            raise WorkspaceError(f"Path is not a directory: {path}")

        entries: list[str] = []
        for item in sorted(target.rglob("*"), key=lambda p: str(p).lower()):
            relative = item.relative_to(self.workspace).as_posix()
            if not relative:
                continue
            entries.append(relative + ("/" if item.is_dir() else ""))
            if len(entries) >= self.MAX_LIST_ENTRIES:
                entries.append(
                    f"... output truncated after {self.MAX_LIST_ENTRIES} entries ..."
                )
                break

        return "\n".join(entries) if entries else "(workspace is empty)"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceError(f"File does not exist: {path}")
        if not target.is_file():
            raise WorkspaceError(f"Path is not a file: {path}")

        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > self.MAX_READ_CHARS:
            return (
                content[: self.MAX_READ_CHARS]
                + f"\n... file truncated after {self.MAX_READ_CHARS} characters ..."
            )
        return content

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        if target == self.workspace:
            raise WorkspaceError("Cannot write to the workspace directory itself.")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        relative = target.relative_to(self.workspace).as_posix()
        return f"Wrote {len(content)} characters to {relative}."
