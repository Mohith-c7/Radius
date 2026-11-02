"""Merge policy: deterministic and human criteria always win (IN-04).

LLM proposals are appended after the existing criteria, never replace or
reorder them, and are dropped when they duplicate one (same id, same
normalized text, or token-set Jaccard >= threshold, the same similarity rule
as IN-03). IN-06 ranks method ``llm`` last in its merge priority; this module
enforces the same order locally so the extractor is safe without IN-06.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from radius_intent.domain import (
    Criterion,
    CriterionState,
    ExtractionMethod,
    IntentSource,
)
from radius_intent.infrastructure.extraction.dedupe import (
    MIN_TOKENS,
    content_tokens,
    exact_key,
    jaccard,
)
from radius_intent.infrastructure.llm.extractor import (
    LlmCriterionExtractor,
    LlmExtractionResult,
)


@dataclass(frozen=True)
class DroppedProposal:
    criterion: Criterion
    reason: str  # not_llm | not_proposed | same_id | same_text | near_duplicate
    kept_id: str | None = None


@dataclass(frozen=True)
class MergeResult:
    criteria: tuple[Criterion, ...]
    dropped: tuple[DroppedProposal, ...] = ()


def merge_proposals(
    existing: Sequence[Criterion],
    proposals: Sequence[Criterion],
    *,
    similarity_threshold: float = 0.8,
) -> MergeResult:
    """Return ``existing`` unchanged followed by the surviving proposals."""

    kept: list[Criterion] = []
    dropped: list[DroppedProposal] = []
    by_id = {c.id: c for c in existing}
    by_text = {exact_key(c.normalized_text): c for c in existing}
    tokens = [(c, content_tokens(c.normalized_text)) for c in existing]

    for p in proposals:
        if p.origin.extraction_method is not ExtractionMethod.LLM:
            dropped.append(DroppedProposal(p, "not_llm"))
            continue
        if p.state is not CriterionState.PROPOSED:
            dropped.append(DroppedProposal(p, "not_proposed"))
            continue
        if p.id in by_id:
            dropped.append(DroppedProposal(p, "same_id", p.id))
            continue
        twin = by_text.get(exact_key(p.normalized_text))
        if twin is not None:
            dropped.append(DroppedProposal(p, "same_text", twin.id))
            continue
        ptok = content_tokens(p.normalized_text)
        near = None
        if len(ptok) >= MIN_TOKENS:
            for c, ctok in tokens:
                if len(ctok) >= MIN_TOKENS and jaccard(ptok, ctok) >= similarity_threshold:
                    near = c
                    break
        if near is not None:
            dropped.append(DroppedProposal(p, "near_duplicate", near.id))
            continue
        kept.append(p)
        by_id[p.id] = p
        by_text[exact_key(p.normalized_text)] = p
        tokens.append((p, ptok))
    return MergeResult((*existing, *kept), tuple(dropped))


@dataclass(frozen=True)
class AssistedExtraction:
    criteria: tuple[Criterion, ...]
    llm: LlmExtractionResult
    dropped: tuple[DroppedProposal, ...]


class AssistedCriterionExtractor:
    """``CriterionExtractor`` that runs a deterministic extractor, then the LLM.

    The deterministic output is authoritative and always returned intact; if the
    LLM is off, fails or proposes nothing valid, the result equals it.
    """

    def __init__(self, deterministic: object, llm: LlmCriterionExtractor) -> None:
        self._det = deterministic
        self._llm = llm

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        return self.extract_report([source]).criteria

    def extract_report(self, sources: Sequence[IntentSource]) -> AssistedExtraction:
        base: list[Criterion] = []
        for s in sources:
            base.extend(self._det.extract(s))  # type: ignore[attr-defined]
        result = self._llm.extract_report(sources)
        merged = merge_proposals(base, result.criteria)
        return AssistedExtraction(merged.criteria, result, merged.dropped)
