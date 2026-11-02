# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Near-duplicate merging, priorities and the report's merge records."""

from __future__ import annotations

import random

import pytest
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from extraction_helpers import src
from radius_intent.domain import IntentSourceKind as K
from radius_intent.domain import normalize_text
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    ExtractionConfig,
)
from radius_intent.infrastructure.extraction.dedupe import (
    Entry,
    content_tokens,
    exact_key,
    jaccard,
    merge_duplicates,
)
from radius_intent.infrastructure.extraction.report import CriterionTrace

EXTRACTOR = DeterministicCriterionExtractor()
RESET = "Users can reset their password via an email link"


def test_jaccard_basics():
    a, b = frozenset("abc"), frozenset("abd")
    assert jaccard(a, b) == pytest.approx(0.5)
    assert jaccard(a, a) == 1.0
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_content_tokens_drop_stopwords_and_modals():
    assert content_tokens(normalize_text("Users MUST be able to reset")) == {
        "users",
        "reset",
    }
    assert exact_key("users can log in.") == exact_key(
        normalize_text("users  can LOG in")
    )


def test_spec_file_beats_pr_body_and_origins_are_recorded():
    spec = src(
        f'version: 1\ncriteria:\n  - id: C1\n    text: "{RESET}"\n    weight: 0.7\n',
        K.SPEC_FILE,
        ".radius/intent.yml",
    )
    body = src(f"## Acceptance Criteria\n- {RESET}\n- Emails expire after one hour\n")
    issue = src(f"## Requirements\n- {RESET}.\n", K.ISSUE, "o/r#7")
    report = EXTRACTOR.extract_sources([body, issue, spec])

    kinds = [c.origin.source.kind for c in report.criteria]
    assert kinds == [K.SPEC_FILE, K.PR_BODY]
    kept = report.criteria[0]
    assert kept.weight == 0.7 and kept.hints.label == "C1"
    (group,) = report.duplicates
    assert group.kept_id == kept.id
    assert [m.source.kind for m in group.merged] == [K.ISSUE, K.PR_BODY]
    assert all(m.similarity == 1.0 for m in group.merged)
    assert group.merged[0].span.slice(issue.text).startswith("Users can reset")


def test_priority_order_issue_over_body_over_title():
    title = src("Users must be able to reset their password by email", K.PR_TITLE, "t")
    body = src("Users should be able to reset their password by email.", K.PR_BODY, "b")
    issue = src("Users shall be able to reset their password by email.", K.ISSUE, "i")
    report = EXTRACTOR.extract_sources([title, body, issue])
    assert [c.origin.source.kind for c in report.criteria] == [K.ISSUE]
    assert len(report.duplicates[0].merged) == 2


def test_similarity_threshold_is_respected():
    a = src("Users must reset passwords by email link", K.ISSUE, "a")
    b = src("Users must reset passwords by email code", K.PR_BODY, "b")
    strict = DeterministicCriterionExtractor(ExtractionConfig(similarity_threshold=0.9))
    loose = DeterministicCriterionExtractor(ExtractionConfig(similarity_threshold=0.5))
    assert len(strict.extract_sources([a, b]).criteria) == 2
    assert len(loose.extract_sources([a, b]).criteria) == 1


def test_short_statements_merge_only_when_exact():
    a = src("## Acceptance Criteria\n- Login works\n- Logout works\n")
    assert len(EXTRACTOR.extract(a)) == 2


def test_same_source_exact_duplicates_merge_keeping_first():
    s = src("## Acceptance Criteria\n- Users can log in\n- users can  LOG in.\n")
    report = EXTRACTOR.extract_report(s)
    assert [c.text for c in report.criteria] == ["Users can log in"]
    assert report.duplicates[0].merged[0].text == "users can LOG in."


def test_tie_break_is_by_source_key_then_position():
    x = src("The api must return json for every request", K.ISSUE, "b")
    y = src("The api must return json for every request", K.ISSUE, "a")
    report = EXTRACTOR.extract_sources([x, y])
    assert [c.origin.source.source_id for c in report.criteria] == ["a"]


def test_duplicate_source_keys_read_once_with_warning():
    one = src("The api must work well", K.ISSUE, "same")
    two = src("The api must also work", K.ISSUE, "same")
    report = EXTRACTOR.extract_sources([two, one])
    assert len(report.criteria) == 1
    assert "duplicate_source" in {d.code for d in report.diagnostics}
    assert EXTRACTOR.extract_sources([one, two]) == report


def _naive_merge(entries, threshold):
    """Brute-force greedy reference for ``merge_duplicates``."""
    ordered = sorted(entries, key=lambda e: e.sort_key)
    kept: list[Entry] = []
    merged: dict[str, list[str]] = {}
    for entry in ordered:
        toks = content_tokens(entry.criterion.normalized_text)
        key = exact_key(entry.criterion.normalized_text)
        best, best_sim = None, 0.0
        for idx, other in enumerate(kept):
            if exact_key(other.criterion.normalized_text) == key:
                best, best_sim = idx, 1.0
                break
            otoks = content_tokens(other.criterion.normalized_text)
            if len(toks) >= 3 and len(otoks) >= 3:
                sim = jaccard(toks, otoks)
                if sim >= threshold and sim > best_sim:
                    best, best_sim = idx, sim
        if best is None:
            kept.append(entry)
            merged[entry.criterion.id] = []
        else:
            merged[kept[best].criterion.id].append(entry.criterion.id)
    return [e.criterion.id for e in kept], merged


def test_indexed_merge_matches_bruteforce_reference():
    rng = random.Random(7)
    vocab = [f"w{i}" for i in range(14)]
    entries = []
    for i in range(120):
        words = rng.sample(vocab, rng.randint(2, 9))
        text = f"- {' '.join(words)}\n"
        source = src("## Acceptance Criteria\n" + text, K.PR_BODY, f"s{i}")
        crit = EXTRACTOR.extract(source)[0]
        entries.append(Entry(crit, CriterionTrace(crit.id, "section_item")))
    for threshold in (0.5, 0.8, 1.0):
        kept, groups = merge_duplicates(entries, threshold)
        ref_kept, ref_merged = _naive_merge(entries, threshold)
        assert [e.criterion.id for e in kept] == ref_kept
        got = {g.kept_id: [m.criterion_id for m in g.merged] for g in groups}
        assert got == {k: v for k, v in ref_merged.items() if v}


def test_many_overlapping_statements_dedupe_in_reasonable_time():
    import time

    lines = "".join(
        f"- User {chr(97 + j % 26)} requests item{j} and widget{j % 5} under policy{j % 7}\n"
        for j in range(400)
    )
    sources = [
        src("## Acceptance Criteria\n" + lines, k, f"s{n}") for n, k in enumerate(K)
    ]
    start = time.perf_counter()
    report = EXTRACTOR.extract_sources(sources)
    assert time.perf_counter() - start < 15
    assert len(report.criteria) == 400
