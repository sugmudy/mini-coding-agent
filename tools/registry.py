from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from safety import ApprovalCallback, SafetyPolicy

from tools.file_tools import FileTools
from tools.search_tool import SearchTool
from tools.shell_tool import ShellTool


ToolFunction = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    schema: dict[str, Any]
    function: ToolFunction


class ToolRegistry:
    """Owns the model-visible schemas and the local function dispatcher."""

    def __init__(
        self,
        workspace: str | Path,
        command_timeout: int = 30,
        *,
        safety_policy: SafetyPolicy | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        policy = safety_policy or SafetyPolicy("balanced")
        file_tools = FileTools(workspace, safety_policy=policy, approval_callback=approval_callback)
        search_tool = SearchTool(workspace)
        shell_tool = ShellTool(
            workspace,
            timeout=command_timeout,
            safety_policy=policy,
            approval_callback=approval_callback,
        )
        self.safety_policy = policy

        self._tools: dict[str, ToolSpec] = {
            "list_files": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "description": (
                            "Recursively list relevant files/directories inside the workspace. Common generated and "
                            "dependency directories are ignored."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Workspace-relative directory path; use '.' for workspace root.",
                                    "default": ".",
                                }
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.list_files,
            ),
            "read_file": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": (
                            "Read a UTF-8 text file, optionally only a 1-based inclusive line range. Returns line "
                            "numbers by default. Prefer ranges for large files."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."},
                                "start_line": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "Optional first line (1-based, inclusive).",
                                },
                                "end_line": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "Optional last line (1-based, inclusive).",
                                },
                                "include_line_numbers": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": "Include stable display line numbers in returned content.",
                                },
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.read_file,
            ),
            "search_files": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "search_files",
                        "description": (
                            "Search text across workspace files without relying on OS grep. Supports literal or regex "
                            "queries, path scoping and filename globs."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Literal text or regex to search for."},
                                "path": {"type": "string", "default": "."},
                                "file_glob": {
                                    "type": "string",
                                    "default": "*",
                                    "description": "Filename/path glob such as '*.py' or 'src/*.cpp'.",
                                },
                                "case_sensitive": {"type": "boolean", "default": False},
                                "regex": {"type": "boolean", "default": False},
                                "max_results": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 80,
                                    "default": 50,
                                },
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=search_tool.search_files,
            ),
            "write_file": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": (
                            "Create a new text file or fully replace an existing one. For localized edits to an "
                            "existing file, prefer edit_file."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."},
                                "content": {"type": "string", "description": "Complete intended file content."},
                            },
                            "required": ["path", "content"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.write_file,
            ),
            "edit_file": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "edit_file",
                        "description": (
                            "Precisely replace one exact, unique text snippet in an existing file. The edit is refused "
                            "if old_text is missing or ambiguous, and a unified diff is returned on success."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Workspace-relative file path."},
                                "old_text": {
                                    "type": "string",
                                    "description": "Exact existing snippet. Include enough surrounding context to be unique.",
                                },
                                "new_text": {"type": "string", "description": "Replacement snippet."},
                            },
                            "required": ["path", "old_text", "new_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.edit_file,
            ),
            "run_command": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "description": (
                            "Run an allowed development command locally with the workspace as cwd. Returns exit code, "
                            "stdout and stderr. Use this to validate changes."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "For example 'pytest -q' or 'python main.py'.",
                                }
                            },
                            "required": ["command"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=shell_tool.run_command,
            ),
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [spec.schema for spec in self._tools.values()]

    def execute(self, name: str, raw_arguments: str) -> str:
        if name not in self._tools:
            return json.dumps({"ok": False, "error": f"Unknown tool: {name}"}, ensure_ascii=False)

        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"ok": False, "error": f"Invalid JSON arguments: {exc}"}, ensure_ascii=False)

        if not isinstance(arguments, dict):
            return json.dumps(
                {"ok": False, "error": "Tool arguments must decode to a JSON object."},
                ensure_ascii=False,
            )

        try:
            result = self._tools[name].function(**arguments)
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
        except TypeError as exc:
            return json.dumps({"ok": False, "error": f"Invalid tool arguments: {exc}"}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
