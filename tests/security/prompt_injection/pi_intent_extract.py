"""Prompt-injection suite adapter for IN-04 (``LlmCriterionExtractor``).

Drives the real extractor with the suite's stub model wrapped as a provider.
It simulates IN-02 ingestion (sanitised text becomes ``IntentSource.text``),
records every prompt the provider receives, and emits the extractor's
criteria in the guard's strict schema so ``check_outcome`` can re-validate
them against the evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime

from pi_harness import (
    FeatureInput,
    FeatureOutcome,
    LlmModel,
    PromptRecord,
    sanitize_inputs,
)
from radius_intent.domain import IntentSource, IntentSourceKind
from radius_intent.infrastructure.llm import (
    EnvEgressPolicy,
    LlmCriterionExtractor,
    LlmExtractionConfig,
    LlmRequest,
    LlmResponse,
)
from radius_shared.llm_guard import collect_env_secrets

_KINDS = {
    "pr_title": IntentSourceKind.PR_TITLE,
    "pr_body": IntentSourceKind.PR_BODY,
    "commit_message": IntentSourceKind.COMMIT_MESSAGE,
    "issue_text": IntentSourceKind.ISSUE,
    "intent_yml_value": IntentSourceKind.SPEC_FILE,
}
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _RecordingProvider:
    model_id = "pi-stub-model"

    def __init__(self, model: LlmModel, nonce: str) -> None:
        self._model = model
        self._nonce = nonce
        self.prompts: list[PromptRecord] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.prompts.append(PromptRecord(request.system, request.user, self._nonce))
        return LlmResponse(self._model.complete(request.system, request.user), 10, 10)


class IntentExtractAdapter:
    name = "intent-extract-llm (IN-04)"

    def run(
        self,
        inputs: Sequence[FeatureInput],
        *,
        model: LlmModel,
        nonce: str,
        secrets: Sequence[str],
    ) -> FeatureOutcome:
        all_secrets = sorted({*secrets, *collect_env_secrets(os.environ)})
        # IN-02 stand-in: the stored source text is already sanitised.
        ingested = [
            FeatureInput(s.source_id, s.kind, s.text)
            for s in sanitize_inputs(inputs, all_secrets)
        ]
        sources = [
            IntentSource.from_text(
                i.source_id, _KINDS.get(i.kind, IntentSourceKind.COMMENT), i.text, _NOW
            )
            for i in ingested
        ]
        provider = _RecordingProvider(model, nonce)
        extractor = LlmCriterionExtractor(
            provider,
            organization_id="org-pi",
            policy=EnvEgressPolicy(True, frozenset({"*"})),
            config=LlmExtractionConfig(enabled=True),
            nonce_factory=lambda: nonce,
            environ=os.environ,
            sleeper=lambda _s: None,
        )
        result = extractor.extract_report(sources)
        by_id = {s.source_id: s for s in sources}
        emitted = [
            {
                "source_id": c.span.source_id,
                "quote": by_id[c.span.source_id].text[c.span.start : c.span.end],
                "start": c.span.start,
                "end": c.span.end,
                "text": c.text,
            }
            for c in result.criteria
        ]
        seen = tuple(sanitize_inputs(ingested, all_secrets))
        dropped = [d.code.removeprefix("dropped_") for d in result.diagnostics if d.code.startswith("dropped_")]
        return FeatureOutcome(
            prompts=tuple(provider.prompts),
            emitted=json.dumps({"criteria": emitted}, sort_keys=True),
            rejection_code=dropped[0] if dropped else None,
            fell_back=not result.criteria,
            verdict_inputs={},
            findings={s.source_id: s.finding_codes() for s in seen},
            sources=seen,
        )
