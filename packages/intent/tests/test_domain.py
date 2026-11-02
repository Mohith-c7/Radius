"""Table-driven tests for the intent domain model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from radius_intent.domain import (
    ALLOWED_TRANSITIONS,
    Criterion,
    CriterionState,
    DuplicateCriterionError,
    ExtractionMethod,
    IntentDomainError,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    InvalidCriterionError,
    InvalidProvenanceError,
    InvalidSnapshotError,
    InvalidSourceError,
    InvalidSpanError,
    InvalidStateTransitionError,
    InvalidWeightError,
    Provenance,
    SourceRef,
    Span,
    Testability,
    TestabilityAssessment,
    criterion_id,
    hash_text,
    normalize_text,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 11, 2, 12, 0)
TEXT = "Intro.\n- Users can reset their password\n- Emails are sent\n"


def make_source(
    source_id: str = "pr-1", kind=IntentSourceKind.PR_BODY, text: str = TEXT
) -> IntentSource:
    return IntentSource.from_text(source_id, kind, text, NOW)


def make_criterion(
    source: IntentSource | None = None, start: int = 9, end: int = 40, **kw
) -> Criterion:
    source = source or make_source()
    return Criterion.create(
        source,
        Span(source.source_id, start, end),
        extraction_method=ExtractionMethod.DETERMINISTIC,
        extractor_version="det-1",
        **kw,
    )


def make_snapshot(criteria=(), version=1, parent=None, sid="s1", sources=None):
    if sources is None:
        sources = (make_source().ref,)
    return IntentSnapshot(
        snapshot_id=sid,
        analysis_id="a1",
        version=version,
        created_at=NOW,
        criteria=tuple(criteria),
        sources=sources,
        parent_snapshot_id=parent,
    )


# --- Span ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_id", "start", "end"),
    [("", 0, 1), ("  ", 0, 1), ("s", -1, 3), ("s", 3, 3), ("s", 5, 2)],
)
def test_span_rejects_invalid(source_id, start, end):
    with pytest.raises(InvalidSpanError):
        Span(source_id, start, end)


def test_span_within_and_slice():
    span = Span("s", 1, 4)
    assert span.within("abcd") and span.slice("abcd") == "bcd"
    assert not span.within("abc")
    with pytest.raises(InvalidSpanError):
        span.slice("abc")


def test_span_is_frozen():
    with pytest.raises(FrozenInstanceError):
        Span("s", 0, 1).start = 2  # type: ignore[misc]


# --- SourceRef / Provenance / IntentSource ----------------------------------


@pytest.mark.parametrize(
    ("source_id", "digest"),
    [("", hash_text("x")), ("a", "nothex"), ("a", hash_text("x").upper())],
)
def test_source_ref_rejects_invalid(source_id, digest):
    with pytest.raises(InvalidSourceError):
        SourceRef(IntentSourceKind.ISSUE, source_id, digest)


def test_source_ref_key_ignores_hash():
    a = SourceRef(IntentSourceKind.ISSUE, "o/r#1", hash_text("a"))
    b = SourceRef(IntentSourceKind.ISSUE, "o/r#1", hash_text("b"))
    assert a.key == b.key == "issue:o/r#1"


@pytest.mark.parametrize(("when", "version"), [(NAIVE, "v1"), (NOW, ""), (NOW, "   ")])
def test_provenance_rejects_invalid(when, version):
    with pytest.raises(InvalidProvenanceError):
        Provenance(make_source().ref, when, ExtractionMethod.LLM, version)


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"source_id": " "},
        {"raw_text_hash": "zz"},
        {"fetched_at": NAIVE},
    ],
)
def test_source_rejects_invalid(kwargs):
    base = {
        "source_id": "s",
        "kind": IntentSourceKind.COMMENT,
        "text": "t",
        "raw_text_hash": hash_text("t"),
        "fetched_at": NOW,
    }
    with pytest.raises(InvalidSourceError):
        IntentSource(**{**base, **kwargs})


def test_source_from_text_hashes_raw_and_carries_flags():
    src = IntentSource.from_text(
        "s",
        IntentSourceKind.PR_TITLE,
        "clean",
        NOW,
        raw_text="clean<!-- hidden -->",
        truncated=True,
        suspicious_content_removed=True,
    )
    assert src.raw_text_hash == hash_text("clean<!-- hidden -->")
    assert src.truncated and src.suspicious_content_removed
    assert src.ref.key == "pr_title:s"
    default = make_source()
    assert not default.truncated and not default.suspicious_content_removed
    assert default.raw_text_hash == hash_text(TEXT)


def test_all_source_kinds_present():
    assert {k.value for k in IntentSourceKind} == {
        "pr_body", "pr_title", "issue", "commit_message",
        "spec_file", "agent_prompt", "comment",
    }  # fmt: skip


# --- identity ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Hello   World ", "hello world"),
        ("A\tB\nC", "a b c"),
        ("ＡＢＣ", "abc"),  # fullwidth -> NFKC
        ("ﬁle", "file"),  # ligature
        ("café", "café"),
        ("café", "café"),  # composed == decomposed
        ("re​set", "reset"),  # zero-width space
        ("a‮b", "ab"),  # bidi override
        ("STRASSE", "strasse"),
        ("Straße", "strasse"),  # casefold
        ("​ ‍", ""),
    ],
)
def test_normalize_text_table(raw, expected):
    assert normalize_text(raw) == expected


@pytest.mark.parametrize("raw", ["A  b", "café ﬁ", "x​y", ""])
def test_normalize_is_idempotent(raw):
    once = normalize_text(raw)
    assert normalize_text(once) == once


def test_criterion_id_deterministic_and_sensitive():
    base = criterion_id("must work", "pr_body:1")
    assert base == criterion_id("must work", "pr_body:1")
    assert base.startswith("crit_") and len(base) == 5 + 32
    assert base != criterion_id("must work", "pr_body:2")
    assert base != criterion_id("must work!", "pr_body:1")
    # field separator prevents boundary ambiguity
    assert criterion_id("b", "a:x") != criterion_id("x\x00b", "a")


def test_criterion_id_golden_value():
    # Pins the algorithm; change only together with CRITERION_ID_ALGO.
    assert criterion_id("a", "pr_body:1") == criterion_id("a", "pr_body:1")
    assert (
        criterion_id("a", "pr_body:1")
        == "crit_"
        + __import__("hashlib").sha256(b"crit-id-v1\x00pr_body:1\x00a").hexdigest()[:32]
    )


def test_unicode_equivalent_texts_share_id():
    src = make_source()
    a = make_criterion(src, text="Café  Menu")
    b = make_criterion(src, text="café menu")
    assert a.id == b.id


# --- Criterion --------------------------------------------------------------


def test_criterion_create_defaults():
    c = make_criterion()
    assert c.text == TEXT[9:40].strip()
    assert c.state is CriterionState.PROPOSED
    assert c.weight == 1.0 and c.testability is Testability.UNRATED
    assert c.origin.retrieved_at == NOW
    assert c.origin.extraction_method is ExtractionMethod.DETERMINISTIC
    assert c.id == criterion_id(c.normalized_text, c.origin.source.key)


def test_criterion_create_span_outside_source():
    with pytest.raises(InvalidSpanError):
        make_criterion(start=10, end=len(TEXT) + 1)


def test_criterion_create_span_wrong_source():
    src = make_source()
    with pytest.raises(InvalidSpanError):
        Criterion.create(
            src,
            Span("other", 0, 3),
            extraction_method=ExtractionMethod.HUMAN,
            extractor_version="h",
        )


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "​"])
def test_criterion_rejects_empty_text(text):
    with pytest.raises(InvalidCriterionError):
        make_criterion(text=text)


def test_criterion_span_slice_blank_is_rejected():
    src = make_source(text="ab   cd")
    with pytest.raises(InvalidCriterionError):
        make_criterion(src, start=2, end=5)


@pytest.mark.parametrize(
    "weight",
    [0, 0.0, -0.1, 1.0000001, 2, float("nan"), float("inf"), float("-inf")],
)
def test_weight_out_of_range(weight):
    with pytest.raises(InvalidWeightError):
        make_criterion(weight=weight)


@pytest.mark.parametrize("weight", [1e-9, 0.25, 0.5, 1, 1.0])
def test_weight_in_range(weight):
    assert make_criterion(weight=weight).weight == weight


def test_criterion_field_invariants():
    c = make_criterion()
    with pytest.raises(InvalidCriterionError):
        replace(c, id=" ")
    with pytest.raises(InvalidCriterionError):
        replace(c, normalized_text="WRONG")
    with pytest.raises(InvalidCriterionError):
        replace(c, testability_rationale="  ")
    with pytest.raises(InvalidSpanError):
        replace(c, span=Span("other", 0, 2))
    with pytest.raises(FrozenInstanceError):
        c.weight = 0.5  # type: ignore[misc]


_S = CriterionState


@pytest.mark.parametrize("src", list(_S))
@pytest.mark.parametrize("dst", list(_S))
def test_transition_table(src, dst):
    c = replace(make_criterion(), state=src)
    if dst in ALLOWED_TRANSITIONS[src]:
        assert c.transition_to(dst).state is dst
    else:
        with pytest.raises(InvalidStateTransitionError):
            c.transition_to(dst)


def test_transition_methods():
    c = make_criterion()
    assert c.confirm().state is _S.CONFIRMED
    rejected = c.reject()
    assert rejected.state is _S.REJECTED
    assert rejected.reopen().state is _S.PROPOSED
    with pytest.raises(InvalidStateTransitionError):
        rejected.confirm()
    with pytest.raises(InvalidStateTransitionError):
        c.reopen()
    assert c.state is _S.PROPOSED  # original untouched


def test_edit_keeps_identity_and_renormalizes():
    c = make_criterion()
    e = c.edit("  New   WORDING ")
    assert e.state is _S.EDITED and e.id == c.id and e.span == c.span
    assert e.normalized_text == "new wording"
    assert e.edit("again").state is _S.EDITED
    with pytest.raises(InvalidCriterionError):
        c.edit("   ")
    with pytest.raises(InvalidStateTransitionError):
        c.reject().edit("x")


def test_with_weight_and_testability():
    c = make_criterion()
    assert c.with_weight(0.4).weight == 0.4
    with pytest.raises(InvalidWeightError):
        c.with_weight(0)
    t = c.with_testability(Testability.VAGUE, "no observable behavior")
    assert t.testability is Testability.VAGUE
    assert t.testability_rationale == "no observable behavior"
    with pytest.raises(InvalidCriterionError):
        c.with_testability(Testability.TESTABLE, " ")


def test_testability_assessment():
    assert TestabilityAssessment(Testability.TESTABLE).rationale is None
    with pytest.raises(InvalidCriterionError):
        TestabilityAssessment(Testability.VAGUE, "")


# --- Snapshot ---------------------------------------------------------------


def test_snapshot_happy_path_and_get():
    src = make_source()
    c1 = make_criterion(src, 9, 40)
    c2 = make_criterion(src, 41, 58)
    snap = make_snapshot([c1, c2])
    assert snap.criteria == (c1, c2)
    assert snap.get(c2.id) == c2 and snap.get("nope") is None


def test_snapshot_normalizes_lists_to_tuples():
    src = make_source()
    snap = IntentSnapshot(
        "s",
        "a",
        1,
        NOW,
        [make_criterion(src)],
        [src.ref],  # type: ignore[arg-type]
    )
    assert isinstance(snap.criteria, tuple) and isinstance(snap.sources, tuple)


def test_snapshot_duplicate_criterion_ids():
    c = make_criterion()
    with pytest.raises(DuplicateCriterionError):
        make_snapshot([c, c])
    assert issubclass(DuplicateCriterionError, IntentDomainError)


@pytest.mark.parametrize(
    ("version", "parent"),
    [(0, None), (-1, "p"), (1, "p"), (2, None), (2, ""), (2, "s1")],
)
def test_snapshot_version_parent_rules(version, parent):
    with pytest.raises(InvalidSnapshotError):
        make_snapshot(version=version, parent=parent)


@pytest.mark.parametrize(
    "kwargs", [{"snapshot_id": " "}, {"analysis_id": ""}, {"created_at": NAIVE}]
)
def test_snapshot_field_invariants(kwargs):
    base = {
        "snapshot_id": "s1",
        "analysis_id": "a1",
        "version": 1,
        "created_at": NOW,
        "criteria": (),
        "sources": (),
    }
    with pytest.raises(InvalidSnapshotError):
        IntentSnapshot(**{**base, **kwargs})


def test_snapshot_source_refs_must_cover_criteria():
    c = make_criterion()
    with pytest.raises(InvalidSnapshotError):
        make_snapshot([c], sources=())
    stale = SourceRef(c.origin.source.kind, c.origin.source.source_id, hash_text("x"))
    with pytest.raises(InvalidSnapshotError):
        make_snapshot([c], sources=(stale,))
    dup = (c.origin.source, c.origin.source)
    with pytest.raises(InvalidSnapshotError):
        make_snapshot([], sources=dup)


def test_snapshot_diff_added_removed_changed():
    src = make_source()
    a = make_criterion(src, 9, 40)
    b = make_criterion(src, 41, 58)
    c = make_criterion(src, 0, 6)
    old = make_snapshot([a, b])
    new = old.next_version("s2", NOW, (a.confirm(), c), (src.ref,))
    assert new.version == 2 and new.parent_snapshot_id == "s1"
    assert new.analysis_id == old.analysis_id
    d = old.diff(new)
    assert d.added == (c,)
    assert d.removed == (b,)
    assert len(d.changed) == 1
    assert d.changed[0].before == a and d.changed[0].after == a.confirm()
    assert not d.is_empty


def test_snapshot_diff_identical_is_empty():
    c = make_criterion()
    snap = make_snapshot([c])
    assert snap.diff(snap).is_empty


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.with_weight(0.5),
        lambda c: c.with_testability(Testability.TESTABLE),
        lambda c: c.edit("different"),
        lambda c: c.reject(),
    ],
)
def test_snapshot_diff_detects_each_change(mutate):
    c = make_criterion()
    old = make_snapshot([c])
    new = old.next_version("s2", NOW, (mutate(c),), old.sources)
    assert [x.after.id for x in old.diff(new).changed] == [c.id]


def test_snapshot_is_immutable():
    snap = make_snapshot()
    with pytest.raises(FrozenInstanceError):
        snap.version = 3  # type: ignore[misc]
