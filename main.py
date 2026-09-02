from __future__ import annotations

import argparse
import sys

from agent import Agent
from config import Settings
from context import ContextManager
from llm_client import LLMClient, LLMClientError
from loop_detector import LoopDetector
from multi_agent.coordinator import MultiAgentCoordinator
from multi_agent.runtime import RoleAgentFactory
from safety import SafetyPolicy
from session_logger import SessionLogger
from tools.registry import ToolRegistry
from ui import BaseUI, FinalReport, NullUI, PlainUI, RichUI
from version import __version__


CHAT_HELP = """Conversation commands:
  /help      show this help
  /status    show cumulative session metrics
  /history   list requests made in this session
  /exit      finish the session (aliases: /quit, exit, quit)

Every normal input starts a new agent turn. Conversation history, tool observations,
workspace changes, and session metrics are preserved between turns. --max-steps is
applied separately to each turn."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A reliable, observable local coding agent powered by an OpenAI-compatible model gateway."
    )
    parser.add_argument("task", nargs="?", help="One-shot programming task. Omit it to enter multi-turn mode.")
    parser.add_argument("--workspace", help="Workspace directory. Default: ./workspace")
    parser.add_argument("--model", help="Model ID. Overrides AGENT_MODEL.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        help="Optional reasoning effort. Overrides AGENT_REASONING_EFFORT.",
    )
    parser.add_argument("--max-steps", type=int, help="Maximum model steps per user turn. Default: 30")
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
    parser.add_argument("--quiet", action="store_true", help="Hide traces and print only each final answer.")
    parser.add_argument(
        "--multi-agent",
        action="store_true",
        help="Run a bounded Planner -> Implementer -> Reviewer workflow. Requires a positional task.",
    )
    parser.add_argument(
        "--review-rounds",
        type=int,
        default=2,
        help="Maximum independent review attempts in multi-agent mode. Default: 2",
    )
    parser.add_argument(
        "--multi-agent-max-llm-calls",
        type=int,
        default=60,
        help="Hard global LLM-call budget for all roles. Default: 60",
    )
    parser.add_argument(
        "--multi-agent-token-budget",
        type=int,
        help="Optional aggregate token budget checked after each role turn.",
    )
    parser.add_argument("--version", action="version", version=f"Mini Coding Agent {__version__}")
    return parser


def run_interactive(agent: Agent, ui: BaseUI, *, quiet: bool = False) -> int:
    """Run a persistent terminal conversation around an already configured Agent."""
    agent.start_session()
    ui.conversation_ready()
    if not quiet:
        ui.info("Use /help to see conversation commands.")
    try:
        while True:
            user_input = ui.read_user_input()
            if user_input is None:
                break
            text = user_input.strip()
            if not text:
                continue
            command = text.lower()
            if command in {"/exit", "/quit", "exit", "quit"}:
                break
            if command == "/help":
                ui.info(CHAT_HELP)
                continue
            if command == "/status":
                log_path = str(agent.logger.path) if agent.logger.path else None
                ui.status_report(agent.state.summary(), session_log=log_path)
                continue
            if command == "/history":
                ui.history(agent.conversation_history())
                continue
            if command.startswith("/"):
                ui.warning(f"Unknown command: {text}. Use /help to list commands.")
                continue

            try:
                final = agent.run_turn(text, render_report=not quiet)
            except (LLMClientError, RuntimeError, ValueError) as exc:
                ui.warning(f"Turn failed: {exc}")
                continue
            if quiet:
                print(final or "(empty response)")
    finally:
        agent.finish_session(render_report=not quiet)
    return 0


def main() -> int:
    args = build_parser().parse_args()

    try:
        settings = Settings.from_env(
            workspace=args.workspace,
            model=args.model,
            max_steps=args.max_steps,
            log_dir=args.log_dir,
            safety_mode=args.safety,
            reasoning_effort=args.reasoning_effort,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        llm = LLMClient(
            model=settings.model,
            timeout=settings.llm_timeout,
            stream=settings.llm_stream,
            parallel_tool_calls=settings.llm_parallel_tool_calls,
            reasoning_effort=settings.reasoning_effort,
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

    if args.multi_agent and not args.task:
        print("Configuration error: --multi-agent requires a positional task.", file=sys.stderr)
        return 2

    if args.quiet:
        ui: BaseUI = NullUI(assume_yes=args.yes)
    else:
        try:
            ui = RichUI(no_color=args.no_color, assume_yes=args.yes)
        except RuntimeError:
            ui = PlainUI(enabled=True, assume_yes=args.yes)

    safety_policy = SafetyPolicy(settings.safety_mode)
    if args.multi_agent:
        try:
            shared_logger = SessionLogger(settings.log_dir, enabled=not args.no_log)
            factory = RoleAgentFactory(
                settings=settings,
                safety_policy=safety_policy,
                approval_ui=ui,
                logger=shared_logger,
            )
            coordinator = MultiAgentCoordinator(
                planner=factory.create("planner"),
                implementer=factory.create("implementer"),
                reviewer=factory.create("reviewer"),
                max_review_rounds=args.review_rounds,
                max_total_llm_calls=args.multi_agent_max_llm_calls,
                max_total_tokens=args.multi_agent_token_budget,
                logger=shared_logger,
                ui=ui,
            )
            result = coordinator.run(args.task)
            if args.quiet:
                print(result.final_text)
            else:
                ui.final_report(
                    FinalReport(
                        final_text=result.final_text,
                        state=result.state,
                        session_log=str(shared_logger.path) if shared_logger.path else None,
                    )
                )
            return 0 if result.success else 1
        except (LLMClientError, RuntimeError, ValueError) as exc:
            print(f"Multi-agent error: {exc}", file=sys.stderr)
            return 1

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
    agent = Agent(
        llm=llm,
        tools=registry,
        max_steps=settings.max_steps,
        verbose=not args.quiet,
        context_manager=context,
        loop_detector=LoopDetector(repeat_limit=settings.loop_repeat_limit),
        session_logger=SessionLogger(settings.log_dir, enabled=not args.no_log),
        ui=ui,
        workspace=settings.workspace,
        input_price_per_million=settings.input_price_per_million,
        output_price_per_million=settings.output_price_per_million,
    )

    try:
        if args.task:
            final = agent.run(args.task)
            if args.quiet:
                print(final or "(empty response)")
            return 0
        return run_interactive(agent, ui, quiet=args.quiet)
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.", file=sys.stderr)
        if agent.session_active:
            agent.finish_session(render_report=False)
        return 130
    except (LLMClientError, RuntimeError, ValueError) as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
