from __future__ import annotations

import json

import pytest

from tools.file_tools import FileTools, WorkspaceError
from tools.registry import ToolRegistry
from tools.shell_tool import ShellTool

def test_read_file_supports_line_ranges_and_numbers(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "sample.py").write_text("a\nb\nc\nd\n", encoding="utf-8")
    result = tools.read_file("sample.py", start_line=2, end_line=3)
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 4
    assert "2 | b" in result["content"]
    assert "3 | c" in result["content"]
    assert "1 | a" not in result["content"]


def test_read_file_rejects_invalid_ranges(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "a.txt").write_text("x\ny\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="start_line"):
        tools.read_file("a.txt", start_line=0)
    with pytest.raises(WorkspaceError, match="end_line"):
        tools.read_file("a.txt", start_line=2, end_line=1)
    with pytest.raises(WorkspaceError, match="exceeds"):
        tools.read_file("a.txt", start_line=5)


def test_workspace_escape_is_blocked(tmp_path):
    tools = FileTools(tmp_path)
    with pytest.raises(WorkspaceError, match="escapes workspace"):
        tools.read_file("../outside.txt")


def test_list_files_ignores_generated_directories(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "secret.py").write_text("ignored", encoding="utf-8")
    result = tools.list_files(".")
    assert "src/main.py" in result["entries"]
    assert not any(".venv" in item for item in result["entries"])


def test_edit_file_requires_unique_exact_match_and_returns_diff(tmp_path):
    tools = FileTools(tmp_path)
    path = tmp_path / "calc.py"
    path.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    result = tools.edit_file("calc.py", "return a - b", "return a + b")
    assert path.read_text(encoding="utf-8").endswith("return a + b\n")
    assert result["match_count"] == 1
    assert "-    return a - b" in result["diff"]
    assert "+    return a + b" in result["diff"]


def test_edit_file_refuses_ambiguous_match(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "x.py").write_text("return None\nreturn None\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="matches 2 locations"):
        tools.edit_file("x.py", "return None", "return 1")


def test_edit_file_refuses_missing_match(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "x.py").write_text("return 1\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not found"):
        tools.edit_file("x.py", "return 2", "return 3")


def test_write_file_reports_diff_when_replacing_existing_file(tmp_path):
    tools = FileTools(tmp_path)
    (tmp_path / "x.txt").write_text("old\n", encoding="utf-8")
    result = tools.write_file("x.txt", "new\n")
    assert result["created"] is False
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]

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

