from __future__ import annotations

import pytest

from config import Settings


def test_streaming_defaults_to_enabled(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_LLM_STREAM", raising=False)
    monkeypatch.delenv("AGENT_LLM_PARALLEL_TOOL_CALLS", raising=False)
    settings = Settings.from_env(workspace=tmp_path)
    assert settings.llm_stream is True
    assert settings.llm_parallel_tool_calls is False


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_streaming_can_be_disabled(monkeypatch, tmp_path, value):
    monkeypatch.setenv("AGENT_LLM_STREAM", value)
    settings = Settings.from_env(workspace=tmp_path)
    assert settings.llm_stream is False


def test_invalid_streaming_value_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_LLM_STREAM", "sometimes")
    with pytest.raises(ValueError, match="AGENT_LLM_STREAM"):
        Settings.from_env(workspace=tmp_path)


def test_parallel_tool_calls_can_be_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_LLM_PARALLEL_TOOL_CALLS", "true")
    settings = Settings.from_env(workspace=tmp_path)
    assert settings.llm_parallel_tool_calls is True


def test_reasoning_effort_can_be_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_REASONING_EFFORT", "low")
    settings = Settings.from_env(workspace=tmp_path)
    assert settings.reasoning_effort == "low"


def test_invalid_reasoning_effort_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_REASONING_EFFORT", "maximum")
    with pytest.raises(ValueError, match="AGENT_REASONING_EFFORT"):
        Settings.from_env(workspace=tmp_path)
