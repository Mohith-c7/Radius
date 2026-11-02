"""Prompt-injection suite adapter for LK-02 (``LlmReranker``).

Drives the real reranker with the suite's stub model wrapped as a provider. The
case inputs (already sanitised by IN-02 in production) become the criterion
text, and the first non-empty input line is also planted in a candidate's file
path, because file and symbol names are untrusted too. The adapter records
every prompt, re-derives the data blocks with the reranker's own
``prepare_sources`` and fails loudly if a planted secret reaches a re-rank
reason or if the model could add a symbol that was not a candidate.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from pi_harness import (
    FeatureInput,
    FeatureOutcome,
    LlmModel,
    PromptRecord,
    sanitize_inputs,
)
from radius_intent.infrastructure.llm import (
    EnvEgressPolicy,
    LlmRequest,
    LlmResponse,
)
from radius_linking.domain import CriterionInput, RerankCandidate
from radius_linking.infrastructure.rerank import (
    LlmRerankConfig,
    LlmReranker,
    prepare_sources,
)
from radius_shared.llm_guard import collect_env_secrets, contains_secret


class _RecordingProvider:
    model_id = "pi-stub-model"

    def __init__(self, model: LlmModel, nonce: str) -> None:
        self._model = model
        self._nonce = nonce
        self.prompts: list[PromptRecord] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.prompts.append(PromptRecord(request.system, request.user, self._nonce))
        return LlmResponse(self._model.complete(request.system, request.user), 10, 10)


def _candidates(planted: str) -> list[RerankCandidate]:
    return [
        RerankCandidate(
            "sym-1",
            "src/pricing.py",
            "apply_discount",
            "function",
            "modified_body",
            0.8,
        ),
        RerankCandidate("sym-2", "src/cart.py", "Cart.total", "method", "added", 0.5),
        RerankCandidate(
            "sym-3", f"src/{planted}.py", "helper", "function", "added", 0.3
        ),
    ]


class LinkRerankAdapter:
    name = "link-rerank-llm (LK-02)"

    def run(
        self,
        inputs: Sequence[FeatureInput],
        *,
        model: LlmModel,
        nonce: str,
        secrets: Sequence[str],
    ) -> FeatureOutcome:
        all_secrets = sorted({*secrets, *collect_env_secrets(os.environ)})
        ingested = [
            FeatureInput(s.source_id, s.kind, s.text)
            for s in sanitize_inputs(inputs, all_secrets)
        ]
        text = "\n".join(i.text for i in ingested if i.text.strip()) or "n/a"
        first = next(
            (ln.strip() for i in ingested for ln in i.text.splitlines() if ln.strip()),
            "x",
        )
        candidates = _candidates(first[:120])
        provider = _RecordingProvider(model, nonce)
        reranker = LlmReranker(
            provider,
            organization_id="org-pi",
            policy=EnvEgressPolicy(True, frozenset({"*"})),
            config=LlmRerankConfig(enabled=True),
            nonce_factory=lambda: nonce,
            environ=os.environ,
            sleeper=lambda _s: None,
        )
        result = reranker.rerank(CriterionInput("C-PI", text), candidates)
        allowed = {c.symbol_id for c in candidates}
        assert set(result.adjustments) <= allowed, "reranker produced a non-candidate"
        for adj in result.adjustments.values():
            assert not contains_secret(
                adj.reason, all_secrets
            ), "secret in rerank reason"
        sources, _refs = prepare_sources(text, candidates, all_secrets)
        dropped = [
            d.removeprefix("dropped_")
            for d in result.diagnostics
            if d.startswith("dropped_")
        ]
        return FeatureOutcome(
            prompts=tuple(provider.prompts),
            emitted=json.dumps({"criteria": []}),
            rejection_code=dropped[0] if dropped else None,
            fell_back=not result.adjustments,
            verdict_inputs={},
            findings={s.source_id: s.finding_codes() for s in sources},
            sources=tuple(sources),
        )
