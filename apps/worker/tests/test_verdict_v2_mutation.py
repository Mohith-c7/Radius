"""Mutation evidence in Verdict v2 (contract 5): producer, Stage B scoring, safety, honesty.

Hand-computed values use fixture 08 (one function ``validate_password``, four criteria):
the static rows are q = 0.6 * 0.8 = 0.48 (strong assertion, capped) with link l = 0.9, so
the static term is 0.432; the second test of a symbol group is discounted by 0.7.
Wilson 95% lower bounds: 8/10 -> 0.490157, 4/10 -> 0.168178, 10/10 -> 0.722460, 0/10 -> 0.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from radius_api.schemas.verdict_v2 import VerdictV2Out
from radius_evidence.domain.inputs import MutantInput, MutationInput, StageAInput
from radius_evidence.domain.versions import CONTRACT_VERSION
from radius_github.verdict_v2.markdown import (
    DISCLAIMER,
    MUTATION_DISCLAIMER,
    render_check_run,
    render_comment,
)
from radius_github.verdict_v2.view import VerdictV2View
from radius_shared.database.base import Base
from radius_shared.database.models import Organization, Repository
from radius_shared.verdict_v2_payload import StoredVerdict
from radius_shared.verdict_v2_payload import build_payload as shared_build_payload
from radius_testing.infrastructure import result_matching as _rm
from radius_worker.verdict_v2 import mutation as mut
from radius_worker.verdict_v2.collect import (
    CollectLimits,
    Producers,
    VerdictStageACollector,
)
from radius_worker.verdict_v2.scoring import ScoringPipeline
from radius_worker.verdict_v2.sources import IntentFacts, StaticIntent
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
SCHEMA = json.loads((ROOT / "docs/research/design/verdict_v2.schema.json").read_text(encoding="utf-8"))
CLOCK = lambda: datetime(2026, 11, 3, tzinfo=UTC)  # noqa: E731
FIXTURE = "08_multi_criterion_partial_evidence"
SYM = "python:src/validators.py::validate_password#function@981c887bac80"
T8 = "tests/test_validators.py::test_accepts_eight_characters"
T7 = "tests/test_validators.py::test_rejects_seven_characters"
TD = "tests/test_validators.py::test_rejects_missing_digit"
TU = "tests/test_validators.py::test_uppercase_rule_runs"


def _load_loader():
    spec = importlib.util.spec_from_file_location(
        "vs01_loader_mut", ROOT / "benchmarks" / "fixtures" / "verdict_v2" / "loader.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LOADER = _load_loader()


def pipeline() -> ScoringPipeline:
    return ScoringPipeline(mode="shadow", clock=CLOCK)


def mutants(kills: dict[str, int]) -> tuple[MutantInput, ...]:
    """10 decided mutants of SYM: ``kills`` maps test id -> how many (from the first) it kills."""

    out = []
    for i in range(10):
        killers = tuple(t for t, k in kills.items() if i < k)
        out.append(
            MutantInput(
                f"m{i}", SYM, "src/validators.py", 20 + i, "ROR" if i % 2 else "AOR",
                "killed" if killers else "survived", killers,
            )
        )
    return tuple(out)


def mutation_input(kills: dict[str, int], **kw) -> MutationInput:
    muts = mutants(kills)
    return MutationInput(
        status="measured", mutants=muts, symbol_tests={SYM: (T8, T7, TD, TU)}, generated=10,
        sampled=10, **kw,
    )


def with_mutation(m: MutationInput | None, fixture: str = FIXTURE):
    sb = LOADER.stage_b(fixture, mode="gold")
    return dataclasses.replace(sb, stage_a=dataclasses.replace(sb.stage_a, mutation=m))


def crit(payload, cid):
    return next(c for c in payload["criteria"] if c["criterion_id"] == cid)


def item(c, test):
    return next(i for i in c["items"] if i["test_id"] == test)


# ------------------------------------------------------------------ flag off

def test_flag_off_payload_has_no_mutation_fields_and_static_basis() -> None:
    p = pipeline().score_full(with_mutation(None)).payload
    assert p["contract_version"] == CONTRACT_VERSION == "verdict-v2-contract-5"
    assert "mutation" not in p and p["evidence_basis"] == "static_only"
    for c in p["criteria"]:
        assert "mutation" not in c and "evidence_basis" not in c
        assert "mutation_measured" not in c["flags"] and "static_only" in c["flags"]
        for i in c["items"]:
            assert "basis" not in i and "mutation_n" not in i
    assert p["presentation"]["disclaimer"].startswith("Alpha: static evidence only")


def test_flag_off_digest_is_independent_of_the_new_field() -> None:
    a = pipeline().score_full(with_mutation(None))
    sb = LOADER.stage_b(FIXTURE, mode="gold")
    again = pipeline().score_full(sb)
    assert a.bundle["inputs_digest"] == again.bundle["inputs_digest"]
    # a present mutation input is a real input: it changes the digest and records a version
    m = pipeline().score_full(with_mutation(mutation_input({TD: 10})))
    assert m.bundle["inputs_digest"] != a.bundle["inputs_digest"]
    assert m.payload["justification"]["versions"]["mutation"] == "mutation-evidence-1"
    assert "mutation" not in a.payload["justification"]["versions"]


# ------------------------------------------------------------------ scoring, hand computed

def test_measured_rows_replace_the_static_cap_and_support_follows() -> None:
    # T7 kills 8 of 10 mutants, T8 kills 4, TD kills all 10, TU kills none
    p = pipeline().score_full(with_mutation(mutation_input({T7: 8, T8: 4, TD: 10}))).payload
    c1 = crit(p, "C1")
    seven, eight = item(c1, T7), item(c1, T8)
    assert seven["basis"] == "mutation" and seven["mutation_n"] == 10 and seven["mutation_killed"] == 8
    assert seven["d_eff"] == pytest.approx(0.490157, abs=1e-5)
    assert seven["q"] == pytest.approx(0.490157 * 0.8, abs=1e-5)
    assert seven["term"] == pytest.approx(0.490157 * 0.8 * 0.9, abs=1e-5)
    assert eight["d_eff"] == pytest.approx(0.168178, abs=1e-5)
    # noisy-OR with the 0.7 discount of the second item in the symbol group
    t7, t8 = 0.490157 * 0.8 * 0.9, 0.168178 * 0.8 * 0.9
    assert c1["S"] == pytest.approx(1 - (1 - t7) * (1 - 0.7 * t8), abs=1e-4)  # 0.4078
    assert c1["S"] < 0.603763  # a strong static pair that kills little is LOWERED
    assert c1["state"] != "proven"
    # C2: its only test kills everything: 10/10 -> 0.722460 > the static cap 0.6 (raised)
    c2 = crit(p, "C2")
    assert item(c2, TD)["d_eff"] == pytest.approx(0.722460, abs=1e-5)
    assert c2["S"] == pytest.approx(0.722460 * 0.8 * 0.9, abs=1e-4)  # 0.5202 > 0.432
    # C3: the uppercase test detects nothing: lcb 0 -> q 0, gated, support 0
    c3 = crit(p, "C3")
    assert item(c3, TU)["d_eff"] == 0.0 and item(c3, TU)["status"] == "gated:zero_quality"
    assert c3["S"] == 0.0


def test_criterion_union_survivors_basis_and_flags() -> None:
    p = pipeline().score_full(with_mutation(mutation_input({T7: 8, T8: 4, TD: 10}))).payload
    assert p["evidence_basis"] == p["summary"]["evidence_basis"] == "static_and_mutation"
    c1 = crit(p, "C1")
    assert c1["evidence_basis"] == c1["mutation"]["basis"] == "mutation_measured"
    assert "mutation_measured" in c1["flags"] and "static_only" not in c1["flags"]
    mu = c1["mutation"]
    assert (mu["n_mutants"], mu["killed"], mu["tests_measured"], mu["tests_total"]) == (10, 8, 2, 2)
    assert mu["d_union"] == pytest.approx(0.8) and mu["d_union_lcb"] == pytest.approx(0.490157, abs=1e-5)
    assert mu["survivors"] == [
        {"mutant_id": "m8", "path": "src/validators.py", "line": 28, "operator": "AOR"},
        {"mutant_id": "m9", "path": "src/validators.py", "line": 29, "operator": "ROR"},
    ]
    assert mu["d_reach"] is None
    c4 = crit(p, "C4")  # no linked test: nothing measured, static basis
    assert c4["evidence_basis"] == "static_only" and "mutation_measured" not in c4["flags"]
    run = p["mutation"]
    assert (run["status"], run["decided"], run["killed"]) == ("measured", 10, 10)
    assert "mutation-evidence-1" == p["justification"]["versions"]["mutation"]
    assert p["presentation"]["disclaimer"].startswith("Alpha: static assertion strength plus sampled")


def test_unmeasured_run_changes_no_score_and_is_labelled_honestly() -> None:
    base = pipeline().score_full(with_mutation(None)).payload
    for m in (
        MutationInput(status="unmeasured", reason="sandbox_disabled"),
        MutationInput(status="unmeasured", reason="budget_insufficient"),
        # fewer decided mutants than the minimum for every test: static cap stays
        MutationInput(
            status="measured", symbol_tests={SYM: (T8, T7, TD, TU)},
            mutants=tuple(MutantInput(f"x{i}", SYM, "src/validators.py", 5, "ROR", "killed", (T7,))
                          for i in range(4)),
        ),
    ):
        p = pipeline().score_full(with_mutation(m)).payload
        assert p["verdict"] == base["verdict"] and p["evidence_basis"] == "static_only"
        for c, b in zip(p["criteria"], base["criteria"], strict=True):
            assert (c["state"], c["S"]) == (b["state"], b["S"])
            assert c["evidence_basis"] == "static_only" and "mutation_measured" not in c["flags"]
            assert [i["d_eff"] for i in c["items"]] == [i["d_eff"] for i in b["items"]]
        assert p["mutation"]["status"] == m.status


def test_partial_basis_when_only_some_counted_tests_are_measured() -> None:
    # only T7 has a measured sample (8/10); T8 is not part of the matrix at all
    muts = mutants({T7: 8})
    m = MutationInput(status="measured", mutants=muts, symbol_tests={SYM: (T7,)})
    c1 = crit(pipeline().score_full(with_mutation(m)).payload, "C1")
    assert c1["evidence_basis"] == "mutation_partial"
    assert {"mutation_measured", "static_only"} <= set(c1["flags"])
    assert item(c1, T8)["d_eff"] == 0.6 and item(c1, T7)["d_eff"] == pytest.approx(0.490157, abs=1e-5)


def test_equivalent_and_non_decided_mutants_never_enter_the_denominator() -> None:
    muts = list(mutants({T7: 8}))
    muts += [
        MutantInput("e1", SYM, "src/validators.py", 40, "AOR", "equivalent_suspect", (), True),
        MutantInput("t1", SYM, "src/validators.py", 41, "ROR", "timeout"),
        MutantInput("f1", SYM, "src/validators.py", 42, "CON", "flaky"),
        MutantInput("s1", SYM, "src/validators.py", 43, "CON", "skipped_for_budget"),
    ]
    m = MutationInput(status="measured", mutants=tuple(muts), symbol_tests={SYM: (T7, T8)})
    p = pipeline().score_full(with_mutation(m)).payload
    c1 = crit(p, "C1")
    assert item(c1, T7)["mutation_n"] == 10
    assert c1["mutation"]["excluded"] == {"equivalent_suspect": 1, "flaky": 1, "skipped_for_budget": 1, "timeout": 1}
    assert all(s["mutant_id"] not in {"e1", "t1", "f1", "s1"} for s in c1["mutation"]["survivors"])


# ------------------------------------------------------------------ never a pass from mutation

def random_matrix(rng: random.Random) -> MutationInput:
    tests = (T8, T7, TD, TU)
    muts = []
    for i in range(rng.randrange(0, 14)):
        status = rng.choice(["killed", "killed", "survived", "timeout", "flaky", "error"])
        killers = tuple(t for t in tests if rng.random() < 0.6) if status == "killed" else ()
        if status == "killed" and not killers:
            killers = (rng.choice(tests),)
        muts.append(
            MutantInput(f"r{i}", SYM, "src/validators.py", 20 + i, rng.choice(["ROR", "AOR", "CON"]),
                        status, killers, rng.random() < 0.1)
        )
    return MutationInput(
        status=rng.choice(["measured", "measured", "unmeasured"]), mutants=tuple(muts),
        symbol_tests={SYM: tests}, min_decided=rng.choice([1, 5]),
    )


def test_property_failing_ci_stays_failed_and_contradicted_whatever_mutation_says() -> None:
    sb = LOADER.stage_b(FIXTURE, mode="gold")
    first = next(c for c in sb.cases if c.test_id == T7)
    failed_case = dataclasses.replace(first, outcome=type(first.outcome)("failed"))
    cases = tuple(failed_case if c is first else c for c in sb.cases)
    rng = random.Random(2026)
    for _ in range(60):
        m = random_matrix(rng)
        sa = dataclasses.replace(sb.stage_a, mutation=m)
        p = pipeline().score_full(dataclasses.replace(sb, stage_a=sa, cases=cases)).payload
        assert p["verdict"] == "failed" and crit(p, "C1")["state"] == "contradicted"
        assert item(crit(p, "C1"), T7)["term"] == 0.0


def test_property_survivors_alone_never_raise_support_or_create_a_verdict() -> None:
    """All mutants survive (or are excluded): support can only go down or stay, never up."""

    base = pipeline().score_full(with_mutation(None)).payload
    rng = random.Random(5)
    for _ in range(40):
        n = rng.randrange(0, 15)
        muts = tuple(
            MutantInput(f"s{i}", SYM, "src/validators.py", 20 + i, "ROR",
                        rng.choice(["survived", "timeout", "flaky", "equivalent_suspect"]), (), False)
            for i in range(n)
        )
        m = MutationInput(status="measured", mutants=muts, symbol_tests={SYM: (T8, T7, TD, TU)},
                          min_decided=rng.choice([1, 5]))
        p = pipeline().score_full(with_mutation(m)).payload
        for c, b in zip(p["criteria"], base["criteria"], strict=True):
            assert c["S"] <= b["S"] + 1e-9
            if b["state"] != "proven":
                assert c["state"] != "proven"
        assert p["verdict"] != "failed"  # survivors never create a failure either


def test_property_mutation_never_creates_failed_or_contradicted() -> None:
    base = pipeline().score_full(with_mutation(None)).payload
    assert base["verdict"] != "failed"
    rng = random.Random(99)
    for _ in range(80):
        p = pipeline().score_full(with_mutation(random_matrix(rng))).payload
        assert p["verdict"] != "failed"
        assert all(c["state"] != "contradicted" for c in p["criteria"])


def test_all_kills_matrix_never_makes_a_tampered_fixture_greener() -> None:
    sb = LOADER.stage_b("04_test_tampering", mode="gold")
    static = pipeline().score_full(sb).payload["verdict"]
    syms = sorted({e.symbol_id for e in sb.stage_a.symbol_test})
    tests = sorted({e.test_id for e in sb.stage_a.symbol_test})
    muts = tuple(
        MutantInput(f"k{i}", syms[0], "src/x.py", i + 1, "ROR", "killed", tuple(tests)) for i in range(10)
    )
    m = MutationInput(status="measured", mutants=muts, symbol_tests={s: tuple(tests) for s in syms})
    p = pipeline().score_full(
        dataclasses.replace(sb, stage_a=dataclasses.replace(sb.stage_a, mutation=m))
    ).payload
    order = ["failed", "needs_review", "insufficient_evidence", "verified"]
    assert order.index(p["verdict"]) <= order.index(static)  # tamper rules still decide


# ------------------------------------------------------------------ contract surfaces

def test_payload_conforms_to_schema_api_model_and_shared_reader() -> None:
    scored = pipeline().score_full(with_mutation(mutation_input({T7: 8, T8: 4, TD: 10})))
    p = scored.payload
    assert _validate(p, SCHEMA) == []
    out = VerdictV2Out.model_validate(p)
    assert out.evidence_basis == "static_and_mutation" and out.mutation.decided == 10
    assert out.criteria[0].mutation.survivors[0].mutant_id == "m8"
    # the stored-bundle reader (what the API serves) produces the same mutation facts
    stored = StoredVerdict(
        row_id="r", organization_id="o", analysis_id=p["analysis_id"], head_sha=p["head_sha"],
        revision=1, inputs_digest="d", status="ok", mode="shadow", verdict=p["verdict"],
        pending=p["pending"], reason_code=None, algo_version=p["algo_version"], profile=p["profile"],
        config_digest="c", bundle=json.loads(json.dumps(scored.bundle)),
        justification=p["justification"], error_detail=None, fallback=None, published_at=None,
        published_digest=None, publish_error=None, computed_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    served = shared_build_payload(stored)
    assert served["evidence_basis"] == "static_and_mutation"
    assert served["presentation"]["disclaimer"].startswith("Alpha: static assertion strength plus")
    assert served["mutation"] == p["mutation"]
    for a, b in zip(served["criteria"], p["criteria"], strict=True):
        assert a.get("mutation") == b.get("mutation") and a.get("evidence_basis") == b.get("evidence_basis")
        assert [i.get("basis") for i in a["items"]] == [i.get("basis") for i in b["items"]]
    assert _validate(served, SCHEMA) == []


def test_flag_off_served_payload_is_unchanged_in_shape() -> None:
    scored = pipeline().score_full(with_mutation(None))
    p = scored.payload
    stored = StoredVerdict(
        row_id="r", organization_id="o", analysis_id=p["analysis_id"], head_sha=p["head_sha"],
        revision=1, inputs_digest="d", status="ok", mode="shadow", verdict=p["verdict"],
        pending=p["pending"], reason_code=None, algo_version=p["algo_version"], profile=p["profile"],
        config_digest="c", bundle=json.loads(json.dumps(scored.bundle)),
        justification=p["justification"], error_detail=None, fallback=None, published_at=None,
        published_digest=None, publish_error=None, computed_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    served = shared_build_payload(stored)
    assert "mutation" not in served and all("mutation" not in c for c in served["criteria"])
    assert served["evidence_basis"] == "static_only"


def test_stage_b_recompute_from_the_stored_bundle_is_identical() -> None:
    sb = with_mutation(mutation_input({T7: 8, T8: 4, TD: 10}))
    first = pipeline().score_full(sb)
    again = StageAInput.from_dict(json.loads(json.dumps(first.bundle["stage_a"])))
    assert again == sb.stage_a
    second = pipeline().score_full(dataclasses.replace(sb, stage_a=again))
    assert json.dumps(first.bundle, sort_keys=True) == json.dumps(second.bundle, sort_keys=True)


def test_renderer_wording_is_honest_and_shows_basis_and_gaps() -> None:
    p = pipeline().score_full(with_mutation(mutation_input({T7: 8, T8: 4, TD: 10}))).payload
    body = render_comment(VerdictV2View.from_payload(p))
    assert MUTATION_DISCLAIMER in body and DISCLAIMER not in body
    assert "mutation-measured (10 mutants)" in body
    assert "static assertion strength only" in body  # the unmeasured criteria say so
    assert "Gaps found by mutation" in body and "`src/validators.py`:28, operator AOR" in body
    assert "no mutation testing" not in body
    assert "proof" in body  # "not a proof of correctness" stays in the text
    for banned in ("proven correct", "guarantee", "verified correct"):
        assert banned not in body.lower()
    check = render_check_run(VerdictV2View.from_payload(p))
    assert "static + sampled mutation evidence" in check.title
    # flag off: wording is the old static text, no mutation vocabulary
    off = render_comment(VerdictV2View.from_payload(pipeline().score_full(with_mutation(None)).payload))
    assert DISCLAIMER in off and "mutation-measured" not in off and "Gaps found" not in off


def test_untrusted_survivor_path_is_escaped_in_the_comment() -> None:
    m = mutation_input({T7: 8, T8: 4, TD: 10})
    bad = dataclasses.replace(m.mutants[8], path="src/<script>alert(1)</script>|x.py")
    m = dataclasses.replace(m, mutants=(*m.mutants[:8], bad, m.mutants[9]))
    body = render_comment(VerdictV2View.from_payload(pipeline().score_full(with_mutation(m)).payload))
    assert r"`src/<script>alert(1)</script>\|x.py`" in body  # inert code span, pipe escaped


# ------------------------------------------------------------------ Stage A: collector / producer

SYM_ID = "python:src/a.py::f#function@abc"
TEST_ID = "tests/test_a.py::test_f"
SHA = "c" * 40


def _criterion():
    return NS(id="C1", text="f returns one", state="confirmed", weight=1.0,
              testability="behavioral_testable", hints=NS(paths=(), tests=()))


def _changed(**kw):
    base = {"symbol_id": SYM_ID, "path": "src/a.py", "qualified_name": "f", "kind": "function",
            "language": "python", "change_kind": NS(value="modified_body"), "is_behavioral": True,
            "new_range": NS(start=1, end=3), "old_range": None}
    return NS(**{**base, **kw})


def _producers(**over) -> Producers:
    links = NS(links=(NS(symbol_id=SYM_ID, test_id=TEST_ID, score=0.9,
                         kind=NS(value="direct_call"), depth=None),), algo_version="link-combine-v1")
    base = dict(
        symbol_changes=lambda c: NS(symbols=(_changed(),), truncated=False,
                                    algo_version="symbol-changes-v1", to_json=lambda: "{}"),
        tamper=lambda cs, c: NS(findings=(), waived=(), unanalyzable=(), truncated=False,
                                rule_errors=(), catalog_version="tamper-rules-v1"),
        link_criteria=lambda crit, cs, c, srcs: NS(
            links=(NS(criterion_id="C1", symbol_id=SYM_ID, linker="combined", score=0.8, rank=1,
                      evidence=()),), by_linker=(), algo_version="criterion-symbol-links-v1"),
        link_tests=lambda srcs, targets: links,
        assertions=lambda files, srcs, lk, targets: NS(algo_version="x", to_dict=lambda: {
            "assertions": [], "tests": []}),
        relevance=lambda crit, cl, tl, srcs, aset: [{"criterion_id": "C1", "test_id": TEST_ID, "weight": 0.7}],
        read_sources=lambda root: ({"src/a.py": "def f(): return 1\n"}, False),
    )
    base.update(over)
    return Producers(**base)


class _Sha:
    def head_sha(self, analysis_id, command):  # noqa: ARG002
        return SHA


def _collect(producers: Producers, limits: CollectLimits | None = None) -> StageAInput:
    col = VerdictStageACollector(
        StaticIntent(IntentFacts(criteria=(_criterion(),), commit_messages=())),
        head_sha_port=_Sha(), producers=producers, limits=limits,
    )
    return col.collect(uuid4(), NS(repository_id=uuid4(), repository_path=Path("."), diff_text="d",
                                   base_ref=None, head_ref=None))


def test_flag_off_collector_runs_no_mutation_and_adds_nothing() -> None:
    sa = _collect(_producers())
    assert sa.mutation is None and sa.degraded == ()


def test_producer_receives_changed_linked_symbols_and_result_is_stored() -> None:
    seen = []

    def producer(req):
        seen.append(req)
        return MutationInput(status="measured", generated=3)

    sa = _collect(_producers(mutation=producer))
    assert sa.mutation.status == "measured" and sa.degraded == ()
    (req,) = seen
    targets = mut.select_targets(req)
    assert [(t.symbol_id, t.path, t.ranges, t.tests) for t in targets] == [
        (SYM_ID, "src/a.py", ((1, 3),), (TEST_ID,))
    ]


def test_producer_failure_degrades_never_crashes_and_is_not_blocking() -> None:
    def boom(req):
        raise RuntimeError("secret detail must not leak")

    sa = _collect(_producers(mutation=boom))
    assert sa.mutation.status == "unmeasured" and sa.mutation.reason == "producer_failed"
    assert "producer_failed:mutation" in sa.degraded and "truncated" not in sa.degraded


def test_producer_timeout_is_its_own_marker_and_does_not_block_the_verdict() -> None:
    def slow(req):
        time.sleep(0.5)
        return MutationInput(status="measured")

    sa = _collect(_producers(mutation=slow), CollectLimits(mutation_timeout_s=0.05))
    assert "producer_timeout:mutation" in sa.degraded and "truncated" not in sa.degraded
    assert sa.mutation.status == "unmeasured"


def test_unmeasured_result_leaves_a_marker_and_no_linked_tests_skips_the_producer() -> None:
    sa = _collect(_producers(mutation=lambda r: MutationInput(status="unmeasured", reason="sandbox_disabled")))
    assert "mutation_unmeasured:sandbox_disabled" in sa.degraded
    called = []
    no_tests = _producers(
        mutation=lambda r: called.append(r),
        link_tests=lambda srcs, targets: NS(links=(), algo_version="link-combine-v1"),
    )
    sa = _collect(no_tests)
    assert called == [] and sa.mutation.reason == "no_linked_tests"


def test_select_targets_skips_tests_pseudo_removed_and_unlinked_symbols() -> None:
    def sym(sid, path, qn, kind="function", change="modified_body", test=False):
        return mut.SymbolInput(sid, path, qn, kind, "python", change, True, test, qn == "<module>")

    changeset = NS(symbols=(
        NS(symbol_id="ok", new_range=NS(start=1, end=5)),
        NS(symbol_id="in_test", new_range=NS(start=1, end=5)),
        NS(symbol_id="pseudo", new_range=NS(start=1, end=5)),
        NS(symbol_id="removed", new_range=None),
        NS(symbol_id="unlinked", new_range=NS(start=1, end=5)),
        NS(symbol_id="lowlink", new_range=NS(start=1, end=5)),
    ))
    syms = (
        sym("ok", "src/a.py", "f"), sym("in_test", "tests/test_a.py", "test_x", test=True),
        sym("pseudo", "src/a.py", "<module>", kind="module"),
        sym("removed", "src/a.py", "g", change="removed"), sym("unlinked", "src/a.py", "h"),
        sym("lowlink", "src/a.py", "i"),
    )
    cs = tuple(mut.CriterionSymbolEdgeInput("C1", s, 0.8, 1) for s in ("ok", "in_test", "pseudo", "removed", "lowlink"))
    st = tuple(
        mut.SymbolTestEdgeInput(s, f"tests/t.py::t_{s}", sc, "direct_call")
        for s, sc in (("ok", 0.9), ("in_test", 0.9), ("pseudo", 0.9), ("removed", 0.9),
                      ("unlinked", 0.9), ("lowlink", 0.3))
    )
    req = mut.request_from_stage_a(Path("."), changeset, syms, cs, st)
    assert [t.symbol_id for t in mut.select_targets(req)] == ["ok"]


class _FakeSandbox:
    """Stands in for ContainerSandboxRunner: reads the *copy* it is handed, like a container."""

    def __init__(self, config, ready=True):
        self.config = config
        self.ready = ready
        self.workspaces: list[Path] = []

    def check_ready(self):
        if not self.ready:
            raise RuntimeError("daemon down")
        return "docker"

    def run_collecting(self, plan, ws, artifacts=()):
        ws = Path(ws)
        self.workspaces.append(ws)
        (_, args), = plan.command_plan
        ids = [a for a in args if "::" in a]
        text = (ws / "src" / "f.py").read_text()
        cases = []
        for tid in ids:
            fails = ">=" in text and tid.endswith("test_a")  # the ROR mutant is caught by test_a only
            name = tid.rsplit("::", 1)[-1]
            cases.append(f'<testcase classname="tests.test_f" name="{name}">' + ("<failure/>" if fails else "") + "</testcase>")
        xml = ("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>").encode()
        return NS(output=""), {"0/junit.xml": xml}


def _tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "f.py").write_text("def f(a, b):\n    if a > b:\n        return a - b\n    return 0\n")
    (tmp_path / "tests" / "test_f.py").write_text("def test_a(): pass\ndef test_b(): pass\n")
    return tmp_path


def _request(repo: Path):
    sid = "python:src/f.py::f#function@1"
    cs = NS(symbols=(NS(symbol_id=sid, new_range=NS(start=1, end=4)),))
    sym = mut.SymbolInput(sid, "src/f.py", "f", "function", "python", "modified_body", True, False, False)
    return mut.request_from_stage_a(
        repo, cs, (sym,), (mut.CriterionSymbolEdgeInput("C1", sid, 0.8, 1),),
        (mut.SymbolTestEdgeInput(sid, "tests/test_f.py::test_a", 0.9, "direct_call"),
         mut.SymbolTestEdgeInput(sid, "tests/test_f.py::test_b", 0.9, "direct_call")),
    ), sid


def _settings(**kw):
    base = dict(mutation_enabled=True, mutation_max_mutants=50, mutation_wall_clock_seconds=600.0,
                mutation_mutant_timeout_seconds=60.0)
    base.update(kw)
    return NS(**base)


@pytest.mark.skipif(
    _rm._safe_et is None, reason="defusedxml missing: JUnit reports cannot be parsed in this env"
)
def test_sandbox_producer_runs_mutants_only_in_copies_and_never_writes_the_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    from radius_testing.infrastructure.sandbox_runner import SandboxConfig
    from radius_testing.mutation import SandboxMutantRunner

    # the real adapter derives a per-run sandbox for the timeout; keep the fake in the loop
    monkeypatch.setattr(SandboxMutantRunner, "_sandbox_with_timeout", lambda self, t: self._sandbox)

    repo = _tmp_repo(tmp_path)
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    sandbox = _FakeSandbox(SandboxConfig(timeout_seconds=30))
    req, sid = _request(repo)
    out = mut.SandboxMutationProducer(_settings(mutation_max_mutants=50), sandbox, image_digest=lambda s: "")(req)
    assert out.status == "measured", out
    assert before == {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert sandbox.workspaces and all(w.resolve() != repo.resolve() for w in sandbox.workspaces)
    assert all(not str(w).startswith(str(repo)) for w in sandbox.workspaces)
    ror = next(m for m in out.mutants if m.operator == "ROR")
    assert ror.status == "killed" and ror.killed_by == ("tests/test_f.py::test_a",)
    assert next(m for m in out.mutants if m.operator == "CON").status == "survived"
    assert out.symbol_tests[sid] == ("tests/test_f.py::test_a", "tests/test_f.py::test_b")
    assert out.image == "" and out.cache_hits == 0  # no digest: no cache


def test_sandbox_not_ready_degrades_to_unmeasured(tmp_path: Path) -> None:
    from radius_testing.infrastructure.sandbox_runner import SandboxConfig

    req, _ = _request(_tmp_repo(tmp_path))
    out = mut.SandboxMutationProducer(_settings(), _FakeSandbox(SandboxConfig(), ready=False))(req)
    assert (out.status, out.reason) == ("unmeasured", "sandbox_not_ready")


def test_factory_flag_off_returns_none_and_sandbox_disabled_is_a_stub(monkeypatch) -> None:
    assert mut.create_mutation_producer(NS(mutation_enabled=False)) is None
    monkeypatch.setenv("RADIUS_MUTATION_ALLOW_LOCAL", "1")  # must make no difference in the worker
    from radius_testing.mutation import runner as runner_mod

    def forbidden(*a, **k):
        raise AssertionError("the local runner must never be constructed in the worker")

    monkeypatch.setattr(runner_mod.SubprocessLocalRunner, "__init__", forbidden)
    settings = NS(mutation_enabled=True, test_execution_mode="disabled", execute_tests=False,
                  environment=NS(value="development"), allow_unsafe_execution=False)
    stub = mut.create_mutation_producer(settings)
    out = stub(None)
    assert (out.status, out.reason) == ("unmeasured", "sandbox_disabled")
    unsafe = NS(mutation_enabled=True, test_execution_mode="unsafe_in_process", execute_tests=True,
                environment=NS(value="development"), allow_unsafe_execution=True)
    assert mut.create_mutation_producer(unsafe)(None).reason == "sandbox_disabled"


def test_factory_sandbox_mode_builds_the_hardened_sandbox_without_reruns(monkeypatch) -> None:
    from radius_testing.infrastructure import ContainerSandboxRunner
    from radius_testing.infrastructure.sandbox_runner import build_container_argv

    settings = NS(
        mutation_enabled=True, mutation_max_mutants=50, mutation_wall_clock_seconds=600.0,
        mutation_mutant_timeout_seconds=60.0, test_execution_mode="sandbox", execute_tests=False,
        environment=NS(value="development"), allow_unsafe_execution=False,
        test_timeout_seconds=600, sandbox_image="img:1", sandbox_runtime="docker",
        sandbox_memory="1g", sandbox_cpus="1.0", sandbox_pids_limit=256, sandbox_tmpfs_size="256m",
        sandbox_nofile_limit=1024, sandbox_max_file_size_bytes=1024, sandbox_max_output_bytes=2048,
        sandbox_seccomp_profile="", test_reruns=3,
    )
    producer = mut.create_mutation_producer(settings)
    assert isinstance(producer, mut.SandboxMutationProducer)
    sandbox = producer._sandbox
    assert isinstance(sandbox, ContainerSandboxRunner) and sandbox.config.image == "img:1"
    argv = " ".join(build_container_argv(
        sandbox.config, runtime_path="docker", container_name="radius-sbx-x",
        workspace_dir=Path("/w"), results_dir=Path("/r"), command=["pytest"],
    ))
    assert "--network none" in argv and "--read-only" in argv and "--cap-drop ALL" in argv
    assert sandbox._rerun.reruns == 0  # a failing mutant is a kill, not a flake to repeat


# ------------------------------------------------------------------ SQL cache

def _cache_env():
    from radius_shared.database import verdict_v2 as _models  # noqa: F401  (registers the table)

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        org = Organization(name="A", github_installation_id=1, github_installation_status="active")
        org2 = Organization(name="B", github_installation_id=2, github_installation_status="active")
        from radius_shared.database import enums as e

        def repo(o, n):
            return Repository(organization=o, github_repository_id=n, name=f"r{n}", owner="o",
                              default_branch="main", clone_url="https://example.invalid/o/r.git",
                              visibility=e.RepositoryVisibility.PRIVATE, status=e.RepositoryStatus.CONNECTED)

        r1, r2, r3 = repo(org, 10), repo(org, 11), repo(org2, 12)
        s.add_all([org, org2, r1, r2, r3])
        s.flush()
        ids = (org.id, r1.id, r2.id, org2.id, r3.id)
        s.commit()
    return factory, ids


def test_sql_cache_stores_final_results_only_and_is_namespaced() -> None:
    from radius_testing.mutation import MutantOutcome

    factory, (org, r1, r2, org2, r3) = _cache_env()
    now = [datetime(2026, 11, 3, tzinfo=UTC)]
    c1 = mut.SqlMutationCache(factory, org, r1, clock=lambda: now[0])
    key = "k" * 64
    assert key not in c1
    c1[key] = MutantOutcome("m", "killed", frozenset({"t::b", "t::a"}))
    hit = c1[key]
    assert hit.status == "killed" and hit.killed_by == frozenset({"t::a", "t::b"}) and hit.cached
    c1["s" * 64] = MutantOutcome("m", "survived")
    c1["x" * 64] = MutantOutcome("m", "timeout")
    c1["y" * 64] = MutantOutcome("m", "flaky")
    assert ("s" * 64) in c1 and ("x" * 64) not in c1 and ("y" * 64) not in c1
    # another repository of the same organization, and another organization: no hit
    assert key not in mut.SqlMutationCache(factory, org, r2)
    assert key not in mut.SqlMutationCache(factory, org2, r3)
    # old rows are pruned on the next write
    now[0] = datetime(2026, 12, 20, tzinfo=UTC)
    fresh = mut.SqlMutationCache(factory, org, r1, clock=lambda: now[0])
    fresh["n" * 64] = MutantOutcome("m", "survived")
    assert key not in fresh and ("n" * 64) in fresh


def test_sql_cache_errors_act_as_misses_never_raise() -> None:
    from radius_testing.mutation import MutantOutcome

    def broken():
        raise RuntimeError("db down")

    cache = mut.SqlMutationCache(broken, uuid4(), uuid4())
    assert ("a" * 64) not in cache
    cache["a" * 64] = MutantOutcome("m", "killed", frozenset({"t"}))  # no exception
    with pytest.raises(KeyError):
        cache["a" * 64]


# ------------------------------------------------------------------ helpers

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _validate(value, schema, path="$"):
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = False
        for n in names:
            if n == "number":
                ok |= isinstance(value, (int, float)) and not isinstance(value, bool)
            elif n == "integer":
                ok |= isinstance(value, int) and not isinstance(value, bool)
            else:
                ok |= isinstance(value, _TYPES[n])
        if not ok:
            return [*errors, f"{path}: bad type {type(value).__name__}"]
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += _validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        errors += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errors += _validate(v, props[k], f"{path}.{k}")
            elif isinstance(extra, dict):
                errors += _validate(v, extra, f"{path}.{k}")
    return errors
