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
        stream: bool = True,
        parallel_tool_calls: bool = False,
        reasoning_effort: str | None = None,
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
        self.stream = stream
        self.parallel_tool_calls = parallel_tool_calls
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.sleep_fn = sleep_fn
        self.last_attempts = 0
        self.last_retries = 0
        self.last_usage: dict[str, Any] = {}
        try:
            # Credentials and base URL intentionally stay in standard SDK environment configuration.
            # SDK retries stay disabled because retry policy is part of this harness and is tested here.
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
    def _transport_error_type():
        try:
            from httpx import TransportError
        except ImportError:
            return OSError
        return TransportError

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
                "remoteprotocolerror",
                "readerror",
                "networkerror",
                "transporterror",
                "timeout",
                "apitimeouterror",
                "ratelimiterror",
                "internalservererror",
            )
        )

    def _request_with_retry(self, operation: Callable[[], Any], *, label: str) -> Any:
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        self.last_attempts = 0
        self.last_retries = 0
        for attempt in range(attempts):
            self.last_attempts = attempt + 1
            try:
                result = operation()
                self.last_retries = attempt
                return result
            except (self._openai_error_type(), self._transport_error_type()) as exc:
                last_error = exc
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    self.last_retries = attempt
                    break
                delay = self.retry_backoff * (2**attempt)
                if delay > 0:
                    self.sleep_fn(delay)
        assert last_error is not None
        raise LLMClientError(f"{label} failed after {self.last_attempts} attempt(s): {last_error}") from last_error

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            value = usage.model_dump(exclude_none=True)
            return value if isinstance(value, dict) else {}
        if isinstance(usage, dict):
            return dict(usage)
        result = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            value = getattr(usage, key, None)
            if value is not None:
                result[key] = value
        return result

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @staticmethod
    def _merge_fragment(current: str, fragment: Any) -> str:
        """Join identifier/name fragments while tolerating gateways that repeat them."""
        if not isinstance(fragment, str) or not fragment:
            return current
        if not current:
            return fragment
        if fragment == current or current.endswith(fragment):
            return current
        if fragment.startswith(current):
            return fragment
        return current + fragment

    @classmethod
    def _consume_stream(cls, chunks: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Aggregate Chat Completions chunks into one protocol-valid assistant message."""
        role = "assistant"
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        refusal_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        saw_choice = False

        for chunk in chunks:
            chunk_usage = cls._usage_dict(cls._field(chunk, "usage"))
            if chunk_usage:
                usage = chunk_usage

            for choice in cls._field(chunk, "choices", []) or []:
                saw_choice = True
                delta = cls._field(choice, "delta")
                if delta is None:
                    continue
                delta_data = (
                    delta.model_dump(exclude_none=True)
                    if hasattr(delta, "model_dump")
                    else delta if isinstance(delta, dict) else {}
                )
                delta_role = cls._field(delta, "role")
                if isinstance(delta_role, str) and delta_role:
                    role = delta_role
                content = cls._field(delta, "content")
                if isinstance(content, str):
                    content_parts.append(content)
                reasoning = cls._field(delta, "reasoning_content")
                if reasoning is None and isinstance(delta_data, dict):
                    reasoning = delta_data.get("reasoning_content")
                if isinstance(reasoning, str):
                    reasoning_parts.append(reasoning)
                refusal = cls._field(delta, "refusal")
                if isinstance(refusal, str):
                    refusal_parts.append(refusal)

                for position, call_delta in enumerate(cls._field(delta, "tool_calls", []) or []):
                    call_index = cls._field(call_delta, "index")
                    call_id = cls._field(call_delta, "id")
                    if not isinstance(call_index, int):
                        matching_index = next(
                            (
                                index
                                for index, existing in tool_calls.items()
                                if call_id and existing.get("id") == call_id
                            ),
                            None,
                        )
                        call_index = matching_index if matching_index is not None else position
                    current = tool_calls.setdefault(
                        call_index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    current["id"] = cls._merge_fragment(current["id"], call_id)
                    call_type = cls._field(call_delta, "type")
                    if isinstance(call_type, str) and call_type:
                        current["type"] = call_type
                    function = cls._field(call_delta, "function")
                    if function is not None:
                        current_function = current["function"]
                        current_function["name"] = cls._merge_fragment(
                            current_function["name"], cls._field(function, "name")
                        )
                        arguments = cls._field(function, "arguments")
                        if isinstance(arguments, str):
                            current_function["arguments"] += arguments

        if not saw_choice:
            raise LLMClientError("Model gateway returned a stream with no choices.")

        message: dict[str, Any] = {"role": role}
        content = "".join(content_parts)
        if content:
            message["content"] = content
        reasoning_content = "".join(reasoning_parts)
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        refusal = "".join(refusal_parts)
        if refusal:
            message["refusal"] = refusal
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return message, usage

    def _stream_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=self.parallel_tool_calls,
            stream=True,
            stream_options={"include_usage": True},
        )
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        chunks = self.client.chat.completions.create(**request)
        return self._consume_stream(chunks)

    def list_models(self) -> list[str]:
        response = self._request_with_retry(self.client.models.list, label="List models request")
        return sorted(model.id for model in response.data)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        if not self.model:
            raise LLMClientError(
                "No model selected. Set AGENT_MODEL or pass --model. Use --list-models to inspect available models."
            )

        self.last_usage = {}
        if self.stream:
            message, usage = self._request_with_retry(
                lambda: self._stream_completion(messages, tools),
                label="Model request",
            )
            self.last_usage = usage
            return message

        request: dict[str, Any] = dict(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=self.parallel_tool_calls,
        )
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        response = self._request_with_retry(
            lambda: self.client.chat.completions.create(**request),
            label="Model request",
        )
        if not response.choices:
            raise LLMClientError("Model gateway returned no choices.")
        self.last_usage = self._usage_dict(getattr(response, "usage", None))
        return response.choices[0].message
