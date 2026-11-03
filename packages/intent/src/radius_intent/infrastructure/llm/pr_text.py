"""``llm`` extraction mode: guarded LLM proposals from the PR title and body (DEC-034).

"LLM proposes, evidence disposes". This module only *composes* the existing guarded
:class:`LlmCriterionExtractor` (nonce-delimited data blocks, strict JSON schema, verbatim
quote grounding, caps, egress gate, circuit breaker, token ledger) for one narrow use:

* only ``pr_title`` and ``pr_body`` sources are ever sent (no diff, no spec files, no
  comments, no commit messages); every other source kind is ignored here;
* every proposal is ``proposed``, method ``llm`` (provenance ``llm_proposed``), weight
  ``llm_weight``; nothing here can confirm a criterion or produce evidence;
* any failure (no key, SDK missing, timeout, rate limit, schema violation, caps, open
  breaker) yields no LLM criteria and a recorded degradation. The deterministic ``summary``
  extractors keep running next to it, so the result is never worse than ``summary`` mode;
* each run is recorded as a :class:`LlmRunRecord` (model, token usage, latency, drops,
  degradation) for the extraction trace.

The Anthropic SDK stays an optional extra and is imported lazily by the provider.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from radius_shared.logging import get_logger

from radius_intent.domain import Criterion, IntentSource, IntentSourceKind
from radius_intent.infrastructure.llm.config import (
    EnvEgressPolicy,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmExtractionConfig,
)
from radius_intent.infrastructure.llm.extractor import (
    LlmCriterionExtractor,
    LlmExtractionResult,
)
from radius_intent.infrastructure.llm.provider import LlmProvider
from radius_intent.interfaces import CriterionExtractor

_LOG = get_logger("radius.intent.llm_mode")

LLM_MODE = "llm"
API_KEY_ENV = "ANTHROPIC_API_KEY"

#: The only source kinds whose text may leave the machine in this mode.
PR_TEXT_KINDS = frozenset({IntentSourceKind.PR_TITLE, IntentSourceKind.PR_BODY})

#: Diagnostic codes of the guarded extractor that mean "the LLM path failed".
_FAILURE_CODES = frozenset(
    {
        "egress_disabled",
        "circuit_open",
        "analysis_token_cap",
        "org_cost_cap",
        "internal_error",
        "prompt_refused",
        "nonce_collision",
    }
)


@dataclass(frozen=True)
class LlmRunRecord:
    """One extraction run, for the trace (no prompt, no PR text, no model output)."""

    source_key: str
    model: str | None
    called_provider: bool
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    latency_ms: float
    proposals: int
    dropped_codes: tuple[str, ...]
    degraded: bool
    degraded_reason: str | None
    fallback: str | None  # "summary" when degraded


def degradation(result: LlmExtractionResult) -> str | None:
    """Why the run failed (first failing diagnostic code), or ``None`` when it did not."""

    codes = [d.code for d in result.diagnostics]
    for code in codes:
        if code in _FAILURE_CODES or code.startswith("provider_"):
            return code
    if result.called_provider and not result.criteria:
        # The model answered but nothing survived the output guard / evidence checks.
        for code in codes:
            if code.startswith("dropped_"):
                return code
    return None


class PrTextLlmExtractor:
    """``CriterionExtractor`` that proposes criteria from PR title/body via the guard.

    One instance per analysis (its :attr:`runs` is the trace of that analysis).
    """

    def __init__(
        self,
        inner: LlmCriterionExtractor,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self.runs: list[LlmRunRecord] = []

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        if source.kind not in PR_TEXT_KINDS or not source.text.strip():
            return ()
        started = self._clock()
        result = self._inner.extract_report([source])
        latency_ms = (self._clock() - started) * 1000
        reason = degradation(result)
        self.runs.append(
            LlmRunRecord(
                source_key=source.ref.key,
                model=result.model,
                called_provider=result.called_provider,
                cache_hit=result.cache_hit,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=round(latency_ms, 1),
                proposals=len(result.criteria),
                dropped_codes=tuple(
                    d.code for d in result.diagnostics if d.code.startswith("dropped_")
                ),
                degraded=reason is not None,
                degraded_reason=reason,
                fallback="summary" if reason is not None else None,
            )
        )
        return result.criteria


@dataclass(frozen=True)
class LlmModeSetup:
    """Extractors for ``llm`` mode plus why the LLM part is (not) active."""

    extractors: tuple[CriterionExtractor, ...]
    llm: PrTextLlmExtractor | None
    active: bool
    reason: str  # "active" or a short, secret-free explanation


_SHARED_CACHE = InMemoryResponseCache(256)
_SHARED_LEDGER = InMemoryUsageLedger()


def build_provider(
    config: LlmExtractionConfig, env: Mapping[str, str]
) -> tuple[LlmProvider | None, str]:
    """Build the Anthropic provider. ``(None, reason)`` without key or SDK. No network."""

    import importlib.util

    if not env.get(API_KEY_ENV, "").strip():
        return None, f"{API_KEY_ENV} is not set"
    if importlib.util.find_spec("anthropic") is None:
        return None, "the 'anthropic' package is not installed (extra 'llm')"
    from radius_intent.infrastructure.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(config.model, environ=env), "ok"


def build_llm_mode_extractors(
    base: Sequence[CriterionExtractor],
    organization_id: str,
    *,
    env: Mapping[str, str] | None = None,
    provider_factory: Callable[
        [LlmExtractionConfig, Mapping[str, str]], tuple[LlmProvider | None, str]
    ] = build_provider,
) -> LlmModeSetup:
    """Append the guarded PR-text LLM extractor to ``base`` when it may run.

    ``base`` is the deterministic set (``default_extractors("llm")``, i.e. summary
    behaviour); it is returned unchanged, with a clear log line, when the mode is
    selected but cannot run (flag off, org not enabled, no key, SDK missing).
    """

    environ = os.environ if env is None else env
    base_t = tuple(base)
    config = LlmExtractionConfig.from_env(environ)

    def disabled(reason: str, code: str) -> LlmModeSetup:
        # One fixed message per reason code: ``reason`` can derive from the environment and is
        # returned to the caller but never logged (CodeQL: clear-text logging of sensitive data).
        if code == "flag_off":
            detail = "RADIUS_LLM_INTENT_ENABLED is not true"
        elif code == "org_not_listed":
            detail = "the organization is not listed in RADIUS_LLM_INTENT_ORGS"
        else:
            detail = "no LLM provider could be created (is the API key set and the SDK installed?)"
        _LOG.warning(
            "RADIUS_INTENT_EXTRACTION_MODE=llm is selected but the LLM part is disabled: %s; "
            "falling back to the deterministic summary extraction.",
            detail,
        )
        return LlmModeSetup(base_t, None, False, reason)

    if not config.enabled:
        return disabled("RADIUS_LLM_INTENT_ENABLED is not true", "flag_off")
    if not EnvEgressPolicy.from_config(config).egress_allowed(organization_id):
        return disabled("organization is not listed in RADIUS_LLM_INTENT_ORGS", "org_not_listed")
    provider, why = provider_factory(config, environ)
    if provider is None:
        return disabled(why, "provider_unavailable")
    inner = LlmCriterionExtractor(
        provider,
        organization_id=organization_id,
        config=config,
        cache=_SHARED_CACHE,
        ledger=_SHARED_LEDGER,
        environ=environ,
    )
    llm = PrTextLlmExtractor(inner)
    _LOG.warning(
        "LLM extraction mode is ACTIVE: the PR title and body of analyses of this "
        "organization are sent to a third-party model provider (model %s).",
        provider.model_id,
    )
    return LlmModeSetup((*base_t, llm), llm, True, "active")


__all__ = [
    "API_KEY_ENV",
    "LLM_MODE",
    "PR_TEXT_KINDS",
    "LlmModeSetup",
    "LlmRunRecord",
    "PrTextLlmExtractor",
    "build_llm_mode_extractors",
    "build_provider",
    "degradation",
]
