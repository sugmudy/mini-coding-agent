from __future__ import annotations

import json

from tools.file_tools import FileTools, WorkspaceError
from tools.registry import ToolRegistry
from tools.shell_tool import ShellTool


def test_file_tools_round_trip(tmp_path):
    tools = FileTools(tmp_path)
    message = tools.write_file("src/example.py", "print('ok')\n")
    assert "src/example.py" in message
    assert tools.read_file("src/example.py") == "print('ok')\n"
    listing = tools.list_files(".")
    assert "src/" in listing
    assert "src/example.py" in listing


def test_file_tools_block_workspace_escape(tmp_path):
    tools = FileTools(tmp_path)
    try:
        tools.read_file("../outside.txt")
    except WorkspaceError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("Expected WorkspaceError")


def test_registry_handles_bad_json(tmp_path):
    registry = ToolRegistry(tmp_path)
    payload = json.loads(registry.execute("read_file", "{bad"))
    assert payload["ok"] is False
    assert "Invalid JSON" in payload["error"]


def test_run_command_returns_exit_code(tmp_path):
    shell = ShellTool(tmp_path, timeout=5)
    result = shell.run_command('python -c "print(123)"')
    assert result["exit_code"] == 0
    assert "123" in result["stdout"]
