"""Optional, guarded LLM re-ranker for criterion -> symbol candidates (LK-02).

"LLM proposes, evidence disposes" (DEC-009). Default OFF. Rules enforced here:

* **Gate.** ``EgressPolicy.egress_allowed(org)`` is checked before every
  provider call; the default configuration never calls the provider. The flags
  are separate from IN-04's (``RADIUS_LLM_LINK_RERANK_ENABLED`` /
  ``RADIUS_LLM_LINK_RERANK_ORGS``).
* **What leaves (DEC-021).** The sanitised criterion text and, per candidate, an
  opaque reference plus name/path/kind/change-kind metadata. **Never** source
  code, docstrings, comments, literals, signatures or diffs. Even symbol names
  and paths are code-derived, so enabling this needs the admin to accept that
  (see the package README); a stricter code-egress policy is a follow-up.
* **Guard.** Untrusted text goes through ``sanitize_untrusted`` (secret masking
  included) and ``build_prompt`` (nonce-delimited data blocks); the reply must be
  one strict JSON document; refs must be among the candidates; anything else is
  dropped and the deterministic order stays.
* **Re-rank only.** The model sees candidates the deterministic linkers found and
  returns scores for them. The pipeline additionally discards any symbol that
  is not a candidate, so the model can never add a link.
* **Fail closed, no side effects.** No tools, no network in tests, never raises
  into the pipeline; metadata-only logging.
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

from radius_intent.infrastructure.llm import (
    CircuitBreaker,
    EgressPolicy,
    EnvEgressPolicy,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    ProviderError,
    ResponseCache,
    UsageLedger,
    backoff_delay,
)
from radius_shared.llm_guard import (
    NonceCollision,
    PromptBuildError,
    UntrustedText,
    build_prompt,
    collect_env_secrets,
    contains_secret,
    new_nonce,
    sanitize_untrusted,
)
from radius_shared.logging import get_logger

from radius_linking.domain import (
    CriterionInput,
    RerankAdjustment,
    RerankCandidate,
    RerankResult,
)

_LOG = get_logger("radius.linking.llm")

PROMPT_VERSION = "link-rerank-llm-v1"
VERSION = "link-rerank-llm-v1"
DEFAULT_MODEL = "claude-haiku-5-5"
ENV_ENABLED = "RADIUS_LLM_LINK_RERANK_ENABLED"
ENV_ORGS = "RADIUS_LLM_LINK_RERANK_ORGS"
ENV_MODEL = "RADIUS_LLM_LINK_RERANK_MODEL"
_TRUE = {"1", "true", "yes", "on"}

TASK_INSTRUCTIONS = (
    "The criterion block states what a code change should achieve. The candidates block "
    "lists code symbols (one per line: reference | kind | name | file | change kind) that "
    "might implement it. Judge only from the names and paths shown how plausible it is "
    "that each candidate implements the criterion. Score every listed reference between "
    "0 and 1 and give a short plain-text reason (at most 160 characters). Use only the "
    "references shown. Do not add references, links, commands, verdicts or statuses."
)
OUTPUT_SCHEMA_HINT = '{"ranking":[{"ref":"S1","score":0.0,"reason":"<short reason>"}]}'

_REF = re.compile(r"^S[0-9]{1,4}$")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file)://|\bwww\.")
_BAD_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f<>`$]")


@dataclass(frozen=True)
class LlmRerankConfig:
    """All knobs. Defaults are OFF and conservative."""

    enabled: bool = False
    orgs: frozenset[str] = frozenset()
    model: str = DEFAULT_MODEL
    max_output_tokens: int = 1024
    timeout_s: float = 30.0
    seed: int = 0
    max_attempts: int = 2
    backoff_base_s: float = 0.5
    backoff_max_s: float = 4.0
    breaker_threshold: int = 5
    breaker_cooldown_s: float = 60.0
    analysis_token_cap: int = 20_000
    org_token_cap: int = 500_000
    max_candidates: int = 10
    max_criterion_chars: int = 2_000
    max_reason_chars: int = 160
    max_raw_bytes: int = 16_384
    cache_size: int = 256

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LlmRerankConfig:
        env = os.environ if env is None else env
        orgs = frozenset(
            o.strip() for o in env.get(ENV_ORGS, "").split(",") if o.strip()
        )
        d = cls()
        return cls(
            enabled=env.get(ENV_ENABLED, "").strip().lower() in _TRUE,
            orgs=orgs,
            model=env.get(ENV_MODEL, "").strip() or d.model,
        )


def estimate_tokens(*parts: str) -> int:
    return sum(math.ceil(len(p) / 3) for p in parts)


def prepare_sources(
    criterion_text: str,
    candidates: Sequence[RerankCandidate],
    secrets: Sequence[str],
    *,
    max_criterion_chars: int = 2_000,
) -> tuple[list[UntrustedText], dict[str, str]]:
    """Sanitised data blocks for the prompt and the ``ref -> symbol_id`` map.

    Only names, paths and kinds of the candidates are included (no code).
    """

    refs = {f"S{i}": c.symbol_id for i, c in enumerate(candidates, start=1)}
    lines = [
        f"S{i} | {c.kind} | {c.qualified_name} | {c.path} | {c.change_kind}"
        for i, c in enumerate(candidates, start=1)
    ]
    sources = [
        sanitize_untrusted(
            criterion_text,
            source_id="criterion",
            kind="criterion_text",
            max_length=max_criterion_chars,
            secrets=secrets,
        ),
        sanitize_untrusted(
            "\n".join(lines),
            source_id="candidates",
            kind="symbol_metadata",
            max_length=20_000,
            secrets=secrets,
        ),
    ]
    return sources, refs


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key")
        out[k] = v
    return out


def parse_ranking(
    raw: str,
    refs: Mapping[str, str],
    *,
    forbidden: Sequence[str],
    max_raw_bytes: int = 16_384,
    max_reason_chars: int = 160,
) -> tuple[dict[str, RerankAdjustment], list[str]]:
    """Strictly validate a model reply. Returns (adjustments by symbol id, drop codes).

    Whole-document problems (not JSON, wrong shape, duplicate refs, oversize)
    yield no adjustments; bad items are dropped one by one.
    """

    if len(raw.encode("utf-8", "replace")) > max_raw_bytes:
        return {}, ["oversize"]
    try:
        doc = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, RecursionError):
        return {}, ["not_json"]
    if (
        not isinstance(doc, dict)
        or set(doc) != {"ranking"}
        or not isinstance(doc["ranking"], list)
    ):
        return {}, ["schema"]
    items = doc["ranking"]
    if len(items) > len(refs):
        return {}, ["too_many_items"]
    seen: set[str] = set()
    out: dict[str, RerankAdjustment] = {}
    codes: list[str] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"ref", "score", "reason"}:
            codes.append("item_schema")
            continue
        ref, score, why = item["ref"], item["score"], item["reason"]
        if not isinstance(ref, str) or not _REF.match(ref):
            codes.append("bad_ref")
            continue
        if ref in seen:
            return {}, ["duplicate_ref"]
        seen.add(ref)
        if ref not in refs:
            codes.append("unknown_ref")
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            codes.append("bad_score")
            continue
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            codes.append("score_range")
            continue
        if (
            not isinstance(why, str)
            or not why.strip()
            or len(why) > max_reason_chars
            or _BAD_CHARS.search(why)
            or _URL.search(why)
            or "<<<" in why
            or contains_secret(why, forbidden)
            or any(f and f.lower() in why.lower() for f in forbidden)
        ):
            codes.append("bad_reason")
            continue
        out[refs[ref]] = RerankAdjustment(float(score), why.strip())
    return out, codes


class LlmReranker:
    """Implements the ``Reranker`` port on top of an :class:`LlmProvider`.

    One instance serves one organization; create one per analysis so the
    per-analysis token cap is meaningful.
    """

    name = "llm"
    version = VERSION

    def __init__(
        self,
        provider: LlmProvider,
        *,
        organization_id: str,
        config: LlmRerankConfig | None = None,
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
        self._cfg = config or LlmRerankConfig()
        self._policy = policy or EnvEgressPolicy(self._cfg.enabled, self._cfg.orgs)
        self._cache = (
            cache if cache is not None else InMemoryResponseCache(self._cfg.cache_size)
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

    def rerank(
        self, criterion: CriterionInput, candidates: Sequence[RerankCandidate]
    ) -> RerankResult:
        """Never raises: any failure returns no adjustments plus a diagnostic code."""

        try:
            return self._run(criterion, list(candidates)[: self._cfg.max_candidates])
        except Exception:
            return RerankResult({}, ("internal_error",), VERSION)

    def _result(self, adj: Mapping[str, RerankAdjustment], *diags: str) -> RerankResult:
        return RerankResult(dict(adj), tuple(diags), VERSION)

    def _run(
        self, criterion: CriterionInput, candidates: list[RerankCandidate]
    ) -> RerankResult:
        if not candidates or not criterion.text.strip():
            return self._result({})
        if not self._policy.egress_allowed(self._org):
            return self._result({}, "egress_disabled")
        secrets = sorted(collect_env_secrets(self._environ))
        try:
            sources, refs = prepare_sources(
                criterion.text,
                candidates,
                secrets,
                max_criterion_chars=self._cfg.max_criterion_chars,
            )
        except ValueError:
            return self._result({}, "invalid_source")
        prompt = None
        nonce = ""
        for _ in range(3):
            nonce = self._nonce_factory()
            try:
                prompt = build_prompt(
                    task_instructions=TASK_INSTRUCTIONS,
                    sources=sources,
                    nonce=nonce,
                    prompt_version=PROMPT_VERSION,
                    output_schema_hint=OUTPUT_SCHEMA_HINT,
                )
                break
            except NonceCollision:
                continue
            except PromptBuildError:
                return self._result({}, "prompt_refused")
        if prompt is None:
            return self._result({}, "nonce_collision")

        prompt_hash = hashlib.sha256(
            f"{PROMPT_VERSION}\0{prompt.system}\0{prompt.user}\0{nonce}".encode()
        ).hexdigest()[:32]
        key = f"{self._org}:{prompt_hash}"
        raw = self._cache.get(key)
        called = False
        if raw is None:
            response = self._call(prompt.system, prompt.user, prompt_hash)
            if isinstance(response, str):
                return self._result({}, response)
            raw, called = response.text, True
        adj, codes = parse_ranking(
            raw,
            refs,
            forbidden=[*secrets, nonce],
            max_raw_bytes=self._cfg.max_raw_bytes,
            max_reason_chars=self._cfg.max_reason_chars,
        )
        if called and not codes:
            self._cache.set(key, raw)  # only fully valid answers are cached
        return self._result(adj, *(f"dropped_{c}" for c in codes))

    def _call(self, system: str, user: str, prompt_hash: str) -> LlmResponse | str:
        cfg = self._cfg
        estimate = estimate_tokens(system, user) + cfg.max_output_tokens
        if self._analysis_tokens + estimate > cfg.analysis_token_cap:
            return "analysis_token_cap"
        if self._ledger.used(self._org) + estimate > cfg.org_token_cap:
            return "org_cost_cap"
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
                return "egress_disabled"
            if not self._breaker.allow():
                return "circuit_open"
            started = self._clock()
            try:
                response = self._provider.complete(request)
            except ProviderError as exc:
                self._breaker.record_failure()
                self._log(prompt_hash, model, attempt, f"error:{exc.code}", 0, 0, 0.0)
                if not exc.retryable or attempt == cfg.max_attempts:
                    return f"provider_{exc.code}"
                self._sleep(
                    backoff_delay(attempt, cfg.backoff_base_s, cfg.backoff_max_s)
                )
                continue
            except Exception:
                self._breaker.record_failure()
                return "provider_unexpected"
            self._breaker.record_success()
            used_in = response.input_tokens or estimate_tokens(system, user)
            used_out = response.output_tokens or estimate_tokens(response.text)
            self._analysis_tokens += used_in + used_out
            self._ledger.add(self._org, used_in + used_out)
            self._log(
                prompt_hash, model, attempt, "ok", used_in, used_out,
                (self._clock() - started) * 1000,
            )  # fmt: skip
            return response
        return "provider_error"

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
        """Metadata only: never prompts, symbol names or model output."""

        _LOG.info(
            "llm_call",
            extra={
                "event": "llm_call",
                "feature": "link_rerank_llm",
                "organization_id": self._org,
                "prompt_hash": prompt_hash,
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "attempt": attempt,
                "outcome": outcome,
                "usage_in": in_tok,
                "usage_out": out_tok,
                "latency_ms": round(latency_ms, 1),
            },
        )
