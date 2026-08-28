from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from tools.file_tools import FileTools, WorkspaceError


class SearchTool:
    """Cross-platform workspace text search with bounded output."""

    DEFAULT_GLOB = "*"
    MAX_RESULTS = 80
    MAX_FILE_BYTES = 2_000_000

    def __init__(self, workspace: str | Path) -> None:
        self.file_tools = FileTools(workspace)
        self.workspace = self.file_tools.workspace

    @staticmethod
    def _looks_binary(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                chunk = handle.read(4096)
        except OSError:
            return True
        return b"\x00" in chunk

    def search_files(
        self,
        query: str,
        path: str = ".",
        file_glob: str = "*",
        case_sensitive: bool = False,
        regex: bool = False,
        max_results: int = 50,
    ) -> dict[str, object]:
        if not query:
            raise WorkspaceError("query must not be empty.")
        if max_results < 1 or max_results > self.MAX_RESULTS:
            raise WorkspaceError(f"max_results must be between 1 and {self.MAX_RESULTS}.")

        root = self.file_tools._resolve(path)
        if not root.exists():
            raise WorkspaceError(f"Path does not exist: {path}")
        if not root.is_dir():
            raise WorkspaceError(f"Path is not a directory: {path}")

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query if regex else re.escape(query), flags)
        matches: list[dict[str, object]] = []
        scanned_files = 0
        skipped_files = 0
        truncated = False

        for candidate in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
            if not candidate.is_file() or self.file_tools._should_ignore(candidate):
                continue
            relative = candidate.relative_to(self.workspace).as_posix()
            if not fnmatch.fnmatch(candidate.name, file_glob) and not fnmatch.fnmatch(relative, file_glob):
                continue
            try:
                if candidate.stat().st_size > self.MAX_FILE_BYTES or self._looks_binary(candidate):
                    skipped_files += 1
                    continue
                lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                skipped_files += 1
                continue

            scanned_files += 1
            for line_no, line in enumerate(lines, start=1):
                if pattern.search(line):
                    matches.append(
                        {
                            "path": relative,
                            "line": line_no,
                            "text": line.strip()[:500],
                        }
                    )
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if truncated:
                break

        return {
            "query": query,
            "path": path,
            "file_glob": file_glob,
            "regex": regex,
            "case_sensitive": case_sensitive,
            "matches": matches,
            "match_count": len(matches),
            "scanned_files": scanned_files,
            "skipped_files": skipped_files,
            "truncated": truncated,
            "hint": "Refine query/path/file_glob if results were truncated." if truncated else None,
        }
