from __future__ import annotations

import argparse
import sys

from agent import Agent
from config import Settings
from context import ContextManager
from llm_client import LLMClient, LLMClientError
from loop_detector import LoopDetector
from safety import SafetyPolicy
from session_logger import SessionLogger
from tools.registry import ToolRegistry
from ui import NullUI, PlainUI, RichUI
from version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A reliable, observable local coding agent powered by an OpenAI-compatible model gateway."
    )
    parser.add_argument("task", nargs="?", help="Programming task for the agent.")
    parser.add_argument("--workspace", help="Workspace directory. Default: ./workspace")
    parser.add_argument("--model", help="Model ID. Overrides AGENT_MODEL.")
    parser.add_argument("--max-steps", type=int, help="Maximum model turns. Default: 30")
    parser.add_argument("--log-dir", help="Session JSONL directory. Default: ./logs")
    parser.add_argument(
        "--safety",
        choices=["strict", "balanced", "permissive"],
        help="Safety mode. Default: AGENT_SAFETY_MODE or balanced.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-approve review-level actions. Blocked destructive actions remain blocked.",
    )
    parser.add_argument("--no-log", action="store_true", help="Disable local JSONL session tracing.")
    parser.add_argument("--no-color", action="store_true", help="Disable terminal colors while keeping structured UI.")
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List model IDs available to the configured gateway and exit.",
    )
    parser.add_argument("--quiet", action="store_true", help="Hide intermediate traces and print only the final answer.")
    parser.add_argument("--version", action="version", version=f"Mini Coding Agent {__version__}")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        settings = Settings.from_env(
            workspace=args.workspace,
            model=args.model,
            max_steps=args.max_steps,
            log_dir=args.log_dir,
            safety_mode=args.safety,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        llm = LLMClient(
            model=settings.model,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            retry_backoff=settings.retry_backoff,
        )
    except LLMClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.list_models:
        try:
            for model_id in llm.list_models():
                print(model_id)
        except LLMClientError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if not settings.model:
        print(
            "Configuration error: no model selected. Set AGENT_MODEL or pass --model. "
            "Run `python main.py --list-models` first if needed.",
            file=sys.stderr,
        )
        return 2

    task = args.task
    if not task:
        try:
            task = input("Task> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130

    if args.quiet:
        ui = NullUI()
    else:
        try:
            ui = RichUI(no_color=args.no_color, assume_yes=args.yes)
        except RuntimeError:
            ui = PlainUI(enabled=True, assume_yes=args.yes)

    safety_policy = SafetyPolicy(settings.safety_mode)
    registry = ToolRegistry(
        settings.workspace,
        command_timeout=settings.command_timeout,
        safety_policy=safety_policy,
        approval_callback=ui.confirm,
    )
    context = ContextManager(
        max_history_chars=settings.max_history_chars,
        max_tool_result_chars=settings.max_tool_result_chars,
    )
    loop_detector = LoopDetector(repeat_limit=settings.loop_repeat_limit)
    session_logger = SessionLogger(settings.log_dir, enabled=not args.no_log)

    agent = Agent(
        llm=llm,
        tools=registry,
        max_steps=settings.max_steps,
        verbose=not args.quiet,
        context_manager=context,
        loop_detector=loop_detector,
        session_logger=session_logger,
        ui=ui,
        workspace=settings.workspace,
        input_price_per_million=settings.input_price_per_million,
        output_price_per_million=settings.output_price_per_million,
    )

    try:
        final = agent.run(task)
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.", file=sys.stderr)
        return 130
    except (LLMClientError, RuntimeError, ValueError) as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(final or "(empty response)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
