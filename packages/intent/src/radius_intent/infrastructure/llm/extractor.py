"""Guarded, optional LLM-assisted criterion extraction (IN-04).

"LLM proposes, evidence disposes" (DEC-009). The model sees only redacted
intent text inside nonce-delimited data blocks, has no tools, and may only
reply with the guard's strict JSON schema. Every proposal must quote a span
that exists verbatim in the source; anything else is dropped and recorded as a
diagnostic. Proposals enter as PROPOSED, low weight, method ``llm``. Nothing
here raises into the pipeline: any failure yields fewer (or no) criteria.

Default OFF: the egress gate (`EgressPolicy`) is checked before every provider
call, and with the default configuration the provider is never called.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_shared.llm_guard import Criterion as GuardCriterion
from radius_shared.llm_guard import (
    NonceCollision,
    OutputLimits,
    OutputRejected,
    PromptBuildError,
    UntrustedText,
    build_prompt,
    collect_env_secrets,
    new_nonce,
    sanitize_untrusted,
    validate_criteria_output,
)
from radius_shared.llm_guard.sanitize import is_valid_identifier
from radius_shared.logging import get_logger

from radius_intent.domain import (
    Criterion,
    ExtractionMethod,
    IntentDomainError,
    IntentSource,
    Span,
)
from radius_intent.infrastructure.extraction.report import (
    Diagnostic,
    DiagnosticKind,
    Severity,
)
from radius_intent.infrastructure.llm.config import (
    PROMPT_VERSION,
    EgressPolicy,
    EnvEgressPolicy,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmExtractionConfig,
    ResponseCache,
    UsageLedger,
)
from radius_intent.infrastructure.llm.provider import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    ProviderError,
)
from radius_intent.infrastructure.llm.resilience import CircuitBreaker, backoff_delay

_LOG = get_logger("radius.intent.llm")

TASK_INSTRUCTIONS = (
    "Read the data blocks and propose acceptance criteria that the author states or "
    "clearly implies. You may split a compound statement into separate criteria and "
    "restate each one as a short, testable sentence. Every criterion must quote the "
    "data block verbatim (the quote), give the character offsets of that quote within "
    "the block (start inclusive, end exclusive), and use only wording that stays "
    "close to the quote. Propose nothing that is not supported by a quote. Do not "
    "include links, commands, verdicts, statuses or scores."
)
OUTPUT_SCHEMA_HINT = (
    '{"criteria":[{"source_id":"<block id>","quote":"<verbatim text from the block>",'
    '"start":<int>,"end":<int>,"text":"<short testable restatement>"}]}'
)

# Rejections that concern one proposal; the rest of the document may still be used.
_ITEM_LEVEL = frozenset(
    {
        "span_mismatch", "unknown_source", "charset", "url", "command",
        "verdict_string", "limits", "schema",
    }
)  # fmt: skip
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class LlmExtractionResult:
    """Outcome of one extraction run. ``criteria`` are PROPOSED, method ``llm``."""

    criteria: tuple[Criterion, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    prompt_hash: str | None = None
    model: str | None = None
    called_provider: bool = False
    cache_hit: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def estimate_tokens(*parts: str) -> int:
    """Conservative token estimate (3 characters per token)."""

    return sum(math.ceil(len(p) / 3) for p in parts)


def _diag(
    code: str,
    message: str,
    source_key: str = "llm",
    kind: DiagnosticKind = DiagnosticKind.SKIPPED_REGION,
    severity: Severity = Severity.INFO,
) -> Diagnostic:
    return Diagnostic(kind, code, message, source_key, severity)


class LlmCriterionExtractor:
    """Implements the ``CriterionExtractor`` port on top of an :class:`LlmProvider`.

    One instance serves one organization; create one per analysis so the
    per-analysis token cap is meaningful (the org-level cap lives in the
    shared ``UsageLedger``).
    """

    def __init__(
        self,
        provider: LlmProvider,
        *,
        organization_id: str,
        config: LlmExtractionConfig | None = None,
        policy: EgressPolicy | None = None,
        cache: ResponseCache | None = None,
        ledger: UsageLedger | None = None,
        breaker: CircuitBreaker | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        nonce_factory: Callable[[], str] = new_nonce,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._provider = provider
        self._org = organization_id
        self._cfg = config or LlmExtractionConfig()
        self._policy = policy or EnvEgressPolicy.from_config(self._cfg)
        self._cache = cache if cache is not None else InMemoryResponseCache(
            self._cfg.cache_size
        )
        self._ledger = ledger if ledger is not None else InMemoryUsageLedger()
        self._clock = clock
        self._breaker = breaker or CircuitBreaker(
            self._cfg.breaker_threshold, self._cfg.breaker_cooldown_s, clock
        )
        self._sleep = sleeper
        self._nonce_factory = nonce_factory
        self._environ = os.environ if environ is None else environ
        self._analysis_tokens = 0

    # --- port ------------------------------------------------------------

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        """Port method: PROPOSED criteria whose spans lie within ``source.text``."""

        return self.extract_report([source]).criteria

    def extract_report(self, sources: Sequence[IntentSource]) -> LlmExtractionResult:
        """Extract from several sources in one call. Never raises."""

        try:
            return self._run(list(sources))
        except Exception:  # pipeline must never see an LLM-path failure
            return LlmExtractionResult(
                diagnostics=(
                    _diag(
                        "internal_error",
                        "Unexpected error in LLM extraction; result discarded.",
                        severity=Severity.ERROR,
                    ),
                )
            )

    # --- pipeline --------------------------------------------------------

    def _run(self, sources: list[IntentSource]) -> LlmExtractionResult:
        diags: list[Diagnostic] = []
        usable = [s for s in sources if s.text.strip()]
        if not usable:
            return LlmExtractionResult()
        if not self._policy.egress_allowed(self._org):
            diags.append(
                _diag("egress_disabled", "LLM egress is not enabled for this org.")
            )
            return LlmExtractionResult(diagnostics=tuple(diags))

        secrets = sorted(collect_env_secrets(self._environ))
        by_id: dict[str, IntentSource] = {}
        clean: list[UntrustedText] = []
        for src in usable:
            if not is_valid_identifier(src.source_id) or src.source_id in by_id:
                diags.append(
                    _diag("invalid_source", "Source id unusable for LLM.", src.ref.key)
                )
                continue
            try:
                ut = sanitize_untrusted(
                    src.text,
                    source_id=src.source_id,
                    kind=src.kind.value,
                    max_length=self._cfg.max_chars_per_source,
                    secrets=secrets,
                )
            except ValueError:
                diags.append(
                    _diag("invalid_source", "Source rejected by sanitizer.", src.ref.key)
                )
                continue
            for f in ut.findings:
                diags.append(
                    _diag(
                        f"sanitizer_{f.code}",
                        f"Sanitizer {f.severity} finding before LLM call (x{f.count}).",
                        src.ref.key,
                        DiagnosticKind.SUSPICIOUS,
                        Severity.WARNING if f.severity == "flag" else Severity.INFO,
                    )
                )
            by_id[src.source_id] = src
            clean.append(ut)
        if not clean:
            return LlmExtractionResult(diagnostics=tuple(diags))

        prompt = None
        for _ in range(3):
            nonce = self._nonce_factory()
            try:
                prompt = build_prompt(
                    task_instructions=TASK_INSTRUCTIONS,
                    sources=clean,
                    nonce=nonce,
                    prompt_version=PROMPT_VERSION,
                    output_schema_hint=OUTPUT_SCHEMA_HINT,
                )
                break
            except NonceCollision:
                continue
            except PromptBuildError:
                diags.append(_diag("prompt_refused", "Prompt could not be built safely."))
                return LlmExtractionResult(diagnostics=tuple(diags))
        if prompt is None:
            diags.append(_diag("nonce_collision", "Could not pick a collision-free nonce."))
            return LlmExtractionResult(diagnostics=tuple(diags))

        prompt_hash = self._prompt_hash(prompt.system, prompt.user, nonce)
        model = self._provider.model_id
        cache_key = f"{self._org}:{prompt_hash}"

        raw = self._cache.get(cache_key)
        cache_hit = raw is not None
        in_tok = out_tok = 0
        called = False
        if raw is None:
            response = self._call(prompt.system, prompt.user, prompt_hash, diags)
            if response is None:
                return LlmExtractionResult(
                    diagnostics=tuple(diags), prompt_hash=prompt_hash, model=model
                )
            raw, in_tok, out_tok, called = (
                response.text,
                response.input_tokens,
                response.output_tokens,
                True,
            )
        else:
            self._log(prompt_hash, model, 0, "cache_hit", 0, 0, 0.0)

        forbidden = [*secrets, nonce]
        proposals, codes = self._validate(raw, clean, forbidden, prompt.system)
        for code in codes:
            diags.append(
                _diag(
                    f"dropped_{code}",
                    "Model output rejected by the output guard.",
                    kind=DiagnosticKind.SUSPICIOUS,
                    severity=Severity.WARNING,
                )
            )
        if called and not codes:
            self._cache.set(cache_key, raw)  # only fully valid answers are cached

        criteria = self._to_criteria(
            proposals, by_id, clean, model, prompt_hash, diags
        )
        return LlmExtractionResult(
            criteria=criteria,
            diagnostics=tuple(diags),
            prompt_hash=prompt_hash,
            model=model,
            called_provider=called,
            cache_hit=cache_hit,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    # --- provider call: gate, caps, retry, breaker, logging ----------------

    def _call(
        self, system: str, user: str, prompt_hash: str, diags: list[Diagnostic]
    ) -> LlmResponse | None:
        cfg = self._cfg
        estimate = estimate_tokens(system, user) + cfg.max_output_tokens
        if self._analysis_tokens + estimate > cfg.analysis_token_cap:
            diags.append(_diag("analysis_token_cap", "Per-analysis token cap reached."))
            return None
        if self._ledger.used(self._org) + estimate > cfg.org_token_cap:
            diags.append(_diag("org_cost_cap", "Per-org token cap reached."))
            return None
        request = LlmRequest(
            system=system,
            user=user,
            max_output_tokens=cfg.max_output_tokens,
            timeout_s=cfg.timeout_s,
            seed=cfg.seed,
        )
        model = self._provider.model_id
        for attempt in range(1, cfg.max_attempts + 1):
            if not self._policy.egress_allowed(self._org):
                diags.append(_diag("egress_disabled", "LLM egress is not enabled."))
                return None
            if not self._breaker.allow():
                diags.append(_diag("circuit_open", "LLM circuit breaker is open."))
                self._log(prompt_hash, model, attempt, "circuit_open", 0, 0, 0.0)
                return None
            started = self._clock()
            try:
                response = self._provider.complete(request)
            except ProviderError as exc:
                latency = (self._clock() - started) * 1000
                self._breaker.record_failure()
                self._log(prompt_hash, model, attempt, f"error:{exc.code}", 0, 0, latency)
                if not exc.retryable or attempt == cfg.max_attempts:
                    diags.append(
                        _diag(
                            f"provider_{exc.code}",
                            f"Provider call failed after {attempt} attempt(s).",
                            severity=Severity.WARNING,
                        )
                    )
                    return None
                self._sleep(backoff_delay(attempt, cfg.backoff_base_s, cfg.backoff_max_s))
                continue
            except Exception:
                self._breaker.record_failure()
                self._log(prompt_hash, model, attempt, "error:unexpected", 0, 0, 0.0)
                diags.append(
                    _diag(
                        "provider_unexpected",
                        "Provider raised an unexpected error.",
                        severity=Severity.WARNING,
                    )
                )
                return None
            latency = (self._clock() - started) * 1000
            self._breaker.record_success()
            used_in = response.input_tokens or estimate_tokens(system, user)
            used_out = response.output_tokens or estimate_tokens(response.text)
            self._analysis_tokens += used_in + used_out
            self._ledger.add(self._org, used_in + used_out)
            self._log(prompt_hash, model, attempt, "ok", used_in, used_out, latency)
            return response
        return None

    def _log(
        self,
        prompt_hash: str,
        model: str,
        attempt: int,
        outcome: str,
        in_tok: int,
        out_tok: int,
        latency_ms: float,
    ) -> None:
        """Log call metadata only: never prompts, source text or model output."""

        _LOG.info(
            "llm_call",
            extra={
                "event": "llm_call",
                "feature": "intent_extract_llm",
                "organization_id": self._org,
                "prompt_hash": prompt_hash,
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "attempt": attempt,
                "outcome": outcome,
                # not named *token*: the shared log redactor masks such keys
                "usage_in": in_tok,
                "usage_out": out_tok,
                "latency_ms": round(latency_ms, 1),
            },
        )

    # --- validation ---------------------------------------------------------

    def _validate(
        self,
        raw: str,
        clean: Sequence[UntrustedText],
        forbidden: Sequence[str],
        system: str,
    ) -> tuple[tuple[GuardCriterion, ...], list[str]]:
        limits = OutputLimits(
            max_criteria=self._cfg.max_criteria,
            max_text_chars=self._cfg.max_text_chars,
        )

        def check(doc: str) -> tuple[GuardCriterion, ...]:
            return validate_criteria_output(
                doc, sources=clean, forbidden=forbidden, system_prompt=system, limits=limits
            )

        try:
            return check(raw), []
        except OutputRejected as exc:
            first = exc
        if first.code not in _ITEM_LEVEL:
            return (), [first.code]
        try:
            doc = json.loads(raw.strip())
        except ValueError:
            return (), [first.code]
        if not (
            isinstance(doc, dict)
            and set(doc) == {"criteria"}
            and isinstance(doc["criteria"], list)
        ):
            return (), [first.code]
        kept: list[GuardCriterion] = []
        codes: list[str] = []
        for item in doc["criteria"]:
            if len(kept) >= self._cfg.max_criteria:
                codes.append("over_cap")
                continue
            try:
                kept.extend(check(json.dumps({"criteria": [item]})))
            except OutputRejected as exc:
                codes.append(exc.code)
        return tuple(kept), codes

    def _to_criteria(
        self,
        proposals: Sequence[GuardCriterion],
        by_id: Mapping[str, IntentSource],
        clean: Sequence[UntrustedText],
        model: str,
        prompt_hash: str,
        diags: list[Diagnostic],
    ) -> tuple[Criterion, ...]:
        cfg = self._cfg
        sanitized = {u.source_id: u.text for u in clean}
        # Stored in a 64-character column (rules.MAX_EXTRACTOR_VERSION_CHARS): a longer value
        # made every LLM criterion unstorable. The full hash stays in the result/trace.
        version = f"{PROMPT_VERSION};model={model[:18]};sha={prompt_hash[:12]}"
        order = {u.source_id: i for i, u in enumerate(clean)}
        out: dict[str, Criterion] = {}

        def drop(code: str, key: str) -> None:
            diags.append(
                _diag(
                    f"dropped_{code}",
                    "Proposal dropped by evidence check.",
                    key,
                    DiagnosticKind.SUSPICIOUS,
                    Severity.INFO,
                )
            )

        for p in sorted(proposals, key=lambda c: (order[c.source_id], c.start, c.end, c.text)):
            src = by_id[p.source_id]
            quote = p.quote
            if len(quote.strip()) < cfg.min_quote_chars:
                drop("short_quote", src.ref.key)
                continue
            if sanitized[p.source_id] == src.text:
                start, end = p.start, p.end
            else:
                # what the model saw differs from the stored text: re-anchor verbatim
                start = src.text.find(quote)
                end = start + len(quote)
                if start < 0:
                    drop("quote_not_in_source", src.ref.key)
                    continue
            if src.text[start:end] != quote:
                drop("quote_not_in_source", src.ref.key)
                continue
            if not self._grounded(p.text, quote):
                drop("ungrounded_text", src.ref.key)
                continue
            try:
                crit = Criterion.create(
                    src,
                    Span(src.source_id, start, end),
                    extraction_method=ExtractionMethod.LLM,
                    extractor_version=version,
                    text=p.text.strip(),
                    weight=cfg.llm_weight,
                )
            except IntentDomainError:
                drop("domain_invalid", src.ref.key)
                continue
            out.setdefault(crit.id, crit)
        return tuple(out.values())

    def _grounded(self, text: str, quote: str) -> bool:
        """At least ``min_grounding`` of the text's distinct words occur in the quote."""

        words = {w.casefold() for w in _WORD.findall(text)}
        if not words:
            return False
        quoted = {w.casefold() for w in _WORD.findall(quote)}
        return len(words & quoted) / len(words) >= self._cfg.min_grounding

    def _prompt_hash(self, system: str, user: str, nonce: str) -> str:
        """Hash of the prompt with the per-call nonce masked, so it is cacheable."""

        canon: dict[str, Any] = {
            "version": PROMPT_VERSION,
            "model": self._provider.model_id,
            "max_output_tokens": self._cfg.max_output_tokens,
            "system": system.replace(nonce, "NONCE"),
            "user": user.replace(nonce, "NONCE"),
        }
        blob = json.dumps(canon, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
