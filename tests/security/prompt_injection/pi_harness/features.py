"""Reference LLM features for the suite.

* :class:`GuardedCriteriaFeature` shows the required wiring
  (sanitise -> delimit -> call -> strict validation -> fallback).
* :class:`NaiveCriteriaFeature` is the anti-pattern (string concatenation,
  trusts model output, lets it set a verdict). The suite must catch it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict

from radius_shared.llm_guard import (
    NonceCollision,
    OutputRejected,
    build_prompt,
    collect_env_secrets,
    sanitize_untrusted,
    validate_criteria_output,
)

from .core import FeatureInput, FeatureOutcome, LlmModel, PromptRecord

TASK = "Extract each testable requirement as a criterion. Quote the source verbatim and give its character span."
SCHEMA = '{"criteria":[{"source_id":"<id>","quote":"<verbatim>","start":<int>,"end":<int>,"text":"<short wording>"}]}'


def _canonical(criteria: Sequence[object]) -> str:
    return json.dumps({"criteria": [asdict(c) for c in criteria]}, sort_keys=True)  # type: ignore[call-overload]


class GuardedCriteriaFeature:
    name = "reference-guarded"

    def run(
        self,
        inputs: Sequence[FeatureInput],
        *,
        model: LlmModel,
        nonce: str,
        secrets: Sequence[str],
    ) -> FeatureOutcome:
        all_secrets = sorted({*secrets, *collect_env_secrets(os.environ)})
        sources = tuple(
            sanitize_untrusted(i.text, source_id=i.source_id, kind=i.kind, secrets=all_secrets)
            for i in inputs
        )
        findings = {s.source_id: s.finding_codes() for s in sources}
        try:
            prompt = build_prompt(
                task_instructions=TASK,
                sources=sources,
                nonce=nonce,
                prompt_version="criteria-v1",
                output_schema_hint=SCHEMA,
            )
        except NonceCollision:
            return FeatureOutcome((), _canonical([]), "nonce_collision", True, {}, findings, sources)
        raw = model.complete(prompt.system, prompt.user)
        try:
            criteria = validate_criteria_output(
                raw, sources=sources, forbidden=[*all_secrets, nonce], system_prompt=prompt.system
            )
        except OutputRejected as exc:
            # Fail closed: deterministic fallback, nothing from the model is used.
            return FeatureOutcome(
                (PromptRecord(prompt.system, prompt.user, nonce),),
                _canonical([]),
                exc.code,
                True,
                {},
                findings,
                sources,
            )
        return FeatureOutcome(
            (PromptRecord(prompt.system, prompt.user, nonce),),
            _canonical(criteria),
            None,
            False,
            {},
            findings,
            sources,
        )


class NaiveCriteriaFeature:
    """Anti-pattern: do not copy. Exists so the suite can prove it detects it."""

    name = "reference-naive"

    def run(
        self,
        inputs: Sequence[FeatureInput],
        *,
        model: LlmModel,
        nonce: str,
        secrets: Sequence[str],
    ) -> FeatureOutcome:
        user = "Requirements:\n" + "\n".join(i.text for i in inputs)
        system = "Extract requirements as JSON."
        raw = model.complete(system, user)
        verdict_inputs: dict[str, object] = {}
        try:
            doc = json.loads(raw)
            if isinstance(doc, dict) and "verdict" in doc:
                verdict_inputs["verdict"] = doc["verdict"]  # model output reaches verdict logic
        except ValueError:
            pass
        return FeatureOutcome((PromptRecord(system, user, None),), raw, None, False, verdict_inputs)
