"""OpenAI-compatible provider, guarded wrapper and factory (DEC-042). No network:
every HTTP exchange goes through ``httpx.MockTransport``."""

from __future__ import annotations

import json

import httpx
import pytest
from radius_intent.infrastructure.llm import (
    LlmRequest,
    ProviderAuthError,
    ProviderBudgetExhausted,
    ProviderConfigError,
    ProviderError,
    ProviderOutputTruncated,
    ProviderRateLimited,
    ProviderRequestError,
    ProviderTimeout,
    ProviderUnavailable,
)
from radius_intent.infrastructure.llm.factory import (
    LlmProviderSettings,
    build_llm_provider,
)
from radius_intent.infrastructure.llm.guarded import GuardedProvider, RateGate
from radius_intent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleProvider,
    parse_retry_after,
    unwrap_fence,
    validate_base_url,
)
from radius_intent.infrastructure.llm.pr_text import build_provider

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"
KEY = "test-key-" + "q" * 24
SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "string"}},
    "required": ["x"],
    "additionalProperties": False,
}


def _ok(content: str = '{"x":"y"}', finish: str = "stop", usage: dict | None = None) -> dict:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7},
    }


class Recorder:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    def body(self, n: int = -1) -> dict:
        return json.loads(self.requests[n].content)


def _provider(rec: Recorder, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=kw.pop("base_url", GEMINI),
        api_key=KEY,
        model=kw.pop("model", "gemini-3.5-flash-lite"),
        transport=httpx.MockTransport(rec),
        **kw,
    )


def _req(**kw) -> LlmRequest:
    return LlmRequest(system="sys", user="data", max_output_tokens=256, timeout_s=5, **kw)


# --- adapter ---------------------------------------------------------------


def test_request_shape_auth_and_structured_output() -> None:
    rec = Recorder(_ok())
    resp = _provider(rec, reasoning_effort="low", json_mode="schema").complete(
        _req(json_schema=SCHEMA, schema_name="radius_t")
    )
    sent = rec.requests[0]
    assert str(sent.url) == GEMINI + "chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.headers["x-title"] == "Radius" and sent.headers["x-openrouter-title"] == "Radius"
    body = rec.body()
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "data"}]
    assert body["max_tokens"] == 256 and body["n"] == 1 and body["stream"] is False
    assert body["reasoning_effort"] == "low"
    assert "temperature" not in body  # provider default unless configured
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "radius_t", "schema": SCHEMA, "strict": True},
    }
    assert (resp.text, resp.input_tokens, resp.output_tokens) == ('{"x":"y"}', 11, 7)


def test_json_modes() -> None:
    rec = Recorder(_ok(), _ok(), _ok(), _ok())
    _provider(rec).complete(_req(json_schema=SCHEMA))  # default: json_object
    assert rec.body()["response_format"] == {"type": "json_object"}
    _provider(rec).complete(_req())  # a request that expects no JSON gets none
    assert "response_format" not in rec.body()
    _provider(rec, json_mode="schema").complete(_req(json_schema=SCHEMA))
    assert rec.body()["response_format"]["type"] == "json_schema"
    _provider(rec, json_mode="off").complete(_req(json_schema=SCHEMA))
    assert "response_format" not in rec.body()


OPENROUTER = "https://openrouter.ai/api/v1"
CHAIN = "nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free"


