"""Near-duplicate merging across (and within) sources.

Similarity measure: token-set Jaccard over normalised words with stopwords and
modal verbs removed, ``|A & B| / |A | B|``. Two criteria merge when the measure
is >= the threshold (default 0.8); statements with fewer than three content
tokens merge only on exact normalised text. Greedy and order-independent:
entries are processed by (priority desc, source key, span, id) and each joins
the most similar earlier group (ties: earliest group), so the same inputs in
any order give the same groups.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from radius_intent.domain import Criterion

from .config import source_priority
from .report import CriterionTrace, DuplicateGroup, MergedOrigin

_WORD = re.compile(r"\w+")
STOPWORDS = frozenset(
    "a an the to of and or in on for is are be been being it its this that these those "
    "with by as at from can could will would should must shall may might has have had "
    "do does did not no able need needs".split()
)
MIN_TOKENS = 3


def exact_key(normalized: str) -> str:
    """Punctuation-insensitive key: all words (stopwords kept) joined."""
    return " ".join(_WORD.findall(normalized))


def content_tokens(normalized: str) -> frozenset[str]:
    """Return the content-word set used for similarity."""
    return frozenset(w for w in _WORD.findall(normalized) if w not in STOPWORDS)


def prefix_tokens(
    tokens: frozenset[str], threshold: float, freq: Counter[str]
) -> list[str]:
    """Return the prefix-filter tokens of a set (globally rarest first).

    Two sets with Jaccard >= ``threshold`` must share a token among their
    prefixes under any fixed total order, so only prefixes need indexing.
    Order: ascending document frequency over the whole batch, then
    alphabetical (a function of the batch's contents, not of its order).
    """
    ordered = sorted(tokens, key=lambda t: (freq[t], t))
    size = len(ordered)
    keep = size - math.ceil(threshold * size - 1e-9) + 1
    return ordered[:keep]


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-set Jaccard similarity (0.0 when both are empty)."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class Entry:
    """A criterion with its trace, ready for merging."""

    criterion: Criterion
    trace: CriterionTrace

    @property
    def sort_key(self) -> tuple[int, str, int, int, str]:
        """Deterministic processing order (highest priority first)."""
        c = self.criterion
        return (
            -source_priority(c.origin.source.kind),
            c.origin.source.key,
            c.span.start,
            c.span.end,
            c.id,
        )


def merge_duplicates(
    entries: list[Entry], threshold: float
) -> tuple[list[Entry], list[DuplicateGroup]]:
    """Merge near-duplicates; return kept entries and the merge records."""
    ordered = sorted(entries, key=lambda e: e.sort_key)
    freq: Counter[str] = Counter()
    for entry in ordered:
        freq.update(content_tokens(entry.criterion.normalized_text))
    kept: list[Entry] = []
    kept_tokens: list[frozenset[str]] = []
    merged: list[list[MergedOrigin]] = []
    by_norm: dict[str, int] = {}
    index: dict[str, list[int]] = {}
    for entry in ordered:
        crit = entry.criterion
        tokens = content_tokens(crit.normalized_text)
        key = exact_key(crit.normalized_text)
        group, sim = by_norm.get(key), 1.0
        if group is None and len(tokens) >= MIN_TOKENS:
            group, sim = _best_group(tokens, kept_tokens, index, threshold, freq)
        if group is None:
            gid = len(kept)
            kept.append(entry)
            kept_tokens.append(tokens)
            merged.append([])
            by_norm[key] = gid
            if len(tokens) >= MIN_TOKENS:
                for tok in prefix_tokens(tokens, threshold, freq):
                    index.setdefault(tok, []).append(gid)
        else:
            merged[group].append(
                MergedOrigin(
                    crit.id, crit.origin.source, crit.span, crit.text, round(sim, 6)
                )
            )
    groups = [
        DuplicateGroup(kept[i].criterion.id, tuple(m))
        for i, m in enumerate(merged)
        if m
    ]
    return kept, groups


def _best_group(
    tokens: frozenset[str],
    kept_tokens: list[frozenset[str]],
    index: dict[str, list[int]],
    threshold: float,
    freq: Counter[str],
) -> tuple[int | None, float]:
    candidates: set[int] = set()
    for tok in prefix_tokens(tokens, threshold, freq):
        candidates.update(index.get(tok, ()))
    best: int | None = None
    best_sim = 0.0
    size = len(tokens)
    for gid in sorted(candidates):
        other = kept_tokens[gid]
        lo, hi = sorted((size, len(other)))
        if lo / hi < threshold:
            continue
        sim = jaccard(tokens, other)
        if sim >= threshold and sim > best_sim:
            best, best_sim = gid, sim
    return best, best_sim
