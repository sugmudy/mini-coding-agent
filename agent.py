from __future__ import annotations

import json
import time
from typing import Any

from context import ContextManager
from llm_client import LLMClient
from loop_detector import LoopDetector
from prompts import SYSTEM_PROMPT
from session_logger import SessionLogger
from state import AgentState
from tools.registry import ToolRegistry


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
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive.")
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.verbose = verbose
        self.context = context_manager or ContextManager()
        self.loop_detector = loop_detector or LoopDetector()
        self.logger = session_logger or SessionLogger(enabled=False)
        self.messages: list[dict[str, Any]] = []
        self.state = AgentState()

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    @staticmethod
    def _message_to_dict(message: Any) -> dict[str, Any]:
        if hasattr(message, "model_dump"):
            return message.model_dump(exclude_none=True)
        if isinstance(message, dict):
            return message
        raise TypeError(f"Unsupported assistant message type: {type(message)!r}")

    @staticmethod
    def _preview(text: str, limit: int = 500) -> str:
        text = text.replace("\r", "")
        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _tool_success(tool_result: str) -> bool:
        try:
            return bool(json.loads(tool_result).get("ok"))
        except (json.JSONDecodeError, AttributeError):
            return False

    def _extract_tool_call(self, tool_call: Any) -> tuple[str, str, str]:
        if isinstance(tool_call, dict):
            call_id = tool_call["id"]
            function = tool_call["function"]
            return call_id, function["name"], function.get("arguments", "{}")
        return tool_call.id, tool_call.function.name, tool_call.function.arguments or "{}"

    def run(self, task: str) -> str:
        if not task.strip():
            raise ValueError("Task cannot be empty.")

        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.strip()},
        ]
        self.state = AgentState()
        validation_nudged = False
        self.logger.log("session_start", task=task.strip(), max_steps=self.max_steps)

        for step in range(1, self.max_steps + 1):
            self.state.step = step
            model_messages = self.context.prepare(self.messages)
            self._log(f"\n[step {step}/{self.max_steps}] Asking model...")
            self.logger.log(
                "llm_request",
                step=step,
                full_history_messages=len(self.messages),
                model_view_messages=len(model_messages),
            )

            started = time.perf_counter()
            assistant_message = self.llm.complete(model_messages, self.tools.schemas)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)

            assistant_dict = self._message_to_dict(assistant_message)
            self.messages.append(assistant_dict)
            self.logger.log("llm_response", step=step, duration_ms=duration_ms, message=assistant_dict)

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
                    notice = (
                        "Runtime validation guard: files were changed but no validation command has been run. "
                        "If a reasonable test/build/run command exists, execute it before finishing. If no such "
                        "validation is appropriate, explain that explicitly and then finish."
                    )
                    self.messages.append({"role": "user", "content": notice})
                    self.logger.log("validation_nudge", step=step, changed_files=sorted(self.state.changed_files))
                    self._log("[guard] Changes detected without validation; asking model to verify once.")
                    continue

                self.logger.log("session_complete", final=final, state=self.state.summary())
                self._log("[done] Model returned a final response.")
                return final

            for tool_call in tool_calls:
                call_id, name, raw_arguments = self._extract_tool_call(tool_call)
                self._log(f"[tool] {name}({self._preview(raw_arguments, 300)})")

                loop_warning = self.loop_detector.check(name, raw_arguments)
                if loop_warning:
                    tool_result = json.dumps(
                        {"ok": False, "error": "LoopDetected", "message": loop_warning},
                        ensure_ascii=False,
                    )
                    self._log(f"[loop] {loop_warning}")
                    self.logger.log(
                        "tool_blocked",
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
                    succeeded = self._tool_success(tool_result)
                    self.loop_detector.record(name, raw_arguments, succeeded=succeeded)
                    self.state.observe_tool(name, raw_arguments, tool_result)
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
                self._log(f"[result] {self._preview(bounded_result)}")
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": bounded_result,
                    }
                )

        self.logger.log("session_stopped", reason="max_steps", state=self.state.summary())
        raise RuntimeError(
            f"Agent stopped after reaching the maximum of {self.max_steps} model steps."
        )
