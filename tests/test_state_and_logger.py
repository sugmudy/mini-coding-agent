from __future__ import annotations

import json

from session_logger import SessionLogger
from state import AgentState


def test_state_tracks_changes_commands_and_counts():
    state = AgentState()
    state.observe_tool(
        "edit_file",
        '{"path":"a.py","old_text":"x","new_text":"y"}',
        json.dumps({"ok": True, "result": {}}),
    )
    state.observe_tool(
        "run_command",
        '{"command":"pytest -q"}',
        json.dumps({"ok": True, "result": {"exit_code": 0}}),
    )
    summary = state.summary()
    assert summary["changed_files"] == ["a.py"]
    assert summary["commands_run"] == ["pytest -q"]
    assert summary["tool_counts"]["edit_file"] == 1


def test_session_logger_redacts_secret_like_strings(tmp_path):
    logger = SessionLogger(tmp_path)
    logger.log("test", payload="token=supersecretvalue", other="sk-abcdefghijklmnop")
    content = logger.path.read_text(encoding="utf-8")
    assert "supersecretvalue" not in content
    assert "sk-abcdefghijklmnop" not in content
    assert "REDACTED" in content


def test_session_logger_redacts_sensitive_dictionary_keys(tmp_path):
    logger = SessionLogger(tmp_path)
    logger.log("test", config={"api_key": "do-not-store", "normal": "ok"})
    content = logger.path.read_text(encoding="utf-8")
    assert "do-not-store" not in content
    assert '"normal": "ok"' in content


def test_session_logger_redacts_json_string_credentials_and_bearer(tmp_path):
    logger = SessionLogger(tmp_path)
    logger.log(
        "test",
        arguments='{"api_key":"hidden-value","other":"ok"}',
        auth="Bearer abcdefghijklmnopqrstuvwxyz",
    )
    content = logger.path.read_text(encoding="utf-8")
    assert "hidden-value" not in content
    assert "abcdefghijklmnopqrstuvwxyz" not in content
