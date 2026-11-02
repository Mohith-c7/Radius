"""EV-07: freshness binding, blob-level staleness, decay hook, audit partition."""

from __future__ import annotations

import hashlib
import random

import pytest
from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.factories import from_test
from radius_evidence.domain.freshness import (
    FreshnessConfig,
    apply_freshness,
    assess_staleness,
    bind_freshness,
    blob_hash,
    changed_covered_paths,
    is_valid_sha,
    partition_by_freshness,
)
from radius_evidence.domain.independence import classify_independence
from radius_evidence.domain.model import EvidenceItem

A = "a" * 40
B = "b" * 40


def make_item(test_id: str, head: str = A) -> EvidenceItem:
    return from_test(
        analysis_id="an1",
        repository_id="rp1",
        head_sha=head,
        test_id=test_id,
        outcome=Outcome.PASSED,
        collected_at="2026-11-02T10:00:00Z",
        independence=classify_independence(test_id),
    )


@pytest.mark.parametrize(
    ("bound", "current", "f", "reason"),
    [
        (A, A, 1.0, "current_head"),
        (A, B, 0.0, "stale_sha"),
        ("", A, 0.0, "unbound"),
        (None, A, 0.0, "unbound"),
        ("abc", A, 0.0, "unbound"),
        ("A" * 40, A, 0.0, "unbound"),  # uppercase is not a valid binding
        ("g" * 40, A, 0.0, "unbound"),
        (A + "0", A, 0.0, "unbound"),
    ],
)
def test_bind_freshness(bound: str | None, current: str, f: float, reason: str) -> None:
    info = bind_freshness(bound, current)
    assert (info.f, info.reason) == (f, reason)
    assert info.current_sha == current


@pytest.mark.parametrize(
    ("value", "ok"), [(A, True), ("", False), (None, False), ("1" * 39, False)]
)
def test_is_valid_sha(value: str | None, ok: bool) -> None:
    assert is_valid_sha(value) is ok


