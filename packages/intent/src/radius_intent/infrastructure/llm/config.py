"""Configuration, egress gate, usage ledger and cache for LLM extraction."""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

PROMPT_VERSION = "intent-extract-llm-v1"
DEFAULT_MODEL = "claude-haiku-5-5"

ENV_ENABLED = "RADIUS_LLM_INTENT_ENABLED"
ENV_ORGS = "RADIUS_LLM_INTENT_ORGS"
ENV_MODEL = "RADIUS_LLM_INTENT_MODEL"

_TRUE = {"1", "true", "yes", "on"}


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class LlmExtractionConfig:
    """All knobs. Defaults are OFF and conservative (DEC-015).

    ``enabled`` is the deployment-wide flag; ``orgs`` is the per-org enable list
    (``"*"`` enables every org once the global flag is on). Token caps stand in
    for a cost cap: they bound spend without hard-coding provider prices.
    """

    enabled: bool = False
    orgs: frozenset[str] = frozenset()
    model: str = DEFAULT_MODEL
    max_output_tokens: int = 2048
    timeout_s: float = 30.0
    seed: int = 0
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0
    breaker_threshold: int = 5
    breaker_cooldown_s: float = 60.0
    analysis_token_cap: int = 30_000
    org_token_cap: int = 1_000_000
    max_chars_per_source: int = 20_000
    max_criteria: int = 20
    max_text_chars: int = 300
    min_quote_chars: int = 8
    min_grounding: float = 0.6
    llm_weight: float = 0.4
    cache_size: int = 256

    def __post_init__(self) -> None:
        if not 0 < self.llm_weight <= 1:
            raise ValueError("llm_weight must be in (0, 1].")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1.")
        if not 0 <= self.min_grounding <= 1:
            raise ValueError("min_grounding must be in [0, 1].")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LlmExtractionConfig:
        env = os.environ if env is None else env
        orgs = frozenset(
            o.strip() for o in env.get(ENV_ORGS, "").split(",") if o.strip()
        )
        d = cls()
        return cls(
            enabled=env.get(ENV_ENABLED, "").strip().lower() in _TRUE,
            orgs=orgs,
            model=env.get(ENV_MODEL, "").strip() or d.model,
            max_output_tokens=_int(
                env, "RADIUS_LLM_INTENT_MAX_OUTPUT_TOKENS", d.max_output_tokens
            ),
            timeout_s=_float(env, "RADIUS_LLM_INTENT_TIMEOUT_S", d.timeout_s),
            seed=_int(env, "RADIUS_LLM_INTENT_SEED", d.seed),
            max_attempts=_int(env, "RADIUS_LLM_INTENT_MAX_ATTEMPTS", d.max_attempts),
            breaker_threshold=_int(
                env, "RADIUS_LLM_INTENT_BREAKER_THRESHOLD", d.breaker_threshold
            ),
            breaker_cooldown_s=_float(
                env, "RADIUS_LLM_INTENT_BREAKER_COOLDOWN_S", d.breaker_cooldown_s
            ),
            analysis_token_cap=_int(
                env, "RADIUS_LLM_INTENT_ANALYSIS_TOKEN_CAP", d.analysis_token_cap
            ),
            org_token_cap=_int(
                env, "RADIUS_LLM_INTENT_ORG_TOKEN_CAP", d.org_token_cap
            ),
            max_criteria=_int(env, "RADIUS_LLM_INTENT_MAX_CRITERIA", d.max_criteria),
        )


class EgressPolicy(Protocol):
    """Gate checked before EVERY provider call (DEC-015)."""

    def egress_allowed(self, organization_id: str) -> bool: ...


@dataclass(frozen=True)
class EnvEgressPolicy:
    """Allowed only when the global flag is on and the org is enabled."""

    enabled: bool = False
    orgs: frozenset[str] = frozenset()

    @classmethod
    def from_config(cls, config: LlmExtractionConfig) -> EnvEgressPolicy:
        return cls(config.enabled, config.orgs)

    def egress_allowed(self, organization_id: str) -> bool:
        if not self.enabled or not organization_id:
            return False
        return "*" in self.orgs or organization_id in self.orgs


class UsageLedger(Protocol):
    """Token usage per organization (repository-agnostic)."""

    def used(self, organization_id: str) -> int: ...

    def add(self, organization_id: str, tokens: int) -> None: ...


class InMemoryUsageLedger:
    """Process-lifetime ledger. A durable, period-based one is a follow-up."""

    def __init__(self) -> None:
        self._used: dict[str, int] = {}

    def used(self, organization_id: str) -> int:
        return self._used.get(organization_id, 0)

    def add(self, organization_id: str, tokens: int) -> None:
        self._used[organization_id] = self.used(organization_id) + max(0, tokens)


class ResponseCache(Protocol):
    """Raw-response cache keyed by (org, prompt hash). Values are re-validated on use."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class InMemoryResponseCache:
    """Bounded LRU cache."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max = max(1, max_entries)
        self._data: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str) -> str | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
