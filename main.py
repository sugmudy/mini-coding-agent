from __future__ import annotations

import argparse
import sys

from agent import Agent
from config import Settings
from llm_client import LLMClient, LLMClientError
from tools.registry import ToolRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A minimal local coding agent powered by an OpenAI-compatible model gateway."
    )
    parser.add_argument("task", nargs="?", help="Programming task for the agent.")
    parser.add_argument("--workspace", help="Workspace directory. Default: ./workspace")
    parser.add_argument("--model", help="Model ID. Overrides AGENT_MODEL.")
    parser.add_argument("--max-steps", type=int, help="Maximum model turns. Default: 20")
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List model IDs available to the configured gateway and exit.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Hide intermediate agent/tool trace output.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        settings = Settings.from_env(
            workspace=args.workspace,
            model=args.model,
            max_steps=args.max_steps,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        llm = LLMClient(model=settings.model, timeout=settings.llm_timeout)
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

    registry = ToolRegistry(
        settings.workspace,
        command_timeout=settings.command_timeout,
    )
    agent = Agent(
        llm=llm,
        tools=registry,
        max_steps=settings.max_steps,
        verbose=not args.quiet,
    )

    try:
        final = agent.run(task)
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.", file=sys.stderr)
        return 130
    except (LLMClientError, RuntimeError, ValueError) as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1

    print("\n=== Final Answer ===")
    print(final or "(empty response)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
