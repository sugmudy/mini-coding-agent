from __future__ import annotations

from typing import Any

from llm_client import LLMClient, LLMClientError
from prompts import SYSTEM_PROMPT
from tools.registry import ToolRegistry


class Agent:
    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        max_steps: int = 20,
        verbose: bool = True,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive.")
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.verbose = verbose
        self.messages: list[dict[str, Any]] = []

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

    def run(self, task: str) -> str:
        if not task.strip():
            raise ValueError("Task cannot be empty.")

        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.strip()},
        ]

        for step in range(1, self.max_steps + 1):
            self._log(f"\n[step {step}/{self.max_steps}] Asking model...")

            try:
                assistant_message = self.llm.complete(self.messages, self.tools.schemas)
            except LLMClientError:
                raise

            assistant_dict = self._message_to_dict(assistant_message)
            self.messages.append(assistant_dict)

            tool_calls = getattr(assistant_message, "tool_calls", None)
            if tool_calls is None and isinstance(assistant_message, dict):
                tool_calls = assistant_message.get("tool_calls")

            if not tool_calls:
                content = getattr(assistant_message, "content", None)
                if content is None and isinstance(assistant_message, dict):
                    content = assistant_message.get("content")
                final = (content or "").strip()
                self._log("[done] Model returned a final response.")
                return final

            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    call_id = tool_call["id"]
                    function = tool_call["function"]
                    name = function["name"]
                    raw_arguments = function.get("arguments", "{}")
                else:
                    call_id = tool_call.id
                    name = tool_call.function.name
                    raw_arguments = tool_call.function.arguments or "{}"

                self._log(f"[tool] {name}({self._preview(raw_arguments, 300)})")
                tool_result = self.tools.execute(name, raw_arguments)
                self._log(f"[result] {self._preview(tool_result)}")

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_result,
                    }
                )

        raise RuntimeError(
            f"Agent stopped after reaching the maximum of {self.max_steps} model steps."
        )
