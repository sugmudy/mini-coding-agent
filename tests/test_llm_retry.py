from __future__ import annotations

import pytest

from llm_client import LLMClient, LLMClientError


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def make_client(max_retries=3):
    client = LLMClient.__new__(LLMClient)
    client.max_retries = max_retries
    client.retry_backoff = 0
    client.sleep_fn = lambda _: None
    client._openai_error_type = lambda: FakeAPIError
    client._transport_error_type = lambda: OSError
    return client


def test_retry_transient_5xx_then_succeeds():
    client = make_client()
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeAPIError("temporary", 503)
        return "ok"

    assert client._request_with_retry(operation, label="test") == "ok"
    assert calls["n"] == 3


def test_does_not_retry_auth_error():
    client = make_client()
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        raise FakeAPIError("bad auth", 401)

    with pytest.raises(LLMClientError):
        client._request_with_retry(operation, label="test")
    assert calls["n"] == 1


def test_retries_lower_level_transport_error():
    class RemoteProtocolError(OSError):
        pass

    client = make_client(max_retries=1)
    client._transport_error_type = lambda: RemoteProtocolError
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RemoteProtocolError("incomplete chunked read")
        return "ok"

    assert client._request_with_retry(operation, label="test") == "ok"
    assert calls["n"] == 2
