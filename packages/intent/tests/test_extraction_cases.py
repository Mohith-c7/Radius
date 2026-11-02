# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Table-driven extraction tests over the fixtures directory.

Each fixture ``fixtures/extraction/<name>.{md,yml}`` has an entry in
``expected.json``: source kind, the exact ordered criterion texts, diagnostic
codes that must be present, and an optional ``suspicious`` flag expectation.
"""

from __future__ import annotations

import json

import pytest
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from extraction_helpers import FIXTURES, src
from radius_intent.domain import (
    CriterionState,
    ExtractionMethod,
    IntentSourceKind,
    criterion_id,
)
from radius_intent.infrastructure.extraction import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    DeterministicCriterionExtractor,
)

EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
CASES = sorted(EXPECTED)
EXTRACTOR = DeterministicCriterionExtractor()
NON_VERBATIM_RULES = {"gherkin", "spec_file", "table_row"}


def load(name: str, *, crlf: bool = False):
    spec = EXPECTED[name]
    text = (FIXTURES / name).read_text(encoding="utf-8")
    if crlf:
        text = text.replace("\n", "\r\n")
    return src(text, IntentSourceKind(spec["kind"]), source_id=name), text


def test_fixture_corpus_is_large_and_every_file_has_expectations():
    on_disk = {p.name for p in FIXTURES.iterdir() if p.suffix in {".md", ".yml"}}
    assert on_disk == set(CASES)
    assert len(CASES) >= 40


@pytest.mark.parametrize("name", CASES)
def test_fixture_extraction(name):
    spec = EXPECTED[name]
    source, _ = load(name, crlf=spec["crlf"])
    report = EXTRACTOR.extract_report(source)

    assert [c.text for c in report.criteria] == spec["criteria"]
    codes = {d.code for d in report.diagnostics}
    assert set(spec["codes"]) <= codes, (spec["codes"], codes)
    if spec["suspicious"] is not None:
        assert report.suspicious is spec["suspicious"]

    assert len(report.traces) == len(report.criteria)
    for criterion, trace in zip(report.criteria, report.traces, strict=True):
        assert trace.criterion_id == criterion.id
        assert criterion.state is CriterionState.PROPOSED
        assert criterion.origin.extraction_method is ExtractionMethod.DETERMINISTIC
        assert criterion.origin.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION
        assert criterion.id == criterion_id(criterion.normalized_text, source.ref.key)
        assert criterion.span.within(source.text)


@pytest.mark.parametrize("name", CASES)
def test_port_method_matches_report(name):
    source, _ = load(name, crlf=EXPECTED[name]["crlf"])
    assert EXTRACTOR.extract(source) == EXTRACTOR.extract_report(source).criteria


@pytest.mark.parametrize("name", [n for n in CASES if n.endswith(".md")])
def test_crlf_and_lf_give_same_criteria(name):
    lf_source, _ = load(name)
    crlf_source, _ = load(name, crlf=True)
    lf = EXTRACTOR.extract_report(lf_source)
    crlf = EXTRACTOR.extract_report(crlf_source)
    assert [c.text for c in crlf.criteria] == [c.text for c in lf.criteria]
    assert [c.id for c in crlf.criteria] == [c.id for c in lf.criteria]


@pytest.mark.parametrize("name", [n for n in CASES if n.endswith(".md")])
def test_span_points_at_the_statement(name):
    source, text = load(name)
    if "<!--" in text:
        pytest.skip("comment masking intentionally differs from the raw slice")
    report = EXTRACTOR.extract_report(source)
    for criterion, trace in zip(report.criteria, report.traces, strict=True):
        if trace.rule in NON_VERBATIM_RULES:
            continue
        covered = " ".join(criterion.span.slice(source.text).split())
        assert criterion.text == covered or criterion.text.endswith(covered), (
            criterion.text,
            covered,
        )


def test_gherkin_span_covers_the_scenario_lines():
    source, text = load("gherkin_fenced.md")
    first, second = EXTRACTOR.extract(source)
    covered = first.span.slice(text)
    assert covered.startswith("Scenario: Request a reset")
    assert covered.endswith("Then an email is sent")
    assert second.span.start > first.span.end


def test_table_span_is_the_cell():
    source, text = load("table_criteria_column.md")
    (first, _second) = EXTRACTOR.extract(source)
    assert first.span.slice(text) == "Passwords are hashed with argon2"


def test_checkbox_state_is_recorded_in_the_trace():
    source = src(
        "## Acceptance Criteria\n- [x] done one\n- [ ] open one\n- plain one\n"
    )
    report = EXTRACTOR.extract_report(source)
    assert [t.checked for t in report.traces] == [True, False, None]
    assert [t.rule for t in report.traces] == ["task_item", "task_item", "section_item"]
    assert report.traces[0].section == "acceptance criteria"


def test_lead_in_depth_and_prefix_trace():
    source = src("## Acceptance Criteria\n- Admins can:\n  - create users\n")
    report = EXTRACTOR.extract_report(source)
    assert [c.text for c in report.criteria] == ["Admins can: create users"]
    assert report.traces[0].depth == 1


def test_custom_section_pattern_is_configurable():
    from radius_intent.infrastructure.extraction import ExtractionConfig

    config = ExtractionConfig(section_pattern=r"goals?")
    extractor = DeterministicCriterionExtractor(config)
    source = src(
        "## Goals\n- Ship the thing\n\n## Acceptance Criteria\n- Not a section now\n"
    )
    assert [c.text for c in extractor.extract(source)] == ["Ship the thing"]


def test_report_flags_for_ingestion_markers():
    source = src("plain", truncated=True, suspicious_content_removed=True)
    report = EXTRACTOR.extract_report(source)
    codes = {d.code for d in report.diagnostics}
    assert {"truncated", "suspicious_removed_upstream"} <= codes
    assert report.suspicious


def test_trace_for_lookup():
    source = src("The service must log requests.")
    report = EXTRACTOR.extract_report(source)
    (criterion,) = report.criteria
    assert report.trace_for(criterion.id) is not None
    assert report.trace_for("crit_missing") is None
    assert report.trace_for(criterion.id).rule == "modal"
