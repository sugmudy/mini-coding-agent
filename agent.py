from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from context import ContextManager
from llm_client import LLMClient
from loop_detector import LoopDetector
from prompts import SYSTEM_PROMPT
from session_logger import SessionLogger
from state import AgentState
from tools.registry import ToolRegistry
from ui import BaseUI, FinalReport, NullUI, PlainUI


class Agent:
    """Model/tool control loop. The model proposes actions; this runtime executes and records them."""

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
        self.messages: list[dict[str, Any]] = []  # Full audit history, not compacted in place.
        self.state = AgentState()

    @staticmethod
    def _message_to_dict(message: Any) -> dict[str, Any]:
        if hasattr(message, "model_dump"):
            return message.model_dump(exclude_none=True)
        if isinstance(message, dict):
            return message
        raise TypeError(f"Unsupported assistant message type: {type(message)!r}")

    @staticmethod
    def _tool_success(tool_result: str) -> bool:
        try:
            return bool(json.loads(tool_result).get("ok"))
        except (json.JSONDecodeError, AttributeError):
            return False

    @staticmethod
    def _tool_safety(tool_result: str) -> tuple[bool, bool]:
        """Return (was_safety_related, approved_review)."""
        try:
            payload = json.loads(tool_result)
        except json.JSONDecodeError:
            return False, False
        if not payload.get("ok"):
            error = str(payload.get("error", ""))
            return "SafetyPolicy" in error, False
        result = payload.get("result")
        if not isinstance(result, dict):
            return False, False
        safety = result.get("safety")
        if not isinstance(safety, dict):
            return False, False
        return safety.get("level") == "review", bool(safety.get("approved"))

    def _extract_tool_call(self, tool_call: Any) -> tuple[str, str, str]:
        if isinstance(tool_call, dict):
            call_id = tool_call["id"]
            function = tool_call["function"]
            return call_id, function["name"], function.get("arguments", "{}")
        return tool_call.id, tool_call.function.name, tool_call.function.arguments or "{}"

    def _complete_report(self, final: str) -> None:
        self.state.finish()
        state_summary = self.state.summary()
        estimated = self.state.estimated_cost_usd(
            self.input_price_per_million,
            self.output_price_per_million,
        )
        if estimated is not None:
            state_summary["estimated_cost_usd"] = round(estimated, 6)
        log_path = str(self.logger.path) if self.logger.path else None
        self.ui.final_report(FinalReport(final_text=final, state=state_summary, session_log=log_path))

    def run(self, task: str) -> str:
        if not task.strip():
            raise ValueError("Task cannot be empty.")

        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.strip()},
        ]
        self.state = AgentState()
        validation_nudged = False
        self.ui.session_started(
            workspace=self.workspace,
            model=getattr(self.llm, "model", None),
            max_steps=self.max_steps,
            session_id=self.logger.session_id,
        )
        self.ui.task(task.strip())
        self.logger.log("session_start", task=task.strip(), max_steps=self.max_steps)

        for step in range(1, self.max_steps + 1):
            self.state.step = step
            model_messages = self.context.prepare(self.messages)
            if self.context.last_prepare_compacted:
                self.state.mark_context_compaction()
                self.logger.log(
                    "context_compaction",
                    step=step,
                    omitted_blocks=self.context.last_omitted_blocks,
                    full_history_messages=len(self.messages),
                    model_view_messages=len(model_messages),
                )
            self.ui.llm_step(step, self.max_steps)
            self.logger.log(
                "llm_request",
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
            self.messages.append(assistant_dict)
            self.logger.log(
                "llm_response",
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

                if self.state.changed_files and not self.state.commands_run and not validation_nudged:
                    validation_nudged = True
                    self.state.validation_nudges += 1
                    notice = (
                        "Runtime validation guard: files were changed but no validation command has been run. "
                        "If a reasonable test/build/run command exists, execute it before finishing. If no such "
                        "validation is appropriate, explain that explicitly and then finish."
                    )
                    self.messages.append({"role": "user", "content": notice})
                    self.logger.log("validation_nudge", step=step, changed_files=sorted(self.state.changed_files))
                    self.ui.warning("Changes were made without validation; the model gets one chance to verify them.")
                    continue

                self.state.finish()
                self.logger.log("session_complete", final=final, state=self.state.summary())
                self._complete_report(final)
                return final

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
                        step=step,
                        tool=name,
                        arguments=raw_arguments,
                        reason=loop_warning,
                    )
                    self.loop_detector.record(name, raw_arguments, succeeded=False)
                    tool_duration_ms = 0.0
                else:
                    started = time.perf_counter()
                    tool_result = self.tools.execute(name, raw_arguments)
                    tool_duration_ms = round((time.perf_counter() - started) * 1000, 2)
                    succeeded = self._tool_success(tool_result)
                    self.loop_detector.record(name, raw_arguments, succeeded=succeeded)
                    self.state.observe_tool(
                        name,
                        raw_arguments,
                        tool_result,
                        duration_ms=tool_duration_ms,
                    )
                    safety_related, approved_review = self._tool_safety(tool_result)
                    if safety_related and succeeded and approved_review:
                        self.state.mark_safety_approval()
                    elif safety_related and not succeeded:
                        self.state.mark_safety_block()
                    self.logger.log(
                        "tool_result",
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
                    }
                )

        self.state.finish()
        self.logger.log("session_stopped", reason="max_steps", state=self.state.summary())
        raise RuntimeError(
            f"Agent stopped after reaching the maximum of {self.max_steps} model steps."
        )