def test_blob_hash_matches_git() -> None:
    # `printf 'hello\n' | git hash-object --stdin`
    assert blob_hash("hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert blob_hash(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert blob_hash("x") == blob_hash(b"x")
    assert blob_hash("x") != hashlib.sha1(b"x").hexdigest()  # noqa: S324


def test_changed_covered_paths_splits_and_treats_missing_as_changed() -> None:
    changed, unchanged = changed_covered_paths(
        ["a.py", "b.py", "c.py", "a.py"],
        {"a.py": "1", "b.py": "2"},
        {"a.py": "1", "b.py": "9", "c.py": "3"},
    )
    assert changed == ("b.py", "c.py")
    assert unchanged == ("a.py",)


@pytest.mark.parametrize(
    ("bound", "blobs_old", "blobs_new", "f", "reason"),
    [
        (
            A,
            {"t.py": "1"},
            {"t.py": "1"},
            1.0,
            "current_head",
        ),  # same sha: blobs ignored
        (B, {"t.py": "1"}, {"t.py": "1"}, 0.0, "stale_sha"),  # decay off by default
    ],
)
def test_default_config_reproduces_binary_freshness(
    bound: str, blobs_old: dict, blobs_new: dict, f: float, reason: str
) -> None:
    rep = assess_staleness(
        bound, A, covered_paths=["t.py"], bound_blobs=blobs_old, current_blobs=blobs_new
    )
    assert (rep.info.f, rep.info.reason) == (f, reason)


@pytest.mark.parametrize(
    ("old", "new", "behind", "f", "reason"),
    [
        (
            {"t.py": "1", "s.py": "2"},
            {"t.py": "1", "s.py": "2"},
            1,
            0.8,
            "stale_sha_unchanged_covered",
        ),
        (
            {"t.py": "1", "s.py": "2"},
            {"t.py": "1", "s.py": "2"},
            2,
            0.64,
            "stale_sha_unchanged_covered",
        ),
        (
            {"t.py": "1", "s.py": "2"},
            {"t.py": "1", "s.py": "2"},
            0,
            0.8,
            "stale_sha_unchanged_covered",
        ),
        ({"t.py": "1", "s.py": "2"}, {"t.py": "1", "s.py": "X"}, 1, 0.0, "stale_sha"),
        ({"t.py": "1", "s.py": "2"}, {"t.py": "Y", "s.py": "2"}, 1, 0.0, "stale_sha"),
        ({"t.py": "1", "s.py": "2"}, {"t.py": "1"}, 1, 0.0, "stale_sha"),  # deleted
        ({}, {}, 1, 0.0, "stale_sha"),  # no blob knowledge
    ],
)
def test_decay_hook(old: dict, new: dict, behind: int, f: float, reason: str) -> None:
    rep = assess_staleness(
        B,
        A,
        covered_paths=["t.py", "s.py"],
        bound_blobs=old,
        current_blobs=new,
        commits_behind=behind,
        config=FreshnessConfig(decay_enabled=True),
    )
    assert rep.info.f == pytest.approx(f)
    assert rep.info.reason == reason


def test_decay_with_no_covered_paths_stays_stale() -> None:
    rep = assess_staleness(B, A, config=FreshnessConfig(decay_enabled=True))
    assert rep.info.f == 0.0


def test_changed_paths_are_reported_with_reasons() -> None:
    rep = assess_staleness(
        B,
        A,
        covered_paths=["t.py"],
        bound_blobs={"t.py": "1"},
        current_blobs={"t.py": "2"},
    )
    assert rep.changed_paths == ("t.py",)
    assert [r.code for r in rep.reasons] == ["covered_file_changed"]


def test_unbound_is_never_decayed() -> None:
    rep = assess_staleness(
        "",
        A,
        covered_paths=["t.py"],
        bound_blobs={"t.py": "1"},
        current_blobs={"t.py": "1"},
        config=FreshnessConfig(decay_enabled=True),
    )
    assert (rep.info.f, rep.info.reason) == (0.0, "unbound")


def test_unchanged_factor_is_clamped() -> None:
    rep = assess_staleness(
        B,
        A,
        covered_paths=["t.py"],
        bound_blobs={"t.py": "1"},
        current_blobs={"t.py": "1"},
        config=FreshnessConfig(decay_enabled=True, unchanged_factor=5.0),
    )
    assert rep.info.f == 1.0


def test_property_staleness_monotone() -> None:
    rng = random.Random(5)
    paths = [f"f{i}.py" for i in range(6)]
    cfg = FreshnessConfig(decay_enabled=True, unchanged_factor=rng.uniform(0.3, 0.95))
    for _ in range(100):
        old = {p: "1" for p in paths}
        order = rng.sample(paths, len(paths))
        new = dict(old)
        last_f = 2.0
        for step in range(len(paths) + 1):
            if step:
                new[order[step - 1]] = "changed"
            f = assess_staleness(
                B,
                A,
                covered_paths=paths,
                bound_blobs=old,
                current_blobs=new,
                config=cfg,
            ).info.f
            assert f <= last_f  # more changed files never raise f
            last_f = f
        prev = 2.0
        for behind in range(1, 6):
            f = assess_staleness(
                B,
                A,
                covered_paths=paths,
                bound_blobs=old,
                current_blobs=old,
                commits_behind=behind,
                config=cfg,
            ).info.f
            assert f <= prev
            prev = f


def test_factor_always_in_unit_interval() -> None:
    for behind in (0, 1, 3, 50):
        f = assess_staleness(
            B,
            A,
            covered_paths=["t.py"],
            bound_blobs={"t.py": "1"},
            current_blobs={"t.py": "1"},
            commits_behind=behind,
            config=FreshnessConfig(decay_enabled=True, unchanged_factor=0.9),
        ).info.f
        assert 0.0 <= f <= 1.0


def test_apply_freshness_and_partition_keep_audit_history() -> None:
    fresh = make_item("t1")
    stale = apply_freshness(make_item("t2"), B)
    assert fresh.freshness.f == 1.0
    assert (stale.freshness.f, stale.freshness.reason) == (0.0, "stale_sha")
    assert stale.head_sha == make_item("t2").head_sha  # binding itself is untouched
    usable, ignored = partition_by_freshness([fresh, stale])
    assert [i.subject_id for i in usable] == ["t1"]
    assert [i.subject_id for i in ignored] == ["t2"]


def test_apply_freshness_with_decay() -> None:
    item: EvidenceItem = make_item("t3", head=B)
    out = apply_freshness(
        item,
        A,
        covered_paths=["t.py"],
        bound_blobs={"t.py": "1"},
        current_blobs={"t.py": "1"},
        config=FreshnessConfig(decay_enabled=True),
    )
    assert out.freshness.f == pytest.approx(0.8)
