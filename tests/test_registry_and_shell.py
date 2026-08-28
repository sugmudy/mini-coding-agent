from __future__ import annotations

import json

from tools.registry import ToolRegistry
from tools.shell_tool import ShellTool


def test_registry_exposes_v2_tools(tmp_path):
    registry = ToolRegistry(tmp_path)
    names = {schema["function"]["name"] for schema in registry.schemas}
    assert names == {"list_files", "read_file", "search_files", "write_file", "edit_file", "run_command"}


def test_registry_returns_structured_error_for_bad_json(tmp_path):
    registry = ToolRegistry(tmp_path)
    payload = json.loads(registry.execute("read_file", "{bad"))
    assert payload["ok"] is False
    assert "Invalid JSON" in payload["error"]


def test_shell_executes_allowed_command_and_captures_result(tmp_path):
    shell = ShellTool(tmp_path, timeout=5)
    result = shell.run_command('python -c "print(123)"')
    assert result["exit_code"] == 0
    assert "123" in result["stdout"]


def test_shell_rejects_unlisted_executable(tmp_path):
    shell = ShellTool(tmp_path)
    try:
        shell.run_command("echo hello")
    except Exception as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("Expected command policy rejection")
