"""VS-01: the generated Verdict v2 input bundles validate, cover the fixtures and are stable."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "benchmarks" / "fixtures" / "verdict_v2"
INTENT = ROOT / "benchmarks" / "fixtures" / "intent"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("verdict_v2_make_fixtures_under_test", ROOT / "scripts" / "verdict_v2_make_fixtures.py")
bundles = _load("verdict_v2_bundle_loader_under_test", OUT / "loader.py")

from radius_evidence.domain.config import DEFAULT_ASSERTION_SCORES  # noqa: E402
from radius_evidence.domain.enums import Outcome  # noqa: E402
from radius_evidence.domain.inputs import StageAInput, StageBInput  # noqa: E402

NAMES = list(gen.ALL_FIXTURES)
EXPECTATIONS = {
    f["fixture"]: f
    for f in json.loads((OUT / "fixture_expectations.json").read_text(encoding="utf-8"))["fixtures"]
}
ORIGINS = {"real", "derived", "hand_built"}
DELETED_AT_HEAD = "tests/test_stock.py::test_reserve_more_than_stock_raises"
SKIPPED_AT_HEAD = "tests/test_stock.py::test_reserve_rejects_non_positive"


def _expected(name: str) -> dict:
    return json.loads((INTENT / name / "expected.json").read_text(encoding="utf-8"))


def _a_static(feature: dict) -> float:
    kinds = [a["kind"] for a in feature["assertions"]]
    if not kinds:
        return DEFAULT_ASSERTION_SCORES["no_assertion"]
    return max(DEFAULT_ASSERTION_SCORES[k] for k in kinds)


def test_all_eight_bundles_exist() -> None:
    assert bundles.fixture_names() == sorted(NAMES)
    assert set(NAMES) == set(EXPECTATIONS)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("mode", bundles.MODES)
def test_bundle_validates_against_input_contracts(name: str, mode: str) -> None:
    raw = bundles.load_bundle(name)
    assert raw["schema"] == gen.SCHEMA
    stage_a = bundles.stage_a(name, mode)
    assert isinstance(stage_a, StageAInput)
    # exact round trip through the frozen contract: no field is dropped or invented
    assert stage_a.to_dict() == raw["modes"][mode]["stage_a"]
    assert re.fullmatch(r"[0-9a-f]{40}", stage_a.head_sha)
    uuid.UUID(stage_a.analysis_id)
    uuid.UUID(stage_a.repository_id)
    sym_ids = {s.symbol_id for s in stage_a.symbols}
    assert len(sym_ids) == len(stage_a.symbols)
    crit_ids = {c.criterion_id for c in stage_a.criteria}
    for e in stage_a.criterion_symbol:
        assert e.criterion_id in crit_ids and e.symbol_id in sym_ids
    for e in stage_a.symbol_test:
        assert e.symbol_id in sym_ids
    for e in stage_a.criterion_test:
        assert e.criterion_id in crit_ids
    for scenario in raw["stage_b"]:
        assert scenario in bundles.SCENARIOS
        sb = bundles.stage_b(name, mode, scenario)
        assert isinstance(sb, StageBInput)
        assert sb.stage_a == stage_a
        failed = sum(1 for c in sb.cases if c.outcome in (Outcome.FAILED, Outcome.ERROR))
        assert sb.ci_failed_cases == failed


@pytest.mark.parametrize("name", NAMES)
def test_covers_all_criteria_of_the_fixture(name: str) -> None:
    exp = _expected(name)
    for mode in bundles.MODES:
        stage_a = bundles.stage_a(name, mode)
        assert [c.criterion_id for c in stage_a.criteria] == [c["id"] for c in exp["criteria"]]
        assert [c.text for c in stage_a.criteria] == [c["text"] for c in exp["criteria"]]
    gold = bundles.stage_a(name, "gold")
    assert {e.criterion_id for e in gold.criterion_symbol} == {c["id"] for c in exp["criteria"]}
    want = {(link["criterion"], t) for link in exp["links"] for t in link["tests"]}
    assert {(e.criterion_id, e.test_id) for e in gold.criterion_test} == want
    assert {e.test_id for e in gold.symbol_test} == {t for _, t in want}
    # auto mode keeps whatever the real linkers emit; a criterion may legitimately get no link
    # (design 7.3: 05 C2 and 06 C2 find no candidate), but never an unknown criterion id
    auto = bundles.stage_a(name, "auto")
    assert {e.criterion_id for e in auto.criterion_symbol} <= {c["id"] for c in exp["criteria"]}
    assert auto.criterion_symbol


@pytest.mark.parametrize("name", NAMES)
def test_gold_symbols_are_resolved_to_changed_symbols(name: str) -> None:
    exp = _expected(name)
    gold = bundles.stage_a(name, "gold")
    by_id = {s.symbol_id: s for s in gold.symbols}
    for link in exp["links"]:
        path, _, qn = link["symbol"].partition("::")
        edge = next(e for e in gold.criterion_symbol if e.criterion_id == link["criterion"])
        sym = by_id[edge.symbol_id]
        assert sym.path == path
        # module constants map to <module> (design 7.3 disagreement 5)
        assert sym.qualified_name in (qn, "<module>")
        assert (edge.score, edge.rank) == (1.0, 1)


@pytest.mark.parametrize("name", NAMES)
def test_expected_tamper_facts_are_present(name: str) -> None:
    exp = _expected(name)
    wanted = EXPECTATIONS[name].get("expected_tamper", [])
    for mode in bundles.MODES:
        stage_a = bundles.stage_a(name, mode)
        got = sorted((t.rule_id, t.severity) for t in stage_a.tamper)
        assert got == sorted((w["rule_id"], w["severity"]) for w in wanted)
        for f in exp["tamper_findings"]:
            hit = [
                t
                for t in stage_a.tamper
                if t.rule_id == f["rule"]
                and t.path == f["file"]
                and (f.get("test") is None or t.test_id == f["test"])
            ]
            assert len(hit) == 1, f
            assert hit[0].severity == f.get("assumed_severity", hit[0].severity)
        assert stage_a.tamper_unanalyzable == ()
        assert stage_a.tamper_waived == 0
    if not wanted:
        assert exp["tamper_findings"] == []


@pytest.mark.parametrize("name", NAMES)
def test_outcomes_match_expected_json(name: str) -> None:
    exp = _expected(name)
    for scenario, outcomes in exp["test_outcomes"].items():
        sb = bundles.stage_b(name, "gold", scenario)
        assert {c.test_id: c.outcome.value for c in sb.cases} == outcomes
        assert sb.results_received and sb.uploads == 1 and not sb.flaky_test_ids
        for c in sb.cases:
            assert c.raw_file and c.raw_name and c.test_id.endswith(c.raw_name)
    head = bundles.stage_b(name, "gold", "head")
    gold_tests = {e.test_id for e in head.stage_a.criterion_test}
    reported = {c.test_id for c in head.cases}
    missing = {t for t in gold_tests if t not in reported}
    assert missing == ({DELETED_AT_HEAD} if name == "04_test_tampering" else set())


@pytest.mark.parametrize("name", NAMES)
def test_assertion_strength_matches_expected_bands(name: str) -> None:
    exp = _expected(name)
    features = {f.test_id: f.to_dict() for f in bundles.stage_a(name, "gold").assertions}
    linked = {t for link in exp["links"] for t in link["tests"]}
    for row in exp["evidence_quality"]:
        feature = features.get(row["test"])
        if feature is None:  # deleted at head: nothing to score
            assert row["band"] == "none"
            continue
        score = _a_static(feature)
        if row["band"] == "strong":
            assert score >= 0.8, row
        elif row["band"] == "weak":
            assert 0.0 < score <= 0.4, row
        elif row["test"] in linked:
            # alpha scores isinstance-only at 0.2 (type_check), below any support threshold
            assert score <= 0.2 or feature["has_skip_marker"], row
        # band "none" on an unlinked test is about relevance, not assertion strength
    skipped = {t for t, f in features.items() if f["has_skip_marker"]}
    assert skipped == ({SKIPPED_AT_HEAD} if name == "04_test_tampering" else set())


def test_scope_creep_unlinked_symbols_are_listed() -> None:
    name = "05_scope_creep"
    gold = bundles.stage_a(name, "gold")
    linked = {e.symbol_id for e in gold.criterion_symbol}
    unlinked = sorted(
        f"{s.path}::{s.qualified_name}"
        for s in gold.symbols
        if s.is_behavioral and not s.is_test and s.symbol_id not in linked
    )
    assert unlinked == sorted(EXPECTATIONS[name]["unlinked_behavioral_symbols"])


@pytest.mark.parametrize("name", NAMES)
def test_tests_added_in_the_pr_are_flagged(name: str) -> None:
    stage_a = bundles.stage_a(name, "gold")
    assert stage_a.changed_test_ids <= {f.test_id for f in stage_a.assertions}
    assert stage_a.changed_test_ids  # every fixture PR touches at least one test function


@pytest.mark.parametrize("name", NAMES)
def test_provenance_is_complete(name: str) -> None:
    raw = bundles.load_bundle(name)
    required = {
        "ids", "criteria", "symbols", "assertions", "tamper", "criterion_symbol",
        "symbol_test", "criterion_test", "changed_test_ids", "stage_b",
    }
    for mode, block in raw["modes"].items():
        prov = block["provenance"]
        assert required <= set(prov)
        assert {p["origin"] for p in prov.values()} <= ORIGINS
        assert prov["symbols"]["origin"] == "real"
        assert prov["assertions"]["origin"] == "hand_built"
        want = "hand_built" if mode == "gold" else "real"
        assert prov["criterion_symbol"]["origin"] == want
        assert prov["symbol_test"]["origin"] == want


def test_fixture_06_documents_the_registry_variant() -> None:
    raw = bundles.load_bundle("06_hallucinated_dependency")
    assert [t["check"] for t in raw["tamper"]["findings"]] == ["registry_missing"]
    variant = raw["tamper_variants"]["no_registry"]["findings"]
    assert [t["rule_id"] for t in variant] == ["T012"]
    assert variant[0]["check"] != "registry_missing"


def test_generation_is_deterministic_and_matches_committed_files() -> None:
    first = gen.generate_all()
    second = gen.generate_all()
    assert first == second
    for name, text in first.items():
        committed = (OUT / name / "inputs.json").read_text(encoding="utf-8")
        assert committed.replace("\r\n", "\n") == text
        assert text.endswith("\n") and "\r" not in text


def test_check_mode_exits_zero_on_a_clean_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert gen.main(["--check"]) == 0
    assert "ok:" in capsys.readouterr().out


def test_check_mode_reports_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = tmp_path / "verdict_v2"
    for name in NAMES:
        (fake / name).mkdir(parents=True)
        text = (OUT / name / "inputs.json").read_text(encoding="utf-8")
        (fake / name / "inputs.json").write_text(text, encoding="utf-8", newline="\n")
    target = fake / NAMES[0] / "inputs.json"
    text = target.read_text(encoding="utf-8").replace('"weight": 1.0', '"weight": 0.5', 1)
    target.write_text(text, encoding="utf-8", newline="\n")
    monkeypatch.setattr(gen, "OUT_DIR", fake)
    assert gen.main(["--check"]) == 1
    assert "DRIFT" in capsys.readouterr().err
