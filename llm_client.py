from __future__ import annotations

import time
from typing import Any, Callable


class LLMClientError(RuntimeError):
    """Raised when the model gateway cannot complete a request."""


class LLMClient:
    def __init__(
        self,
        *,
        model: str | None,
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMClientError(
                "The 'openai' package is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        self.model = model
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.sleep_fn = sleep_fn
        try:
            # Credentials and base URL intentionally stay in standard SDK environment configuration.
            # SDK retries are disabled because retry behavior belongs to this harness and is testable here.
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

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 429 or (isinstance(status, int) and 500 <= status <= 599):
            return True
        name = type(exc).__name__.lower()
        return any(
            token in name
            for token in (
                "connectionerror",
                "apiconnectionerror",
                "timeout",
                "apitimeouterror",
                "ratelimiterror",
                "internalservererror",
            )
        )

    def _request_with_retry(self, operation: Callable[[], Any], *, label: str) -> Any:
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return operation()
            except self._openai_error_type() as exc:
                last_error = exc
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    break
                delay = self.retry_backoff * (2**attempt)
                if delay > 0:
                    self.sleep_fn(delay)
        assert last_error is not None
        raise LLMClientError(f"{label} failed after {attempt + 1} attempt(s): {last_error}") from last_error

    def list_models(self) -> list[str]:
        response = self._request_with_retry(self.client.models.list, label="List models request")
        return sorted(model.id for model in response.data)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        if not self.model:
            raise LLMClientError(
                "No model selected. Set AGENT_MODEL or pass --model. Use --list-models to inspect available models."
            )

        response = self._request_with_retry(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            ),
            label="Model request",
        )
        if not response.choices:
            raise LLMClientError("Model gateway returned no choices.")
        return response.choices[0].message
