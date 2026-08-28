from __future__ import annotations

import pytest

from tools.file_tools import WorkspaceError
from tools.search_tool import SearchTool


def build_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def calculate_total(items):\n    return sum(items)\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from src.calc import calculate_total\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("CALCULATE_TOTAL docs\n", encoding="utf-8")


def test_literal_search_returns_paths_lines_and_text(tmp_path):
    build_project(tmp_path)
    search = SearchTool(tmp_path)
    result = search.search_files("calculate_total", file_glob="*.py")
    assert result["match_count"] == 2
    assert {m["path"] for m in result["matches"]} == {"src/calc.py", "tests/test_calc.py"}
    assert all(isinstance(m["line"], int) for m in result["matches"])


def test_search_supports_case_sensitive_and_regex(tmp_path):
    build_project(tmp_path)
    search = SearchTool(tmp_path)
    insensitive = search.search_files("calculate_total")
    assert insensitive["match_count"] == 3
    sensitive = search.search_files("calculate_total", case_sensitive=True)
    assert sensitive["match_count"] == 2
    regex = search.search_files(r"def\s+calculate_\w+", regex=True, file_glob="*.py")
    assert regex["match_count"] == 1
    assert regex["matches"][0]["path"] == "src/calc.py"


def test_search_respects_path_scope(tmp_path):
    build_project(tmp_path)
    search = SearchTool(tmp_path)
    result = search.search_files("calculate_total", path="tests")
    assert result["match_count"] == 1
    assert result["matches"][0]["path"] == "tests/test_calc.py"


def test_search_rejects_unbounded_result_limit(tmp_path):
    search = SearchTool(tmp_path)
    with pytest.raises(WorkspaceError, match="max_results"):
        search.search_files("x", max_results=1000)
