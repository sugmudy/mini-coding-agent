from __future__ import annotations

import json

import pytest

from tools.registry import ToolRegistry


@pytest.mark.parametrize(
    ("allowed", "expected"),
    [
        (
            {"list_files", "read_file", "search_files"},
            {"list_files", "read_file", "search_files"},
        ),
        (
            {"list_files", "read_file", "search_files", "run_command"},
            {"list_files", "read_file", "search_files", "run_command"},
        ),
    ],
)
def test_registry_exposes_only_allowed_role_tools(tmp_path, allowed, expected):
    registry = ToolRegistry(tmp_path, allowed_tools=allowed)
    assert registry.tool_names == expected


def test_read_only_role_cannot_dispatch_invented_write_call(tmp_path):
    registry = ToolRegistry(
        tmp_path,
        allowed_tools={"list_files", "read_file", "search_files"},
    )
    result = json.loads(
        registry.execute("write_file", json.dumps({"path": "forbidden.txt", "content": "x"}))
    )
    assert result["ok"] is False
    assert "Unknown tool" in result["error"]
    assert not (tmp_path / "forbidden.txt").exists()


def test_unknown_allowed_tool_is_configuration_error(tmp_path):
    with pytest.raises(ValueError, match="Unknown allowed tool"):
        ToolRegistry(tmp_path, allowed_tools={"read_file", "invented_tool"})
