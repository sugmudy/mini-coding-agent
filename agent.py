from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from context import ContextManager
from llm_client import LLMClient
from loop_detector import LoopDetector
from prompts import SYSTEM_PROMPT
from session_logger import SessionLogger
from state import AgentState, TurnState
from tools.registry import ToolRegistry
from ui import BaseUI, FinalReport, NullUI, PlainUI, SessionReport, TurnReport


class Agent:
    """Stateful model/tool runtime supporting one-shot and multi-turn sessions."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        max_steps: int = 30,
        verbose: bool = True,
        context_manager: ContextManager | None = None,
        loop_detector: LoopDetector | None = None,
        session_logger: SessionLogger | None = None,
        ui: BaseUI | None = None,
        workspace: str | Path | None = None,
        input_price_per_million: float | None = None,
        output_price_per_million: float | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive.")
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.context = context_manager or ContextManager()
        self.loop_detector = loop_detector or LoopDetector()
        self.logger = session_logger or SessionLogger(enabled=False)
        self.ui = ui or (PlainUI(enabled=True) if verbose else NullUI())
        self.workspace = Path(workspace or getattr(tools, "workspace", "."))
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.system_prompt = system_prompt
        self.messages: list[dict[str, Any]] = []
        self.state = AgentState()
        self._session_active = False
        self._session_finished = False
        # AgentState, message history, ContextManager diagnostics and most model
        # adapters are deliberately single-flight. Reject overlapping turns instead
        # of allowing nondeterministic interleaving or silently blocking a caller.
        self._turn_lock = threading.Lock()

    @property
    def session_active(self) -> bool:
        return self._session_active and not self._session_finished

    @staticmethod
    def _message_to_dict(message: Any) -> dict[str, Any]:
        if hasattr(message, "model_dump"):
            return message.model_dump(exclude_none=True)
        if isinstance(message, dict):
            return dict(message)
        raise TypeError(f"Unsupported assistant message type: {type(message)!r}")

    @staticmethod
    def _tool_outer_success(tool_result: str) -> bool:
        try:
            return bool(json.loads(tool_result).get("ok"))
        except (json.JSONDecodeError, AttributeError):
            return False

    @staticmethod
    def _tool_success(name: str, tool_result: str) -> bool:
        try:
            payload = json.loads(tool_result)
        except (json.JSONDecodeError, AttributeError):
            return False
        if not payload.get("ok"):
            return False
        if name != "run_command":
            return True
        result = payload.get("result")
        return (
            isinstance(result, dict)
            and result.get("exit_code") == 0
            and not result.get("error")
        )

    @staticmethod
    def _tool_safety(tool_result: str) -> tuple[bool, bool]:
        """Return (was_safety_related, approved_review)."""
        try:
            payload = json.loads(tool_result)
        except json.JSONDecodeError:
            return False, False
        if not payload.get("ok"):
            return "SafetyPolicy" in str(payload.get("error", "")), False
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("safety"), dict):
            return False, False
        safety = result["safety"]
        return safety.get("level") == "review", bool(safety.get("approved"))

    @staticmethod
    def _extract_tool_call(tool_call: Any) -> tuple[str, str, str]:
        if isinstance(tool_call, dict):
            function = tool_call["function"]
            return tool_call["id"], function["name"], function.get("arguments", "{}")
        return tool_call.id, tool_call.function.name, tool_call.function.arguments or "{}"

    def _with_cost(self, summary: dict[str, object], *, turn: TurnState | None = None) -> dict[str, object]:
        result = dict(summary)
        prompt_tokens = turn.prompt_tokens if turn is not None else self.state.prompt_tokens
        completion_tokens = turn.completion_tokens if turn is not None else self.state.completion_tokens
        if self.input_price_per_million is not None and self.output_price_per_million is not None:
            result["estimated_cost_usd"] = round(
                (
                    prompt_tokens * self.input_price_per_million
                    + completion_tokens * self.output_price_per_million
                )
                / 1_000_000,
                6,
            )
        return result

    def start_session(self) -> None:
        """Initialize one persistent conversation and its aggregate runtime state."""
        if self.session_active:
            raise RuntimeError("The agent session is already active.")
        if self._session_finished:
            raise RuntimeError("This Agent instance has already finished its session.")
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.state = AgentState()
        self._session_active = True
        self.ui.session_started(
            workspace=self.workspace,
            model=getattr(self.llm, "model", None),
            max_steps=self.max_steps,
            session_id=self.logger.session_id,
        )
        self.logger.log("session_start", max_steps_per_turn=self.max_steps)

    def _finish_turn(self, final: str, *, render_report: bool) -> str:
        turn = self.state.finish_turn(status="complete", final_text=final)
        summary = self._with_cost(turn.summary(), turn=turn)
        self.logger.log("turn_complete", turn_id=turn.turn_id, final=final, state=summary)
        if render_report:
            self.ui.turn_report(TurnReport(turn_id=turn.turn_id, final_text=final, state=summary))
        return final

    def run_turn(self, user_input: str, *, render_report: bool = True) -> str:
        """Run one exclusive user turn while preserving prior session context."""
        text = user_input.strip()
        if not text:
            raise ValueError("User input cannot be empty.")
        if not self._turn_lock.acquire(blocking=False):
            raise RuntimeError(
                "This Agent already has a running turn. Use one Agent instance per worker "
                "or serialize requests through a coordinator."
            )
        try:
            return self._run_turn(text, render_report=render_report)
        finally:
            self._turn_lock.release()

    def _run_turn(self, text: str, *, render_report: bool) -> str:
        if not self.session_active:
            self.start_session()

        turn = self.state.begin_turn(text)
        turn_id = turn.turn_id
        self.loop_detector.begin_turn()
        self.messages.append({"role": "user", "content": text, "_turn_id": turn_id})
        self.ui.task(text, turn_id=turn_id)
        self.logger.log("turn_start", turn_id=turn_id, user_input=text)
        validation_nudged = False

        try:
            for step in range(1, self.max_steps + 1):
                self.state.set_step(step)
                model_messages = self.context.prepare(self.messages)
                if self.context.last_prepare_compacted:
                    self.state.mark_context_compaction()
                    self.logger.log(
                        "context_compaction",
                        turn_id=turn_id,
                        step=step,
                        omitted_turns=self.context.last_omitted_turns,
                        omitted_blocks=self.context.last_omitted_blocks,
                        full_history_messages=len(self.messages),
                        model_view_messages=len(model_messages),
                    )
                self.ui.llm_step(step, self.max_steps, turn_id=turn_id)
                self.logger.log(
                    "llm_request",
                    turn_id=turn_id,
                    step=step,
                    full_history_messages=len(self.messages),
                    model_view_messages=len(model_messages),
                )

                started = time.perf_counter()
                assistant_message = self.llm.complete(model_messages, self.tools.schemas)
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                usage = getattr(self.llm, "last_usage", {}) or {}
                retries = int(getattr(self.llm, "last_retries", 0) or 0)
                self.state.observe_llm(duration_ms=duration_ms, usage=usage, retries=retries)

                assistant_dict = self._message_to_dict(assistant_message)
                assistant_dict["_turn_id"] = turn_id
                self.messages.append(assistant_dict)
                self.logger.log(
                    "llm_response",
                    turn_id=turn_id,
                    step=step,
                    duration_ms=duration_ms,
                    retries=retries,
                    usage=usage,
                    message=assistant_dict,
                )

                tool_calls = getattr(assistant_message, "tool_calls", None)
                if tool_calls is None and isinstance(assistant_message, dict):
                    tool_calls = assistant_message.get("tool_calls")

                if not tool_calls:
                    content = getattr(assistant_message, "content", None)
                    if content is None and isinstance(assistant_message, dict):
                        content = assistant_message.get("content")
                    final = (content or "").strip()
                    current = self.state.current_turn
                    if current and current.changed_files and not current.commands_run and not validation_nudged:
                        validation_nudged = True
                        self.state.mark_validation_nudge()
                        notice = (
                            "Runtime validation guard: files were changed in this turn but no validation command "
                            "has been run in this turn. If a reasonable test/build/run command exists, execute it "
                            "before finishing. If no validation is appropriate, explain that explicitly and finish."
                        )
                        self.messages.append(
                            {"role": "user", "content": notice, "_turn_id": turn_id, "_internal": True}
                        )
                        self.logger.log(
                            "validation_nudge",
                            turn_id=turn_id,
                            step=step,
                            changed_files=sorted(current.changed_files),
                        )
                        self.ui.warning("Changes were made in this turn without validation; the model gets one chance to verify them.")
                        continue
                    return self._finish_turn(final, render_report=render_report)

                for tool_call in tool_calls:
                    call_id, name, raw_arguments = self._extract_tool_call(tool_call)
                    self.ui.tool_called(name, raw_arguments)
                    loop_warning = self.loop_detector.check(name, raw_arguments)
                    if loop_warning:
                        tool_result = json.dumps(
                            {"ok": False, "error": "LoopDetected", "message": loop_warning},
                            ensure_ascii=False,
                        )
                        self.ui.warning(loop_warning)
                        self.logger.log(
                            "tool_blocked",
                            turn_id=turn_id,
                            step=step,
                            tool=name,
                            arguments=raw_arguments,
                            reason=loop_warning,
                        )
                        self.loop_detector.record(name, raw_arguments, succeeded=False)
                    else:
                        started = time.perf_counter()
                        tool_result = self.tools.execute(name, raw_arguments)
                        tool_duration_ms = round((time.perf_counter() - started) * 1000, 2)
                        succeeded = self._tool_success(name, tool_result)
                        self.loop_detector.record(name, raw_arguments, succeeded=succeeded)
                        self.state.observe_tool(
                            name,
                            raw_arguments,
                            tool_result,
                            duration_ms=tool_duration_ms,
                        )
                        safety_related, approved_review = self._tool_safety(tool_result)
                        if safety_related and approved_review:
                            self.state.mark_safety_approval()
                        elif safety_related and not self._tool_outer_success(tool_result):
                            self.state.mark_safety_block()
                        self.logger.log(
                            "tool_result",
                            turn_id=turn_id,
                            step=step,
                            tool=name,
                            arguments=raw_arguments,
                            succeeded=succeeded,
                            duration_ms=tool_duration_ms,
                            result=tool_result,
                        )

                    bounded_result = self.context.truncate_tool_result(tool_result)
                    self.ui.tool_result(name, bounded_result)
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": bounded_result,
                            "_turn_id": turn_id,
                        }
                    )

            raise RuntimeError(f"Agent stopped after reaching the maximum of {self.max_steps} model steps in turn {turn_id}.")
        except (Exception, KeyboardInterrupt) as exc:
            if self.state.current_turn is not None and self.state.current_turn.status == "running":
                failed = self.state.finish_turn(status="error")
                self.logger.log("turn_error", turn_id=turn_id, error=str(exc), state=failed.summary())
                # The partial messages/tools remain in the audit trail. Make their
                # failure status explicit to the next model turn without exposing a
                # possibly sensitive provider error string.
                self.messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"Turn {turn_id} ended with a local {type(exc).__name__} before a final answer. "
                            "Some tool side effects may already exist; re-inspect relevant files and validation "
                            "state before continuing. Do not treat that turn as completed work."
                        ),
                        "_turn_id": turn_id,
                        "_internal": True,
                    }
                )
            raise

    def finish_session(self, *, render_report: bool = True, final_text: str | None = None) -> None:
        if not self.session_active:
            return
        if self.state.current_turn is not None and self.state.current_turn.status == "running":
            raise RuntimeError("Cannot finish a session while a turn is running.")
        self.state.finish()
        summary = self._with_cost(self.state.summary())
        self.logger.log("session_complete", state=summary)
        self._session_finished = True
        self._session_active = False
        log_path = str(self.logger.path) if self.logger.path else None
        if not render_report:
            return
        if final_text is not None:
            self.ui.final_report(FinalReport(final_text=final_text, state=summary, session_log=log_path))
        else:
            self.ui.session_report(SessionReport(state=summary, session_log=log_path))

    def conversation_history(self) -> list[dict[str, object]]:
        return [
            {
                "turn_id": turn.turn_id,
                "user_input": turn.user_input,
                "final_text": turn.final_text,
                "status": turn.status,
            }
            for turn in self.state.turns
        ]

    def run(self, task: str) -> str:
        """Backward-compatible one-shot API."""
        if not task.strip():
            raise ValueError("Task cannot be empty.")
        self.start_session()
        try:
            final = self.run_turn(task, render_report=False)
        except Exception:
            self.finish_session(render_report=False)
            raise
        self.finish_session(render_report=True, final_text=final)
        return final
