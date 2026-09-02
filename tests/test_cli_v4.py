from __future__ import annotations

from main import build_parser
from version import __version__


def test_v4_cli_options_exist():
    parser = build_parser()
    args = parser.parse_args(
        ["--safety", "strict", "--reasoning-effort", "low", "--yes", "--no-color", "task"]
    )
    assert args.safety == "strict"
    assert args.yes is True
    assert args.no_color is True
    assert args.reasoning_effort == "low"
    assert args.task == "task"


def test_version_is_v5():
    assert __version__.startswith("0.5.")


def test_multi_agent_cli_options_exist():
    args = build_parser().parse_args(
        [
            "--multi-agent",
            "--review-rounds",
            "3",
            "--multi-agent-max-llm-calls",
            "20",
            "--multi-agent-token-budget",
            "10000",
            "task",
        ]
    )
    assert args.multi_agent is True
    assert args.review_rounds == 3
    assert args.multi_agent_max_llm_calls == 20
    assert args.multi_agent_token_budget == 10000
