from __future__ import annotations

from typing import Any


class LLMClientError(RuntimeError):
    """Raised when the model gateway cannot complete a request."""


class LLMClient:
    def __init__(self, *, model: str | None, timeout: float = 60.0) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMClientError(
                "The 'openai' package is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        self.model = model
        try:
            # OpenAI-compatible credentials and base URL are intentionally
            # delegated to the SDK's standard environment configuration.
            self.client = OpenAI(timeout=timeout, max_retries=0)
        except Exception as exc:
            raise LLMClientError(
                "Failed to initialize the OpenAI-compatible client. Check the SDK environment configuration."
            ) from exc

    @staticmethod
    def _openai_error_type():
        try:
            from openai import OpenAIError
        except ImportError:
            return Exception
        return OpenAIError

    def list_models(self) -> list[str]:
        try:
            response = self.client.models.list()
        except self._openai_error_type() as exc:
            raise LLMClientError(f"Failed to list models: {exc}") from exc
        return sorted(model.id for model in response.data)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        if not self.model:
            raise LLMClientError(
                "No model selected. Set AGENT_MODEL or pass --model. "
                "Use --list-models to inspect models available to the configured gateway."
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except self._openai_error_type() as exc:
            raise LLMClientError(f"Model request failed: {exc}") from exc

        if not response.choices:
            raise LLMClientError("Model gateway returned no choices.")

        return response.choices[0].message
