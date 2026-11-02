"""Extractor adapters for the harness: run the production extraction code (EP-05).

Kinds (``list-extractors``):

``deterministic``  ``DeterministicCriterionExtractor`` (``det-extract-v1``)
``llm``            guarded ``LlmCriterionExtractor`` alone, over a provider
``combined``       deterministic criteria + LLM proposals via ``merge_proposals``
``oracle``         sanity upper bound: returns the gold spans (F1 must be 1)
``null``           sanity lower bound: returns nothing (recall must be 0)

LLM providers (``provider.type``): ``fake-lines`` (offline heuristic that quotes
every line of a source), ``replay`` (answers from a recordings file) and
``anthropic`` (real network; refused unless ``--allow-real-llm`` is passed AND
``RADIUS_EVAL_ALLOW_REAL_LLM=1`` is set; see :func:`build_provider`).

Testability is rated by the production rater (``rate_criteria``) so the
harness measures the same step the snapshot service runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from radius_shared.llm_guard import parse_data_blocks

from radius_intent.domain import Criterion, IntentSource, Testability
from radius_intent.infrastructure.extraction import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    DeterministicCriterionExtractor,
    ExtractionConfig,
    normalize_mode,
)
from radius_intent.infrastructure.llm import (
    PROMPT_VERSION,
    EnvEgressPolicy,
    FakeProvider,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmCriterionExtractor,
    LlmExtractionConfig,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    merge_proposals,
)
from radius_intent.infrastructure.llm.anthropic_provider import AnthropicProvider
from radius_intent.infrastructure.testability import (
    TESTABILITY_RULES_VERSION,
    rate_criteria,
)

from .config import ConfigError, ExtractorSpec
from .gold import EvalCase
from .metrics import PredictedCriterion

FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)  # fixed: provenance time is irrelevant
ENV_ALLOW_REAL = "RADIUS_EVAL_ALLOW_REAL_LLM"
EVAL_ORG = "eval"
_NONCE_RE = re.compile(r"RADIUS_DATA_([A-Za-z0-9]+)")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


class RealProviderNotAllowed(ConfigError):
    """A real (network) LLM provider was requested without explicit opt-in."""


@dataclass
class ExtractionOutcome:
    """Predictions for one PR plus LLM usage bookkeeping."""

    criteria: tuple[PredictedCriterion, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    diagnostics: tuple[str, ...] = ()


# ----------------------------------------------------------------- providers


def blocks_key(request: LlmRequest) -> str:
    """Stable key of a request: hash of its (source id, text) data blocks.

    Independent of the per-call nonce, so recordings replay across runs.
    """
    match = _NONCE_RE.search(request.system)
    blocks = parse_data_blocks(request.user, match.group(1)) if match else None
    items = sorted((blocks or {"": request.user}).items())
    blob = json.dumps(items, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fake_lines_handler(request: LlmRequest) -> str:
    """Offline stand-in for a model: quote every substantive line of each block."""
    match = _NONCE_RE.search(request.system)
    blocks = parse_data_blocks(request.user, match.group(1)) if match else None
    items: list[dict[str, Any]] = []
    for source_id, text in sorted((blocks or {}).items()):
        cursor = 0
        for line in text.split("\n"):
            start = text.index(line, cursor) if line else cursor
            cursor = start + len(line)
            bullet = _BULLET.match(line)
            offset = bullet.end() if bullet else 0
            quote = line[offset:].strip()
            if len(quote) < 12 or quote.startswith("#"):
                continue
            q_start = (
                start + offset + (len(line[offset:]) - len(line[offset:].lstrip()))
            )
            items.append(
                {
                    "source_id": source_id,
                    "quote": quote,
                    "start": q_start,
                    "end": q_start + len(quote),
                    "text": quote,
                }
            )
    return json.dumps({"criteria": items})


class ReplayProvider:
    """Answers from recorded responses keyed by :func:`blocks_key`.

    A missing key yields an empty criteria document and is counted in
    ``misses`` (reported in the run manifest).
    """

    def __init__(
        self, responses: Mapping[str, str], *, model_id: str = "replay-model"
    ) -> None:
        self._responses = dict(responses)
        self._model_id = model_id
        self.misses = 0
        self.calls = 0

    @property
    def model_id(self) -> str:
        return self._model_id

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        text = self._responses.get(blocks_key(request))
        if text is None:
            self.misses += 1
            text = json.dumps({"criteria": []})
        return LlmResponse(text, 0, 0)


class RecordingProvider:
    """Wraps a provider and keeps every response for later replay."""

    def __init__(self, inner: LlmProvider) -> None:
        self._inner = inner
        self.recordings: dict[str, str] = {}

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def complete(self, request: LlmRequest) -> LlmResponse:
        response = self._inner.complete(request)
        self.recordings[blocks_key(request)] = response.text
        return response


def build_provider(
    options: Mapping[str, Any],
    *,
    allow_real_llm: bool = False,
    environ: Mapping[str, str] | None = None,
    base_dir: str | None = None,
) -> LlmProvider:
    """Create the provider named by ``options['type']``.

    The real provider needs BOTH ``allow_real_llm`` (CLI flag) and
    ``RADIUS_EVAL_ALLOW_REAL_LLM=1`` in the environment, so a config file alone
    can never trigger network calls or spend. The API key is read by the
    provider from ``ANTHROPIC_API_KEY`` only.
    """
    env = environ if environ is not None else {}
    ptype = options.get("type")
    if ptype == "fake-lines":
        return FakeProvider(
            fake_lines_handler,
            model_id=str(options.get("model", "fake-lines-1")),
            input_tokens=int(options.get("input_tokens", 100)),
            output_tokens=int(options.get("output_tokens", 50)),
        )
    if ptype == "replay":
        path = options.get("recordings")
        if not isinstance(path, str):
            raise ConfigError("replay provider needs 'recordings' (a JSON file path)")
        from pathlib import Path

        file = Path(path)
        if not file.is_absolute() and base_dir:
            file = Path(base_dir) / file
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read recordings {file}: {exc}") from exc
        responses = data.get("responses", data) if isinstance(data, dict) else None
        if not isinstance(responses, dict):
            raise ConfigError("recordings must be a JSON object of responses")
        return ReplayProvider(
            responses, model_id=str(data.get("model", "replay-model"))
        )
    if ptype == "anthropic":
        if not allow_real_llm or env.get(ENV_ALLOW_REAL, "") != "1":
            raise RealProviderNotAllowed(
                "real LLM provider refused: pass --allow-real-llm and set "
                f"{ENV_ALLOW_REAL}=1 (tests and CI never do this)"
            )
        inner = AnthropicProvider(
            str(options["model"]) if options.get("model") else "claude-haiku-5-5",
            environ=env,
        )
        return RecordingProvider(inner) if options.get("record", True) else inner
    raise ConfigError(
        f"unknown provider type {ptype!r} (fake-lines, replay, anthropic)"
    )


# ----------------------------------------------------------------- extractors


def _to_sources(case: EvalCase) -> list[IntentSource]:
    return [
        IntentSource.from_text(s.source_id, s.kind, s.text, FETCHED_AT)
        for s in case.sources
    ]


def _to_predicted(
    criteria: tuple[Criterion, ...], *, rate: bool
) -> tuple[PredictedCriterion, ...]:
    rated = rate_criteria(criteria) if rate else criteria
    return tuple(
        PredictedCriterion(
            source_id=c.span.source_id,
            start=c.span.start,
            end=c.span.end,
            text=c.text,
            testability=(
                None if c.testability is Testability.UNRATED else c.testability.value
            ),
            method=c.origin.extraction_method.value,
        )
        for c in rated
    )


class HarnessExtractor:
    """Base: ``extract(case)`` and ``describe()``."""

    def __init__(self, spec: ExtractorSpec, *, rate: bool) -> None:
        self.spec = spec
        self._rate = rate

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"kind": self.spec.kind}
        if self._rate:
            info["testability_rules"] = TESTABILITY_RULES_VERSION
        return info

    def extract(self, case: EvalCase) -> ExtractionOutcome:  # pragma: no cover
        raise NotImplementedError

    def finalize(self) -> dict[str, Any]:
        """Extra run artifacts (for example LLM recordings)."""
        return {}


class DeterministicHarness(HarnessExtractor):
    def __init__(self, spec: ExtractorSpec, *, rate: bool) -> None:
        super().__init__(spec, rate=rate)
        self._mode = normalize_mode(str(spec.options.get("mode", "")))
        self._ex = DeterministicCriterionExtractor(ExtractionConfig(mode=self._mode))

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "extractor_version": DETERMINISTIC_EXTRACTOR_VERSION,
            "mode": self._mode,
        }

    def extract(self, case: EvalCase) -> ExtractionOutcome:
        report = self._ex.extract_sources(_to_sources(case))
        return ExtractionOutcome(
            _to_predicted(report.criteria, rate=self._rate),
            diagnostics=tuple(d.code for d in report.diagnostics),
        )


class LlmHarness(HarnessExtractor):
    """LLM-only (``combine=False``) or deterministic + LLM (``combine=True``)."""

    def __init__(
        self,
        spec: ExtractorSpec,
        *,
        rate: bool,
        provider: LlmProvider,
        combine: bool,
    ) -> None:
        super().__init__(spec, rate=rate)
        self._provider = provider
        self._combine = combine
        self._det = DeterministicCriterionExtractor()
        self._cache = InMemoryResponseCache(4096)
        self._ledger = InMemoryUsageLedger()
        self._cfg = LlmExtractionConfig(
            enabled=True,
            orgs=frozenset({"*"}),
            analysis_token_cap=int(spec.options.get("analysis_token_cap", 30_000)),
            org_token_cap=int(spec.options.get("org_token_cap", 1_000_000)),
        )

    def describe(self) -> dict[str, Any]:
        info = {
            **super().describe(),
            "prompt_version": PROMPT_VERSION,
            "model": self._provider.model_id,
            "provider": str(dict(self.spec.options.get("provider", {})).get("type")),
        }
        if self._combine:
            info["extractor_version"] = DETERMINISTIC_EXTRACTOR_VERSION
        return info

    def extract(self, case: EvalCase) -> ExtractionOutcome:
        sources = _to_sources(case)
        digest = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:32]
        llm = LlmCriterionExtractor(
            self._provider,
            organization_id=EVAL_ORG,
            config=self._cfg,
            policy=EnvEgressPolicy(True, frozenset({"*"})),
            cache=self._cache,
            ledger=self._ledger,
            sleeper=lambda _s: None,
            nonce_factory=lambda: digest,
            environ={},
        )
        result = llm.extract_report(sources)
        criteria = result.criteria
        if self._combine:
            base = self._det.extract_sources(sources).criteria
            criteria = merge_proposals(base, result.criteria).criteria
        return ExtractionOutcome(
            _to_predicted(criteria, rate=self._rate),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            llm_calls=int(result.called_provider),
            cache_hits=int(result.cache_hit),
            diagnostics=tuple(d.code for d in result.diagnostics),
        )

    def finalize(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        recordings = getattr(self._provider, "recordings", None)
        if recordings:
            out["llm_recordings"] = {
                "model": self._provider.model_id,
                "prompt_version": PROMPT_VERSION,
                "responses": dict(sorted(recordings.items())),
            }
        misses = getattr(self._provider, "misses", None)
        if misses is not None:
            out["replay_misses"] = misses
        return out


class OracleHarness(HarnessExtractor):
    def extract(self, case: EvalCase) -> ExtractionOutcome:
        return ExtractionOutcome(
            tuple(
                PredictedCriterion(
                    g.span.source_id,
                    g.span.start,
                    g.span.end,
                    g.text or case.slice(g.span),
                    g.testability.value if g.testability else None,
                    "oracle",
                )
                for g in case.criteria
            )
        )


class NullHarness(HarnessExtractor):
    def extract(self, case: EvalCase) -> ExtractionOutcome:
        return ExtractionOutcome(())


@dataclass(frozen=True)
class KindInfo:
    kind: str
    summary: str
    needs_provider: bool = False
    options: tuple[str, ...] = ()
    versions: dict[str, str] = field(default_factory=dict)


def list_kinds() -> list[KindInfo]:
    """Describe every extractor kind (``list-extractors``)."""
    tx = {"testability_rules": TESTABILITY_RULES_VERSION}
    return [
        KindInfo(
            "deterministic",
            "Rule-based IN-03 extractor, LLM-free",
            versions={"extractor": DETERMINISTIC_EXTRACTOR_VERSION, **tx},
        ),
        KindInfo(
            "llm",
            "Guarded IN-04 LLM extractor alone",
            True,
            ("provider", "analysis_token_cap", "org_token_cap"),
            {"prompt": PROMPT_VERSION, **tx},
        ),
        KindInfo(
            "combined",
            "Deterministic criteria plus LLM proposals (production merge)",
            True,
            ("provider", "analysis_token_cap", "org_token_cap"),
            {
                "extractor": DETERMINISTIC_EXTRACTOR_VERSION,
                "prompt": PROMPT_VERSION,
                **tx,
            },
        ),
        KindInfo("oracle", "Sanity baseline: returns the gold spans (F1 = 1)"),
        KindInfo("null", "Sanity baseline: returns nothing (recall = 0)"),
    ]


PROVIDER_TYPES = {
    "fake-lines": "offline heuristic: quotes every substantive line",
    "replay": "answers from a recordings JSON ({'responses': {key: text}})",
    "anthropic": "REAL network provider; needs --allow-real-llm and "
    f"{ENV_ALLOW_REAL}=1 and ANTHROPIC_API_KEY",
}


def build_extractor(
    spec: ExtractorSpec,
    *,
    rate_testability: bool,
    allow_real_llm: bool = False,
    environ: Mapping[str, str] | None = None,
    base_dir: str | None = None,
    provider_factory: Callable[..., LlmProvider] = build_provider,
) -> HarnessExtractor:
    """Instantiate the extractor described by ``spec``."""
    if spec.kind == "deterministic":
        return DeterministicHarness(spec, rate=rate_testability)
    if spec.kind in ("llm", "combined"):
        options = spec.options.get("provider")
        if not isinstance(options, Mapping):
            raise ConfigError(
                f"extractor {spec.extractor_id!r} needs a 'provider' object"
            )
        provider = provider_factory(
            options, allow_real_llm=allow_real_llm, environ=environ, base_dir=base_dir
        )
        return LlmHarness(
            spec,
            rate=rate_testability,
            provider=provider,
            combine=spec.kind == "combined",
        )
    if spec.kind == "oracle":
        return OracleHarness(spec, rate=rate_testability)
    if spec.kind == "null":
        return NullHarness(spec, rate=rate_testability)
    raise ConfigError(f"unknown extractor kind {spec.kind!r}")
