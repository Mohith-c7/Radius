"""Provider-neutral LLM settings and the one factory every LLM feature uses.

``RADIUS_LLM_PROVIDER`` picks the adapter:

* ``anthropic`` (default, unchanged behaviour): the Anthropic Messages SDK (optional extra
  ``llm``); key from ``RADIUS_LLM_API_KEY`` or ``ANTHROPIC_API_KEY``.
* ``openai_compatible``: plain HTTP chat completions (``httpx``) against
  ``RADIUS_LLM_BASE_URL`` with ``RADIUS_LLM_API_KEY`` and ``RADIUS_LLM_MODEL`` (a
  comma-separated fallback list is allowed). This covers OpenRouter's free models
  (recommended), Google Gemini and Groq; see ``docs/ai.md``.

Nothing here sends anything: a provider is only built. Every feature keeps its own opt-in
flag and egress gate, and with no key configured :func:`build_llm_provider` returns
``(None, reason)`` and the features behave exactly as without AI. ``reason`` is a fixed,
secret-free phrase; callers still must not log it at a level that reaches shared logs.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from radius_intent.infrastructure.llm.config import DEFAULT_MODEL, ENV_MODEL
from radius_intent.infrastructure.llm.guarded import GuardedProvider, RateGate
from radius_intent.infrastructure.llm.provider import LlmProvider, ProviderConfigError

ENV_PROVIDER = "RADIUS_LLM_PROVIDER"
ENV_BASE_URL = "RADIUS_LLM_BASE_URL"
ENV_API_KEY = "RADIUS_LLM_API_KEY"
ENV_SHARED_MODEL = "RADIUS_LLM_MODEL"
ENV_TIMEOUT = "RADIUS_LLM_TIMEOUT_S"
ENV_DEADLINE = "RADIUS_LLM_DEADLINE_S"
ENV_MAX_CALLS = "RADIUS_LLM_MAX_CALLS_PER_ANALYSIS"
ENV_MIN_INTERVAL = "RADIUS_LLM_MIN_INTERVAL_S"
ENV_MAX_PER_DAY = "RADIUS_LLM_MAX_CALLS_PER_DAY"
ENV_MAX_ATTEMPTS = "RADIUS_LLM_MAX_ATTEMPTS"
ENV_JSON_MODE = "RADIUS_LLM_JSON_MODE"
ENV_REASONING = "RADIUS_LLM_REASONING_EFFORT"
ENV_TEMPERATURE = "RADIUS_LLM_TEMPERATURE"
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
PROVIDERS = frozenset({PROVIDER_ANTHROPIC, PROVIDER_OPENAI_COMPATIBLE})


def _float(env: Mapping[str, str], key: str, default: float, *, low: float, high: float) -> float:
    raw = (env.get(key) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return min(high, max(low, value))


def _int(env: Mapping[str, str], key: str, default: int, *, low: int, high: int) -> int:
    raw = (env.get(key) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return min(high, max(low, value))


@dataclass(frozen=True)
class LlmProviderSettings:
    """Shared provider settings (``RADIUS_LLM_*``). Defaults fit OpenRouter's free tier.

    OpenRouter ``:free`` models allow 20 requests a minute and 50 a day (1000 a day after
    buying 10 credits). ``min_interval_s`` 4 s keeps the process under 15 a minute and
    ``max_calls_per_day`` 45 under 50 a day; raise them only to your key's real limits.
    """

    provider: str = PROVIDER_ANTHROPIC
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout_s: float = 20.0
    deadline_s: float = 30.0
    max_calls_per_analysis: int = 3
    min_interval_s: float = 4.0
    max_calls_per_day: int = 45
    max_attempts: int = 2
    json_mode: str = "json_object"
    reasoning_effort: str = ""
    temperature: float | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LlmProviderSettings:
        env = os.environ if env is None else env
        d = cls()
        provider = (env.get(ENV_PROVIDER) or "").strip().lower() or d.provider
        key = (env.get(ENV_API_KEY) or "").strip()
        if not key and provider == PROVIDER_ANTHROPIC:
            key = (env.get(ANTHROPIC_KEY_ENV) or "").strip()
        model = (env.get(ENV_SHARED_MODEL) or "").strip() or (env.get(ENV_MODEL) or "").strip()
        temperature_raw = (env.get(ENV_TEMPERATURE) or "").strip()
        try:
            temperature = float(temperature_raw) if temperature_raw else None
        except ValueError:
            temperature = None
        return cls(
            provider=provider,
            base_url=(env.get(ENV_BASE_URL) or "").strip(),
            api_key=key,
            model=model,
            timeout_s=_float(env, ENV_TIMEOUT, d.timeout_s, low=1.0, high=120.0),
            deadline_s=_float(env, ENV_DEADLINE, d.deadline_s, low=2.0, high=300.0),
            max_calls_per_analysis=_int(
                env, ENV_MAX_CALLS, d.max_calls_per_analysis, low=1, high=20
            ),
            min_interval_s=_float(env, ENV_MIN_INTERVAL, d.min_interval_s, low=0.0, high=60.0),
            max_calls_per_day=_int(env, ENV_MAX_PER_DAY, d.max_calls_per_day, low=0, high=100_000),
            max_attempts=_int(env, ENV_MAX_ATTEMPTS, d.max_attempts, low=1, high=5),
            json_mode=(env.get(ENV_JSON_MODE) or "").strip().lower() or d.json_mode,
            reasoning_effort=(env.get(ENV_REASONING) or "").strip().lower(),
            temperature=temperature,
        )

    @property
    def resolved_model(self) -> str:
        if self.model:
            return self.model
        return DEFAULT_MODEL if self.provider == PROVIDER_ANTHROPIC else ""

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key)


_GATES: dict[tuple[float, int], RateGate] = {}
_GATES_LOCK = threading.Lock()


def shared_gate(settings: LlmProviderSettings) -> RateGate:
    """The process-wide pacing gate for these limits (one per distinct setting)."""

    key = (settings.min_interval_s, settings.max_calls_per_day)
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _GATES[key] = RateGate(settings.min_interval_s, settings.max_calls_per_day)
        return gate


def build_raw_provider(
    settings: LlmProviderSettings,
    *,
    transport: Any = None,
) -> tuple[LlmProvider | None, str]:
    """The bare adapter, or ``(None, reason)``. No network."""

    if settings.provider not in PROVIDERS:
        return None, f"{ENV_PROVIDER} must be anthropic or openai_compatible"
    if settings.provider == PROVIDER_ANTHROPIC:
        if not settings.api_key:
            return None, f"{ANTHROPIC_KEY_ENV} (or {ENV_API_KEY}) is not set"
        if importlib.util.find_spec("anthropic") is None:
            return None, "the 'anthropic' package is not installed (extra 'llm')"
        from radius_intent.infrastructure.llm.anthropic_provider import (
            AnthropicProvider,
        )

        return (
            AnthropicProvider(
                settings.resolved_model, environ={ANTHROPIC_KEY_ENV: settings.api_key}
            ),
            "ok",
        )
    if not settings.api_key:
        return None, f"{ENV_API_KEY} is not set"
    if not settings.base_url:
        return None, f"{ENV_BASE_URL} is not set"
    if not settings.resolved_model:
        return None, f"{ENV_SHARED_MODEL} is not set"
    from radius_intent.infrastructure.llm.openai_compatible import (
        OpenAICompatibleProvider,
    )

    try:
        return (
            OpenAICompatibleProvider(
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.resolved_model,
                json_mode=settings.json_mode,
                reasoning_effort=settings.reasoning_effort or None,
                temperature=settings.temperature,
                transport=transport,
            ),
            "ok",
        )
    except ProviderConfigError as exc:
        return None, str(exc)


def build_llm_provider(
    settings: LlmProviderSettings | None = None,
    *,
    per_analysis: bool = True,
    deadline_s: float | None = None,
    max_calls: int | None = None,
    transport: Any = None,
    gate: RateGate | None = None,
) -> tuple[LlmProvider | None, str]:
    """Build the configured provider wrapped in :class:`GuardedProvider`.

    ``per_analysis`` (default) applies the per-analysis call budget and the deadline
    (``RADIUS_LLM_DEADLINE_S`` unless ``deadline_s`` is given); build one per feature and
    analysis. ``per_analysis=False`` is for long-lived holders (the API container): pacing,
    daily cap and retries only.
    """

    settings = LlmProviderSettings.from_env() if settings is None else settings
    raw, why = build_raw_provider(settings, transport=transport)
    if raw is None:
        return None, why
    return (
        GuardedProvider(
            raw,
            gate=gate if gate is not None else shared_gate(settings),
            max_calls=(max_calls or settings.max_calls_per_analysis) if per_analysis else None,
            deadline_s=(deadline_s or settings.deadline_s) if per_analysis else None,
            max_attempts=settings.max_attempts,
            timeout_cap_s=settings.timeout_s,
        ),
        "ok",
    )


__all__ = [
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_PROVIDER",
    "ENV_SHARED_MODEL",
    "PROVIDERS",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_OPENAI_COMPATIBLE",
    "LlmProviderSettings",
    "build_llm_provider",
    "build_raw_provider",
    "shared_gate",
]