def test_model_fallback_on_404_429_and_empty_content() -> None:
    none_content = {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
    rec = Recorder(
        httpx.Response(404, json={"error": {"message": "no longer available"}}),
        none_content,
        httpx.Response(429, json={"error": {"code": 429}}),
    )
    provider = _provider(rec, base_url=OPENROUTER, model=CHAIN + ",last/model:free")
    rec.responses.append(_ok())
    assert provider.complete(_req(json_schema=SCHEMA)).text == '{"x":"y"}'
    assert [rec.body(i)["model"] for i in range(4)] == [*CHAIN.split(","), "last/model:free"]
    assert provider.last_model == "last/model:free" and provider.model_id == CHAIN.split(",")[0]
    assert str(rec.requests[0].url) == OPENROUTER + "/chat/completions"


def test_upstream_error_in_a_200_body_also_falls_back() -> None:
    rec = Recorder({"error": {"code": 429, "message": "upstream rate limited"}}, _ok())
    assert _provider(rec, model="a:free,b:free").complete(_req()).text == '{"x":"y"}'
    assert rec.body(1)["model"] == "b:free"


def test_when_every_model_fails_the_last_error_is_raised() -> None:
    rec = Recorder(httpx.Response(404), httpx.Response(429, headers={"retry-after": "5"}))
    with pytest.raises(ProviderRateLimited) as info:
        _provider(rec, model="a,b").complete(_req())
    assert info.value.retryable and info.value.retry_after_s == 5.0
    with pytest.raises(ProviderRequestError):
        _provider(Recorder(httpx.Response(404)), model="a").complete(_req())
    with pytest.raises(ProviderRequestError):
        _provider(Recorder(_ok(content=""))).complete(_req())


def test_invalid_json_is_re_asked_once_with_a_stricter_prompt() -> None:
    rec = Recorder(_ok("Sure! here it is: {x}"), _ok('{"x":"fixed"}'))
    assert _provider(rec).complete(_req(json_schema=SCHEMA)).text == '{"x":"fixed"}'
    assert "not valid JSON" in rec.body(1)["messages"][0]["content"]
    assert "not valid JSON" not in rec.body(0)["messages"][0]["content"]
    # Still invalid after the re-ask: the first reply goes back to the caller's validator.
    rec2 = Recorder(_ok("nope"), _ok("still nope"))
    assert _provider(rec2).complete(_req(json_schema=SCHEMA)).text == "nope"
    # No schema, no re-ask.
    rec3 = Recorder(_ok("plain text"))
    assert _provider(rec3).complete(_req()).text == "plain text" and len(rec3.requests) == 1


def test_every_http_request_passes_the_gate() -> None:
    from radius_intent.infrastructure.llm.guarded import GuardedProvider, RateGate

    rec = Recorder(httpx.Response(429), _ok("bad"), _ok())
    gate = RateGate(0, 3)
    guard = GuardedProvider(_provider(rec, model="a,b"), gate=gate)
    guard.complete(_req(json_schema=SCHEMA))  # 429 on a, bad JSON on b, re-ask on b
    assert gate.calls_last_day == 3 and guard.calls == 1 and guard.last_model == "b"
    with pytest.raises(ProviderBudgetExhausted):
        guard.complete(_req())  # daily cap reached by real HTTP requests


def test_rejected_response_format_falls_back_once_and_is_remembered() -> None:
    rec = Recorder(httpx.Response(400, json={"error": "bad"}), _ok(), _ok())
    provider = _provider(rec)
    assert provider.complete(_req(json_schema=SCHEMA)).text == '{"x":"y"}'
    assert "response_format" in rec.body(0) and "response_format" not in rec.body(1)
    provider.complete(_req(json_schema=SCHEMA))
    assert "response_format" not in rec.body(2)


@pytest.mark.parametrize(
    ("response", "error", "retryable"),
    [
        (httpx.Response(429, headers={"retry-after": "7"}), ProviderRateLimited, True),
        (httpx.Response(503), ProviderUnavailable, True),
        (httpx.Response(401), ProviderAuthError, False),
        (httpx.Response(403), ProviderAuthError, False),
        (httpx.Response(404), ProviderRequestError, False),
        (httpx.ReadTimeout("slow"), ProviderTimeout, True),
        (httpx.ConnectError("down"), ProviderUnavailable, True),
    ],
)
def test_error_mapping(response, error, retryable) -> None:
    with pytest.raises(error) as info:
        _provider(Recorder(response)).complete(_req())
    assert info.value.retryable is retryable
    assert KEY not in str(info.value)
    if error is ProviderRateLimited:
        assert info.value.retry_after_s == 7.0


def test_error_body_is_never_echoed() -> None:
    rec = Recorder(httpx.Response(400, text="you sent: SECRET PROMPT " + KEY))
    with pytest.raises(ProviderRequestError) as info:
        _provider(rec).complete(_req())
    assert "SECRET" not in str(info.value) and KEY not in str(info.value)


def test_truncated_refused_and_empty_replies() -> None:
    with pytest.raises(ProviderOutputTruncated):
        _provider(Recorder(_ok(finish="length"))).complete(_req())
    with pytest.raises(ProviderRequestError):
        _provider(Recorder(_ok(finish="content_filter"))).complete(_req())
    with pytest.raises(ProviderRequestError):
        _provider(Recorder(_ok(content=""))).complete(_req())
    with pytest.raises(ProviderRequestError):
        _provider(Recorder({"nope": 1})).complete(_req())


def test_fenced_reply_and_content_parts_are_unwrapped() -> None:
    assert _provider(Recorder(_ok('```json\n{"x":"y"}\n```'))).complete(_req()).text == '{"x":"y"}'
    parts = {"choices": [{"message": {"content": [{"type": "text", "text": '{"x":'}, {"text": '"z"}'}]}, "finish_reason": "stop"}]}
    assert _provider(Recorder(parts)).complete(_req()).text == '{"x":"z"}'
    assert unwrap_fence("no fence") == "no fence"


def test_base_url_key_and_model_validation() -> None:
    assert validate_base_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"
    for bad in ("http://api.example.invalid/v1", "ftp://x", "https://user:pw@h.invalid/", "", "https://h.invalid/?k=1"):
        with pytest.raises(ProviderConfigError):
            validate_base_url(bad)
    with pytest.raises(ProviderConfigError):
        OpenAICompatibleProvider(base_url=GEMINI, api_key="", model="m")
    with pytest.raises(ProviderConfigError):
        OpenAICompatibleProvider(base_url=GEMINI, api_key=KEY, model=" ")
    assert KEY not in repr(_provider(Recorder()))
    assert parse_retry_after("abc") is None and parse_retry_after("99999") == 3600.0


# --- guarded wrapper -------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


class Scripted:
    model_id = "m"

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.timeouts: list[float] = []

    def complete(self, request):
        self.timeouts.append(request.timeout_s)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        from radius_intent.infrastructure.llm import LlmResponse

        return LlmResponse(item)


def _guard(inner, clock, **kw) -> GuardedProvider:
    gate = kw.pop("gate", None) or RateGate(0, 0, clock=clock)
    return GuardedProvider(inner, gate=gate, clock=clock, sleeper=clock.sleep, **kw)


def test_retries_honour_retry_after_then_succeed() -> None:
    clock = Clock()
    limited = ProviderRateLimited("429")
    limited.retry_after_s = 3.0
    inner = Scripted(limited, "ok")
    assert _guard(inner, clock, max_attempts=2).complete(_req()).text == "ok"
    assert clock.slept == [3.0]


def test_backoff_without_retry_after_and_final_error_is_not_retryable() -> None:
    clock = Clock()
    inner = Scripted(ProviderUnavailable("5xx"), ProviderUnavailable("5xx"), ProviderUnavailable("5xx"))
    with pytest.raises(ProviderUnavailable) as info:
        _guard(inner, clock, max_attempts=3).complete(_req())
    assert clock.slept == [2.0, 4.0]
    assert info.value.retryable is False  # a caller's own retry loop stops here


def test_long_retry_after_gives_up_immediately() -> None:
    clock = Clock()
    limited = ProviderRateLimited("daily quota")
    limited.retry_after_s = 3600.0
    with pytest.raises(ProviderRateLimited):
        _guard(Scripted(limited, "never"), clock, max_attempts=3).complete(_req())
    assert clock.slept == []


def test_non_retryable_errors_are_not_retried() -> None:
    clock = Clock()
    inner = Scripted(ProviderAuthError("401"), "never")
    with pytest.raises(ProviderAuthError):
        _guard(inner, clock, max_attempts=3).complete(_req())
    assert len(inner.outcomes) == 1


def test_per_analysis_call_budget_counts_retries() -> None:
    clock = Clock()
    inner = Scripted(ProviderTimeout("t"), "a", "b")
    guard = _guard(inner, clock, max_calls=2, max_attempts=2)
    assert guard.complete(_req()).text == "a"
    with pytest.raises(ProviderBudgetExhausted) as info:
        guard.complete(_req())
    assert info.value.retryable is False and guard.calls == 2


def test_deadline_caps_timeouts_and_stops_calls() -> None:
    clock = Clock()
    inner = Scripted("a", "b")
    guard = _guard(inner, clock, deadline_s=10.0, timeout_cap_s=20.0)
    guard.complete(LlmRequest(system="s", user="u", timeout_s=30))
    assert inner.timeouts == [10.0]
    clock.t += 9.5
    with pytest.raises(ProviderTimeout):
        guard.complete(_req())


def test_pacing_and_daily_cap_are_process_wide() -> None:
    clock = Clock()
    gate = RateGate(4.0, 3, clock=clock)
    a = _guard(Scripted("1", "2"), clock, gate=gate)
    b = _guard(Scripted("3", "4"), clock, gate=gate)
    a.complete(_req())
    b.complete(_req())  # waits 4 s for the shared slot
    a.complete(_req())
    assert clock.slept == [4.0, 4.0]
    with pytest.raises(ProviderBudgetExhausted):
        b.complete(_req())  # 3 calls in 24 h
    clock.t += 86_400
    assert b.complete(_req()).text == "4"


def test_pacing_wait_beyond_deadline_is_refused() -> None:
    clock = Clock()
    gate = RateGate(60.0, 0, clock=clock)
    _guard(Scripted("1"), clock, gate=gate).complete(_req())
    with pytest.raises(ProviderBudgetExhausted):
        _guard(Scripted("2"), clock, gate=gate, deadline_s=10.0).complete(_req())


# --- settings and factory --------------------------------------------------


GEMINI_ENV = {
    "RADIUS_LLM_PROVIDER": "openai_compatible",
    "RADIUS_LLM_BASE_URL": GEMINI,
    "RADIUS_LLM_API_KEY": KEY,
    "RADIUS_LLM_MODEL": "gemini-3.5-flash-lite",
}


def test_settings_from_env_and_defaults() -> None:
    s = LlmProviderSettings.from_env(GEMINI_ENV)
    assert s.provider == "openai_compatible" and s.resolved_model == "gemini-3.5-flash-lite"
    assert (s.min_interval_s, s.max_calls_per_day, s.max_calls_per_analysis) == (4.0, 45, 3)
    assert KEY not in repr(s)
    assert LlmProviderSettings.from_env({"RADIUS_LLM_INTENT_MODEL": "old"}).resolved_model == "old"
    clamped = LlmProviderSettings.from_env({"RADIUS_LLM_TIMEOUT_S": "9999", "RADIUS_LLM_MAX_ATTEMPTS": "x"})
    assert clamped.timeout_s == 120.0 and clamped.max_attempts == 2


def test_factory_builds_a_guarded_gemini_provider_end_to_end() -> None:
    rec = Recorder(_ok())
    provider, why = build_llm_provider(
        LlmProviderSettings.from_env(GEMINI_ENV), transport=httpx.MockTransport(rec), gate=RateGate(0, 0)
    )
    assert why == "ok" and isinstance(provider, GuardedProvider)
    assert provider.model_id == "gemini-3.5-flash-lite"
    assert provider.complete(_req()).text == '{"x":"y"}'


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({}, "ANTHROPIC_API_KEY"),
        ({**GEMINI_ENV, "RADIUS_LLM_API_KEY": ""}, "RADIUS_LLM_API_KEY"),
        ({**GEMINI_ENV, "RADIUS_LLM_BASE_URL": ""}, "RADIUS_LLM_BASE_URL"),
        ({**GEMINI_ENV, "RADIUS_LLM_MODEL": ""}, "RADIUS_LLM_MODEL"),
        ({**GEMINI_ENV, "RADIUS_LLM_BASE_URL": "http://evil.invalid/v1"}, "https"),
        ({**GEMINI_ENV, "RADIUS_LLM_PROVIDER": "openai"}, "RADIUS_LLM_PROVIDER"),
    ],
)
def test_no_key_or_bad_config_means_no_provider(env, needle) -> None:
    provider, why = build_llm_provider(LlmProviderSettings.from_env(env))
    assert provider is None and needle in why
    assert KEY not in why


def test_intent_build_provider_uses_the_configured_provider() -> None:
    from radius_intent.infrastructure.llm import LlmExtractionConfig

    provider, why = build_provider(LlmExtractionConfig(), GEMINI_ENV)
    assert why == "ok" and provider is not None and provider.model_id == "gemini-3.5-flash-lite"
    assert LlmExtractionConfig.from_env(GEMINI_ENV).model == "gemini-3.5-flash-lite"


def test_provider_errors_are_provider_errors() -> None:
    assert issubclass(ProviderBudgetExhausted, ProviderError)
    assert ProviderBudgetExhausted.code == "budget" and ProviderOutputTruncated.code == "truncated"
