"""EV-02: engine behavior (determinism, ids, config, waivers, robustness, performance)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from textwrap import dedent

import pytest
from radius_analysis.symbol_changes import (
    DictSnapshot,
    ExtractionOptions,
    extract_symbol_changes,
)
from radius_analysis.symbol_changes.testing import make_diff
from radius_analysis.tamper import (
    CATALOG_VERSION,
    BaseRule,
    Family,
    RuleRegistry,
    Severity,
    TamperConfig,
    TamperConfigError,
    analyze_tampering,
    default_registry,
)
from radius_analysis.tamper.model import CheckSpec, RuleDoc

sys.path.insert(0, str(Path(__file__).parent))
from tamper_support import analyze, keys  # noqa: E402

SRC = "def price(n):\n    return n * 2\n"
TEST_BASE = dedent(
    """
    import pytest
    from shop import price


    def test_a():
        assert price(2) == 4


    def test_b():
        assert price(3) == 6
    """
).lstrip()
TAMPERED = TEST_BASE.replace("price(2) == 4", "price(2) is not None").replace(
    "def test_b", '@pytest.mark.skip\ndef test_b'
)
BASE = {"src/shop.py": SRC, "tests/test_shop.py": TEST_BASE}
HEAD = {"src/shop.py": SRC, "tests/test_shop.py": TAMPERED}


def test_report_is_deterministic_and_serializable() -> None:
    a = analyze(BASE, HEAD)
    b = analyze(BASE, HEAD)
    assert a.to_json() == b.to_json()
    data = json.loads(a.to_json())
    assert data["catalog_version"] == CATALOG_VERSION == "tamper-rules-v1"
    assert data["counts"]["findings"] == len(a.findings) == 2
    for f in data["findings"]:
        for field in ("finding_id", "rule_id", "family", "severity", "confidence", "path",
                      "old_snippet", "new_snippet", "reason", "waiver_key"):
            assert field in f


def test_finding_ids_are_stable_across_line_shifts_and_formatting() -> None:
    shifted = dict(HEAD)
    shifted["tests/test_shop.py"] = "# header comment\n\n\n" + TAMPERED.replace(
        "assert price(2) is not None", "assert   price( 2 )  is not None"
    )
    base_shifted = dict(BASE)
    base_shifted["tests/test_shop.py"] = "# header comment\n\n\n" + TEST_BASE
    ids_a = {f.finding_id for f in analyze(BASE, HEAD).findings}
    ids_b = {f.finding_id for f in analyze(base_shifted, shifted).findings}
    assert ids_a == ids_b and len(ids_a) == 2


def test_ids_differ_between_distinct_findings_and_repeat_ids_are_disambiguated() -> None:
    head = dict(HEAD)
    head["tests/test_shop.py"] = TEST_BASE.replace("price(2) == 4", "True").replace(
        "price(3) == 6", "True"
    )
    ids = [f.finding_id for f in analyze(BASE, head).findings]
    assert len(ids) == len(set(ids))


def test_whitespace_only_mutation_changes_nothing() -> None:
    mutated = {"tests/test_shop.py": TAMPERED.replace("\n\n\n", "\n\n\n\n\n"), "src/shop.py": SRC}
    base = {"tests/test_shop.py": TEST_BASE.replace("\n\n\n", "\n\n\n\n\n"), "src/shop.py": SRC}
    assert [f.finding_id for f in analyze(base, mutated).findings] == [
        f.finding_id for f in analyze(BASE, HEAD).findings
    ]


def test_formatting_only_change_produces_no_findings() -> None:
    head = {"src/shop.py": SRC, "tests/test_shop.py": TEST_BASE.replace("price(2) == 4", "price( 2 ) ==  4")}
    assert analyze(BASE, head).findings == ()


def test_severity_override_enable_disable_via_json(tmp_path: Path) -> None:
    cfg = tmp_path / "rules.json"
    cfg.write_text(json.dumps({
        "catalog_version": CATALOG_VERSION,
        "rules": {"T002": {"severity": "low"}, "T004": {"enabled": False},
                  "T004:strength_reduced": {"severity": "critical"}},
    }), encoding="utf-8")
    config = TamperConfig.from_json_file(cfg, known_rules=default_registry().ids())
    report = analyze(BASE, HEAD, config)
    assert keys(report) == ["T002:skip"]
    assert report.findings[0].severity is Severity.LOW
    assert report.rules_run and "T004" not in report.rules_run


def test_check_level_override_beats_rule_level() -> None:
    config = TamperConfig.from_dict({
        "rules": {"T004": {"severity": "low"}, "T004:strength_reduced": {"severity": "critical"}}
    })
    report = analyze(BASE, HEAD, config)
    sev = {f.rule_id: f.severity for f in report.findings}
    assert sev["T004"] is Severity.CRITICAL


def test_enable_only_and_disable_lists() -> None:
    only = analyze(BASE, HEAD, {"enable_only": ["T002"]})
    assert keys(only) == ["T002:skip"]
    off = analyze(BASE, HEAD, {"disable": ["T002", "T004"]})
    assert off.findings == ()


@pytest.mark.parametrize(
    "bad",
    [
        {"catalog_version": "tamper-rules-v0"},
        {"rules": {"T004": {"severity": "extreme"}}},
        {"rules": {"T004": "high"}},
        {"waivers": [{"rule": "T002"}]},
        {"waivers": [{"reason": "x"}]},
        {"params": {"nope": 1}},
        ["not", "an", "object"],
    ],
)
def test_malformed_config_is_rejected(bad: object) -> None:
    with pytest.raises(TamperConfigError):
        TamperConfig.from_dict(bad)  # type: ignore[arg-type]


def test_unknown_rule_ids_rejected_when_registry_known() -> None:
    with pytest.raises(TamperConfigError):
        TamperConfig.from_dict({"disable": ["T999"]}, known_rules=default_registry().ids())


def test_unreadable_config_file(tmp_path: Path) -> None:
    with pytest.raises(TamperConfigError):
        TamperConfig.from_json_file(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(TamperConfigError):
        TamperConfig.from_json_file(bad)


def test_waiver_by_finding_id_and_by_rule_path_moves_findings_not_deletes_them() -> None:
    report = analyze(BASE, HEAD)
    skip = next(f for f in report.findings if f.rule_id == "T002")
    waived = analyze(BASE, HEAD, {"waivers": [
        {"finding_id": skip.finding_id, "reason": "known flaky, ticket 12", "approved_by": "lead"},
        {"rule": "T004:strength_reduced", "path": "tests/*.py", "reason": "intentional"},
    ]})
    assert waived.findings == ()
    assert {w.finding.rule_id for w in waived.waived} == {"T002", "T004"}
    assert {w.reason for w in waived.waived} == {"known flaky, ticket 12", "intentional"}
    assert waived.counts["waived"] == 2
    assert "waived" in json.loads(waived.to_json())["waived"][0]


def test_waiver_with_wrong_path_does_not_match() -> None:
    report = analyze(BASE, HEAD, {"waivers": [{"rule": "T002", "path": "other/*", "reason": "x"}]})
    assert len(report.findings) == 2 and report.waived == ()


def test_inline_markers_in_the_diff_do_not_waive_findings() -> None:
    head = dict(HEAD)
    head["tests/test_shop.py"] = TAMPERED.replace(
        "@pytest.mark.skip", "@pytest.mark.skip  # radius: ignore[T002]"
    )
    assert "T002:skip" in keys(analyze(BASE, head))


# ---------------------------------------------------------------- robustness


def test_unparseable_python_is_recorded_not_raised() -> None:
    head = {"src/shop.py": SRC, "tests/test_shop.py": "def test_a(:\n    assert price(2) == \n"}
    report = analyze(BASE, head)
    assert report.rule_errors == ()
    assert any(u.path == "tests/test_shop.py" and u.side == "head" for u in report.unanalyzable)
    assert any(u.reason.startswith("parse_error") for u in report.unanalyzable)


def test_unparseable_base_is_recorded() -> None:
    base = {"src/shop.py": SRC, "tests/test_shop.py": "def test_a(:\n"}
    report = analyze(base, HEAD)
    assert any(u.side == "base" for u in report.unanalyzable)


def test_binary_and_oversized_files_are_unanalyzable() -> None:
    big = "x = 1\n" * 50
    config = TamperConfig.from_dict({"params": {"max_file_bytes": 100}})
    report = analyze({"a.py": "x=0\n"}, {"a.py": big}, config)
    assert any(u.reason == "file_too_large" for u in report.unanalyzable)
    binary = analyze({"data.bin": "a\n"}, {"data.bin": "a\x00b\n"})
    assert any(u.reason == "binary_file" for u in binary.unanalyzable)


def test_missing_base_snapshot_degrades_with_note() -> None:
    diff = make_diff(BASE, HEAD)
    cs = extract_symbol_changes(DictSnapshot(BASE), DictSnapshot(HEAD), diff, ExtractionOptions())
    report = analyze_tampering(cs, None, DictSnapshot(HEAD))
    assert "base_snapshot_unavailable" in report.notes
    rebuilt = analyze_tampering(cs, None, DictSnapshot(HEAD), diff_text=diff)
    assert keys(rebuilt) == keys(analyze(BASE, HEAD))


def test_reader_exception_is_contained() -> None:
    class Boom:
        def read(self, path: str) -> bytes | None:
            raise RuntimeError("disk on fire")

    diff = make_diff(BASE, HEAD)
    cs = extract_symbol_changes(DictSnapshot(BASE), DictSnapshot(HEAD), diff, ExtractionOptions())
    report = analyze_tampering(cs, Boom(), Boom())
    assert report.findings == ()
    assert any(u.reason.startswith("read_error") for u in report.unanalyzable)


def test_a_failing_rule_is_isolated() -> None:
    class Broken(BaseRule):
        id = "T900"
        family = Family.CODE_QUALITY
        checks = {"x": CheckSpec(Severity.LOW, "x")}
        doc = RuleDoc("t", "r", "b", "a", "l")

        def evaluate(self, context):  # noqa: ANN001, ANN201
            raise ValueError("boom")

    registry = default_registry()
    registry.register(Broken())
    diff = make_diff(BASE, HEAD)
    cs = extract_symbol_changes(DictSnapshot(BASE), DictSnapshot(HEAD), diff, ExtractionOptions())
    report = analyze_tampering(cs, DictSnapshot(BASE), DictSnapshot(HEAD), diff_text=diff,
                               registry=registry)
    assert report.rule_errors == ("T900:ValueError",)
    assert len(report.findings) == 2


def test_registry_validation() -> None:
    class Dup(BaseRule):
        id = "T001"
        family = Family.TEST_DISABLING
        checks = {"x": CheckSpec(Severity.LOW, "x")}
        doc = RuleDoc("t", "r", "b", "a", "l")

    class BadId(Dup):
        id = "X1"

    class NoChecks(Dup):
        id = "T777"
        checks: dict = {}

    reg = default_registry()
    with pytest.raises(ValueError):
        reg.register(Dup())
    with pytest.raises(ValueError):
        RuleRegistry([BadId()])
    with pytest.raises(ValueError):
        RuleRegistry([NoChecks()])
    assert reg.get("T005").id == "T005"
    assert len(reg.all()) == 17 and reg.catalog_version == CATALOG_VERSION


def test_max_findings_truncates_deterministically() -> None:
    body = "".join(f"def test_{i}():\n    assert True\n\n\n" for i in range(30))
    base = {"tests/test_x.py": "def test_0():\n    assert price(1) == 2\n"}
    head = {"tests/test_x.py": body}
    config = TamperConfig.from_dict({"params": {"max_findings": 5}})
    report = analyze(base, head, config)
    assert len(report.findings) == 5 and report.truncated
    assert "max_findings_exceeded" in report.notes


def test_time_budget_stops_rules_and_marks_truncated() -> None:
    ticks = iter(range(0, 10_000, 100))
    diff = make_diff(BASE, HEAD)
    cs = extract_symbol_changes(DictSnapshot(BASE), DictSnapshot(HEAD), diff, ExtractionOptions())
    report = analyze_tampering(
        cs, DictSnapshot(BASE), DictSnapshot(HEAD), TamperConfig.from_dict({"params": {"time_budget_seconds": 150}}),
        diff_text=diff, clock=lambda: float(next(ticks)),
    )
    assert report.truncated


def test_large_synthetic_diff_is_fast() -> None:
    n = 400
    base_src = "".join(f"def f{i}(x):\n    return x + {i}\n\n\n" for i in range(n))
    base_test = "from m import *\n\n\n" + "".join(
        f"def test_{i}():\n    assert f{i}(1) == {i + 1}\n    assert f{i}(2) == {i + 2}\n\n\n"
        for i in range(n)
    )
    head_test = "from m import *\n\n\n" + "".join(
        f"def test_{i}():\n    assert f{i}(1) is not None\n\n\n" if i % 2 else
        f"@pytest.mark.skip\ndef test_{i}():\n    assert f{i}(1) == {i + 1}\n    assert f{i}(2) == {i + 2}\n\n\n"
        for i in range(n)
    )
    base = {"m.py": base_src, "tests/test_m.py": base_test}
    head = {"m.py": base_src, "tests/test_m.py": head_test}
    diff = make_diff(base, head)
    assert diff.count("\n") > 1000
    cs = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff, ExtractionOptions())
    started = time.perf_counter()
    report = analyze_tampering(cs, DictSnapshot(base), DictSnapshot(head), diff_text=diff)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.5, f"tamper analysis took {elapsed:.2f}s"
    assert len(report.findings) >= n  # one per tampered test, at least


def test_report_counts_and_max_severity() -> None:
    report = analyze(BASE, HEAD)
    assert report.max_severity is Severity.HIGH
    assert report.counts["by_rule"] == {"T002": 1, "T004": 1}
    assert analyze(BASE, BASE).max_severity is None
    assert Severity.parse("HIGH") is Severity.HIGH and Severity.parse(Severity.LOW) is Severity.LOW
    with pytest.raises(ValueError):
        Severity.parse("nope")


def test_config_digest_changes_with_config() -> None:
    assert TamperConfig().digest() == TamperConfig().digest()
    assert TamperConfig().digest() != TamperConfig.from_dict({"disable": ["T001"]}).digest()
