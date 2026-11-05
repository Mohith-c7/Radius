"""EV-08: q(e, c) combiner, link mapping and EvidenceQuality rows (table-driven)."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest
from radius_evidence.domain.config import LinkMapping, QualityConfig
from radius_evidence.domain.enums import (
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.model import (
    EvidenceItem,
    FlakyInfo,
    FreshnessInfo,
    IndependenceInfo,
)
from radius_evidence.domain.quality import (
    FAILING_STATUSES,
    STATUS_COUNTED,
    combine_quality,
    criterion_link_strength,
    evidence_quality_row,
    exercise_link_strength,
    flaky_factor,
    gated,
    item_quality,
    link_strength,
    tamper_penalty,
)

SHA = "a" * 40
CFG = QualityConfig()
MAP = LinkMapping()


def make_item(
    *,
    outcome: Outcome | None = Outcome.PASSED,
    factor: float = 0.8,
    fresh: float = 1.0,
    flaky: FlakyInfo | None = None,
    kind: EvidenceKind = EvidenceKind.TEST_OUTCOME,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_1",
        kind=kind,
        source=EvidenceSource.CI_UPLOAD,
        analysis_id="a",
        repository_id="r",
        head_sha=SHA,
        subject_id="tests/t.py::test_x",
        path="tests/t.py",
        symbol_ids=(),
        criterion_ids=(),
        outcome=outcome,
        duration_ms=1,
        features=None,
        severity=None,
        rule_id=None,
        independence=IndependenceInfo(
            AuthoredBy.UNKNOWN, IndependenceBasis.CHANGED_IN_PR, factor
        ),
        flaky=flaky or FlakyInfo(flagged=False),
        freshness=FreshnessInfo(
            SHA, SHA, fresh, "current_head" if fresh else "stale_sha"
        ),
        reasons=(),
        collected_at="2026-11-02T10:00:00Z",
    )


def row(item: EvidenceItem | None = None, **kw):
    args = {"a_static": 1.0, "w_cs": 1.0, "w_st": 0.9, "r_ct": 1.0, "symbol_id": "sym"}
    args.update(kw)
    return evidence_quality_row(item or make_item(), "c1", **args)


@pytest.mark.parametrize(
    ("w", "expected"),
    [
        (0.0, 0.0),
        (0.19, 0.0),
        (0.1999, 0.0),
        (0.2, 0.5),
        (0.3, 0.75),
        (0.35, 0.875),
        (0.4, 1.0),
        (0.41, 1.0),
        (0.91, 1.0),
        (1.0, 1.0),
    ],
)
def test_criterion_link_strength_boundaries(w: float, expected: float) -> None:
    assert criterion_link_strength(w, MAP) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("w", "expected"),
    [(0.0, 0.0), (0.25, 0.0), (0.4999, 0.0), (0.5, 0.5), (0.9, 0.9), (1.0, 1.0)],
)
def test_exercise_link_strength_boundaries(w: float, expected: float) -> None:
    assert exercise_link_strength(w, MAP) == pytest.approx(expected)


def test_link_strength_is_the_product_through_the_gate() -> None:
    link = link_strength(0.35, 0.9, 0.8, MAP)
    assert (link.l_cs, link.l_st, link.r_ct) == pytest.approx((0.875, 0.9, 0.8))
    assert link.l == pytest.approx(0.875 * 0.9 * 0.8)


@pytest.mark.parametrize("r", [-0.01, 1.01])
def test_link_strength_rejects_out_of_range_relevance(r: float) -> None:
    with pytest.raises(ValueError, match="r_ct"):
        link_strength(1.0, 1.0, r, MAP)


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ((), 0.0),
        (("info",), 0.0),
        (("low",), 0.2),
        (("medium",), 0.5),
        (("high",), 1.0),
        (("critical",), 1.0),
        (("HIGH",), 1.0),
        (("medium", "medium"), 0.75),
        (("low", "medium"), 0.6),
        (("low", "low"), 0.36),
        (("critical", "low"), 1.0),
        (("info", "info"), 0.0),
    ],
)
def test_tamper_penalty_noisy_or(severities: tuple[str, ...], expected: float) -> None:
    assert tamper_penalty(severities, CFG) == pytest.approx(expected)


def test_tamper_penalty_unknown_severity_raises() -> None:
    with pytest.raises(ValueError, match="severity"):
        tamper_penalty(["catastrophic"], CFG)


@pytest.mark.parametrize(
    ("flaky", "expected"),
    [
        (FlakyInfo(False), 1.0),
        (FlakyInfo(True, "rerun"), 0.0),
        (FlakyInfo(True, "rerun", 0.1), 0.0),
        (FlakyInfo(True, "history"), 1.0),
        (FlakyInfo(True, "history", 0.2), 0.8),
        (FlakyInfo(True, "history", 0.5), 0.5),
        (FlakyInfo(True, "history", 0.9), 0.5),
        (FlakyInfo(False, None, 0.3), 0.7),
        (FlakyInfo(False, None, 0.0), 1.0),
        (FlakyInfo(False, None, -1.0), 1.0),
    ],
)
def test_flaky_factor(flaky: FlakyInfo, expected: float) -> None:
    assert flaky_factor(flaky, CFG) == pytest.approx(expected)


def _q(a, i=1.0, f=1.0, fl=1.0, tp=0.0, cfg=CFG):
    return combine_quality(
        a, independence=i, freshness=f, flaky_f=fl, tamper_p=tp, config=cfg
    )


@pytest.mark.parametrize(
    ("a", "i", "f", "fl", "tp", "q"),
    [
        (1.0, 0.8, 1.0, 1.0, 0.0, 0.48),  # design: strong test added in the PR
        (1.0, 1.0, 1.0, 1.0, 0.0, 0.60),  # capped
        (0.8, 1.0, 1.0, 1.0, 0.0, 0.60),
        (0.6, 1.0, 1.0, 1.0, 0.0, 0.60),
        (0.5, 1.0, 1.0, 1.0, 0.0, 0.50),
        (0.35, 0.8, 1.0, 1.0, 0.0, 0.28),
        (0.25, 0.8, 1.0, 1.0, 0.0, 0.20),
        (0.2, 0.8, 1.0, 1.0, 0.0, 0.16),
        (0.0, 1.0, 1.0, 1.0, 0.0, 0.0),
        (1.0, 0.6, 1.0, 1.0, 0.0, 0.36),
        (1.0, 0.8, 0.0, 1.0, 0.0, 0.0),  # stale
        (1.0, 0.8, 1.0, 0.0, 0.0, 0.0),  # flaky rerun
        (1.0, 0.8, 1.0, 0.5, 0.0, 0.24),
        (1.0, 0.8, 1.0, 1.0, 1.0, 0.0),  # tamper high nullifies
        (1.0, 0.8, 1.0, 1.0, 0.5, 0.24),
        (1.0, 0.8, 1.0, 1.0, 0.2, 0.384),
        (1.0, 0.0, 1.0, 1.0, 0.0, 0.0),
        (1.0, 1.0, 0.5, 1.0, 0.0, 0.30),
    ],
)
def test_combine_quality_golden(a, i, f, fl, tp, q) -> None:
    assert _q(a, i, f, fl, tp).q == pytest.approx(q)


def test_cap_static_is_configurable() -> None:
    low = QualityConfig(cap_static=0.4)
    assert _q(1.0, 1.0, cfg=low).q == pytest.approx(0.4)
    assert _q(1.0, 1.0, cfg=low).d_eff == pytest.approx(0.4)
    assert _q(0.3, 1.0, cfg=low).d_eff == pytest.approx(0.3)


@pytest.mark.parametrize(
    "kw", [{"a": 1.1}, {"a": -0.1}, {"i": 1.5}, {"f": -1.0}, {"fl": 2.0}, {"tp": 1.2}]
)
def test_combine_quality_rejects_out_of_range(kw) -> None:
    with pytest.raises(ValueError):
        _q(**{"a": 0.5, **kw})


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"a": 0.0}, "zero_a_static"),
        ({"a": 0.9}, "capped_static"),
        ({"i": 0.8}, "independence_discount"),
        ({"f": 0.0}, "stale_evidence"),
        ({"fl": 0.0}, "flaky_rerun"),
        ({"fl": 0.7}, "flaky_history"),
        ({"tp": 1.0}, "tamper_nullified"),
        ({"tp": 0.5}, "tamper_penalty"),
    ],
)
def test_reason_codes(kw, code) -> None:
    codes = {r.code for r in _q(**{"a": 0.5, **kw}).reasons}
    assert code in codes


def test_clean_item_has_no_reasons() -> None:
    assert _q(0.5).reasons == ()


def test_monotone_in_every_factor() -> None:
    rng = random.Random(7)

    def q(v):
        return _q(v[0], v[1], v[2], v[3], v[4]).q

    for _ in range(200):
        base = [rng.random() for _ in range(5)]
        for idx in range(5):
            worse = list(base)
            # a, i, f, flaky_f: smaller is worse; tamper_p (idx 4): larger is worse
            worse[idx] = (
                base[idx] * rng.random()
                if idx < 4
                else base[idx] + (1 - base[idx]) * rng.random()
            )
            assert q(worse) <= q(base) + 1e-12


def test_q_never_exceeds_cap_or_one() -> None:
    rng = random.Random(3)
    for _ in range(200):
        r = _q(rng.random(), rng.random(), rng.random(), rng.random(), rng.random())
        assert 0.0 <= r.q <= CFG.cap_static


def test_item_quality_reads_the_item_factors() -> None:
    item = make_item(factor=0.6, fresh=1.0, flaky=FlakyInfo(True, "history", 0.2))
    r = item_quality(item, 1.0, ["medium"], CFG)
    assert r.q == pytest.approx(0.6 * 0.6 * 0.8 * 0.5)
    assert r.i == 0.6 and r.flaky_f == pytest.approx(0.8) and r.tamper_penalty == 0.5


def test_item_quality_deterministic() -> None:
    item = make_item()
    assert item_quality(item, 0.7, ["low"], CFG) == item_quality(
        item, 0.7, ["low"], CFG
    )


# ---- EvidenceQuality row and gating -------------------------------------


def test_row_golden_matches_design_term() -> None:
    r = row()
    assert r.status == STATUS_COUNTED
    assert r.q == pytest.approx(0.48) and r.l == pytest.approx(0.9)
    assert r.term == pytest.approx(0.432)
    assert r.path is not None and r.path.symbol_id == "sym" and r.group_symbol == "sym"
    assert r.cap_static == 0.6 and r.d_mut is None


@pytest.mark.parametrize(
    ("kw", "status"),
    [
        ({"r_ct": 0.0}, gated("no_criterion_test_edge")),
        ({"w_st": 0.49}, gated("test_link_below_min")),
        ({"w_st": 0.25}, gated("test_link_below_min")),
        ({"w_cs": 0.19}, gated("criterion_link_below_min")),
        ({"w_cs": 0.0}, gated("criterion_link_below_min")),
        ({"a_static": 0.0}, gated("zero_quality")),
        ({"tamper_severities": ["high"]}, gated("zero_quality")),
        ({"tamper_severities": ["medium"]}, STATUS_COUNTED),
        ({"w_cs": 0.2}, STATUS_COUNTED),
        ({"w_st": 0.5}, STATUS_COUNTED),
    ],
)
def test_row_gates(kw, status) -> None:
    assert row(**kw).status == status


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (Outcome.FAILED, "gated:outcome_failed"),
        (Outcome.ERROR, "gated:outcome_error"),
        (Outcome.SKIPPED, "gated:outcome_skipped"),
        (Outcome.FLAKY, "gated:outcome_flaky"),
        (Outcome.NOT_RUN, "gated:outcome_not_run"),
        (None, "gated:outcome_none"),
        (Outcome.PASSED, STATUS_COUNTED),
    ],
)
def test_row_outcome_gates(outcome, status) -> None:
    r = row(make_item(outcome=outcome))
    assert r.status == status
    assert (r.term > 0) is (status == STATUS_COUNTED)


def test_failed_item_with_zero_quality_still_marks_contradiction() -> None:
    r = row(make_item(outcome=Outcome.FAILED), tamper_severities=["high"])
    assert r.status in FAILING_STATUSES and r.q == 0.0 and r.term == 0.0


def test_failed_item_without_link_is_not_attached() -> None:
    assert (
        row(make_item(outcome=Outcome.FAILED), r_ct=0.0).status not in FAILING_STATUSES
    )
    assert (
        row(make_item(outcome=Outcome.FAILED), w_cs=0.1).status not in FAILING_STATUSES
    )


def test_lambda_kind_scales_term_and_zero_gates() -> None:
    half = QualityConfig(lambda_kind={"test_outcome": 0.5})
    assert row(quality=half).term == pytest.approx(0.216)
    assert row(make_item(kind=EvidenceKind.TAMPER_FINDING)).status == gated(
        "zero_quality"
    )


def test_row_uses_custom_link_mapping() -> None:
    m = LinkMapping(link_sat_cs=0.8)
    r = row(w_cs=0.4, mapping=m)
    assert r.l_cs == pytest.approx(0.5)


def test_row_roundtrips_through_json() -> None:
    r = row()
    assert type(r).from_json(r.to_json()) == r


def test_stale_item_row_is_gated_and_f_zero() -> None:
    r = row(make_item(fresh=0.0))
    assert r.f == 0.0 and r.status == gated("zero_quality")


def test_row_is_deterministic() -> None:
    assert row() == row()
    assert replace(row(), term=0.0) != row()
