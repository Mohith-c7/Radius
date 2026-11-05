"""Anthropic adapter: request construction and error mapping with stubs only."""

from __future__ import annotations

import sys
import types

import pytest
from radius_intent.infrastructure.llm import (
    LlmRequest,
    ProviderAuthError,
    ProviderConfigError,
    ProviderRateLimited,
    ProviderRequestError,
    ProviderTimeout,
    ProviderUnavailable,
)
from radius_intent.infrastructure.llm.anthropic_provider import (
    AnthropicProvider,
    map_anthropic_error,
)

REQ = LlmRequest(system="SYS", user="USR", max_output_tokens=321, timeout_s=7.5, seed=0)


class StubMessages:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StubClient:
    def __init__(self, result):
        self.messages = StubMessages(result)


def message(text="{}", stop="end_turn", i=11, o=7):
    block = types.SimpleNamespace(type="text", text=text)
    other = types.SimpleNamespace(type="thinking", thinking="hidden")
    return types.SimpleNamespace(
        content=[other, block],
        stop_reason=stop,
        usage=types.SimpleNamespace(input_tokens=i, output_tokens=o),
    )


def err(name, status=None):
    cls = type(name, (Exception,), {})
    e = cls("detail with sk-secret")
    e.status_code = status
    return e


def test_request_construction_has_no_tools_and_no_sampling_params_by_default():
    p = AnthropicProvider("claude-haiku-5-5", client=StubClient(message()))
    kwargs = p.build_request(REQ)
    assert kwargs == {
        "model": "claude-haiku-5-5",
        "max_tokens": 321,
        "system": "SYS",
        "messages": [{"role": "user", "content": "USR"}],
        "timeout": 7.5,
        "output_config": {"effort": "low"},
    }
    assert "tools" not in kwargs and "temperature" not in kwargs and "seed" not in kwargs
    assert p.model_id == "claude-haiku-5-5"


def test_optional_temperature_and_effort():
    p = AnthropicProvider("m", client=StubClient(message()), effort=None, temperature=0.0)
    kwargs = p.build_request(REQ)
    assert kwargs["temperature"] == 0.0 and "output_config" not in kwargs


def test_complete_returns_text_and_usage():
    client = StubClient(message("hello", i=5, o=3))
    out = AnthropicProvider("m", client=client).complete(REQ)
    assert (out.text, out.input_tokens, out.output_tokens) == ("hello", 5, 3)
    assert client.messages.kwargs["system"] == "SYS"


def test_refusal_is_a_request_error():
    with pytest.raises(ProviderRequestError):
        AnthropicProvider("m", client=StubClient(message(stop="refusal"))).complete(REQ)


@pytest.mark.parametrize(
    "name,status,expected",
    [
        ("APITimeoutError", None, ProviderTimeout),
        ("RateLimitError", 429, ProviderRateLimited),
        ("AuthenticationError", 401, ProviderAuthError),
        ("PermissionDeniedError", 403, ProviderAuthError),
        ("APIConnectionError", None, ProviderUnavailable),
        ("InternalServerError", 529, ProviderUnavailable),
        ("APIStatusError", 408, ProviderUnavailable),
        ("BadRequestError", 400, ProviderRequestError),
        ("NotFoundError", 404, ProviderRequestError),
        ("SomethingElse", None, ProviderRequestError),
    ],
)
def test_error_mapping(name, status, expected):
    mapped = map_anthropic_error(err(name, status))
    assert type(mapped) is expected
    assert "sk-secret" not in str(mapped)
    with pytest.raises(expected):
        AnthropicProvider("m", client=StubClient(err(name, status))).complete(REQ)


def test_timeout_subclass_of_connection_error_maps_to_timeout():
    conn = type("APIConnectionError", (Exception,), {})
    timeout = type("APITimeoutError", (conn,), {})
    assert isinstance(map_anthropic_error(timeout("x")), ProviderTimeout)


def test_missing_key_is_config_error_and_key_comes_from_env_only():
    with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider("m", environ={}).complete(REQ)


def test_missing_sdk_is_config_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderConfigError, match="not installed"):
        AnthropicProvider("m", environ={"ANTHROPIC_API_KEY": "k"}).complete(REQ)


def test_client_built_lazily_with_env_key_and_sdk_retries_disabled(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.messages = StubMessages(message("ok"))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    p = AnthropicProvider("m", environ={"ANTHROPIC_API_KEY": " key-from-env "})
    assert seen == {}  # nothing built at construction
    assert p.complete(REQ).text == "ok"
    p.complete(REQ)
    assert seen == {"api_key": "key-from-env", "max_retries": 0}
