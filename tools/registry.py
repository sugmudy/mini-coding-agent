from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.file_tools import FileTools
from tools.shell_tool import ShellTool


ToolFunction = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    schema: dict[str, Any]
    function: ToolFunction


class ToolRegistry:
    def __init__(self, workspace: str | Path, command_timeout: int = 30) -> None:
        file_tools = FileTools(workspace)
        shell_tool = ShellTool(workspace, timeout=command_timeout)

        self._tools: dict[str, ToolSpec] = {
            "list_files": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "description": "Recursively list files and directories inside the workspace or a workspace subdirectory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Workspace-relative directory path. Use '.' for the workspace root.",
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
                        "description": "Read a UTF-8 text file from the workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Workspace-relative file path.",
                                }
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.read_file,
            ),
            "write_file": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Create or fully overwrite a UTF-8 text file inside the workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Workspace-relative file path.",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Complete file content to write.",
                                },
                            },
                            "required": ["path", "content"],
                            "additionalProperties": False,
                        },
                    },
                },
                function=file_tools.write_file,
            ),
            "run_command": ToolSpec(
                schema={
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "description": "Run an allowed development command locally with the workspace as the working directory. Returns exit code, stdout, and stderr.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Development command to execute, for example 'python main.py' or 'pytest -q'.",
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
            return json.dumps(
                {"ok": False, "error": f"Unknown tool: {name}"},
                ensure_ascii=False,
            )

        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return json.dumps(
                {"ok": False, "error": f"Invalid JSON arguments: {exc}"},
                ensure_ascii=False,
            )

        if not isinstance(arguments, dict):
            return json.dumps(
                {"ok": False, "error": "Tool arguments must decode to a JSON object."},
                ensure_ascii=False,
            )

        try:
            result = self._tools[name].function(**arguments)
            return json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
            )
        except TypeError as exc:
            return json.dumps(
                {"ok": False, "error": f"Invalid tool arguments: {exc}"},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
