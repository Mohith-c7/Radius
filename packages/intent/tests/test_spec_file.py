# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""`.radius/intent.yml` parsing and validation (precise, line-numbered errors)."""

from __future__ import annotations

from pathlib import Path

import pytest
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from extraction_helpers import src
from radius_intent.domain import CriterionHints, ExtractionMethod, IntentSourceKind
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    DiagnosticKind,
    Severity,
)

EXTRACTOR = DeterministicCriterionExtractor()
HEAD = "version: 1\ncriteria:\n"


def run(text: str):
    return EXTRACTOR.extract_report(
        src(text, IntentSourceKind.SPEC_FILE, ".radius/intent.yml")
    )


def problems(report):
    return [
        (d.code, d.line)
        for d in report.diagnostics
        if d.kind is DiagnosticKind.PARSE_ERROR
    ]


def test_full_example_from_the_task_schema():
    report = run(
        'version: 1\ncriteria:\n  - id: C1\n    text: "Users can reset their password via email link"\n'
        '    weight: 1.0\n    paths: ["src/auth/**"]        # optional hints for linking\n'
        '    tests: ["tests/auth/test_reset.py::test_reset_flow"]   # explicit evidence\n'
    )
    (c,) = report.criteria
    assert c.text == "Users can reset their password via email link"
    assert c.weight == 1.0
    assert c.hints == CriterionHints(
        paths=("src/auth/**",),
        tests=("tests/auth/test_reset.py::test_reset_flow",),
        label="C1",
    )
    assert c.origin.extraction_method is ExtractionMethod.DETERMINISTIC
    assert c.origin.source.kind is IntentSourceKind.SPEC_FILE
    assert report.traces[0].rule == "spec_file"
    assert not report.diagnostics


def test_span_points_at_the_text_value_not_the_quotes():
    text = HEAD + '  - text: "Only this"\n'
    (c,) = run(text).criteria
    assert c.span.slice(text) == "Only this"


def test_ids_are_stable_across_reweighting_and_hint_changes():
    a = run(HEAD + '  - id: C1\n    text: "Same text"\n    weight: 1\n')
    b = run(
        HEAD + '  - id: C9\n    text: "Same text"\n    weight: 0.5\n    paths: [x]\n'
    )
    assert a.criteria[0].id == b.criteria[0].id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("criteria: []\n", [("spec_missing_version", 1)]),
        ("version: 2\ncriteria: []\n", [("spec_unsupported_version", 1)]),
        ('version: "1"\ncriteria: []\n', [("spec_unsupported_version", 1)]),
        ("version: 1.0\ncriteria: []\n", [("spec_unsupported_version", 1)]),
        ("version: 1\n", [("spec_missing_criteria", 1)]),
        ("version: 1\ncriteria: nope\n", [("spec_criteria_not_list", 2)]),
        ("- a\n- b\n", [("spec_not_mapping", 1)]),
        (HEAD + "  - just a string\n", [("spec_criterion_not_mapping", 3)]),
        (HEAD + "  - id: C1\n", [("spec_missing_text", 3)]),
        (HEAD + "  - text: ''\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: [a, b]\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: 5\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: ok\n    weight: 0\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    weight: 1.01\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    weight: -0.5\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    weight: true\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    weight: .nan\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    weight: [1]\n", [("spec_invalid_weight", 4)]),
        (HEAD + "  - text: ok\n    paths: src\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: [1]\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: ['/abs']\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: ['a/../b']\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: ['C:/x']\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    tests: ['..\\\\x']\n", [("spec_invalid_tests", 4)]),
        (
            HEAD + "  - text: ok\n    tests: ['../t.py::x']\n",
            [("spec_invalid_tests", 4)],
        ),
        (HEAD + "  - id: 'bad id!'\n    text: ok\n", [("spec_invalid_id", 3)]),
        (HEAD + "  - id: [x]\n    text: ok\n", [("spec_invalid_id", 3)]),
        (HEAD + "  - text: Users can: reset\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: &a x\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: *a\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: !!str x\n", [("spec_invalid_text", 3)]),
        (HEAD + "  - text: {a: 1}\n", [("spec_invalid_text", 3)]),
        (HEAD + '  - text: "unterminated\n', [("spec_invalid_text", 3)]),
        (HEAD + '  - text: "bad \\q escape"\n', [("spec_invalid_text", 3)]),
        (HEAD + '  - text: "a" trailing\n', [("spec_invalid_text", 3)]),
        (HEAD + "  - text: ok\n    paths: [a, b\n", [("spec_invalid_paths", 4)]),
        (
            HEAD + "  - text: ok\n    paths: [a b c]\n    tests: ['x' 'y']\n",
            [("spec_invalid_tests", 5)],
        ),
        (HEAD + "  - text: ok\n    paths: ['a'] junk\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: []]\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: [,]\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: [&a]\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: ok\n    paths: ['a\\q']\n", [("spec_invalid_paths", 4)]),
        (HEAD + "  - text: |\n  -\n", [("spec_invalid_text", 3)]),
    ],
)
def test_validation_errors_carry_codes_and_line_numbers(text, expected):
    report = run(text)
    assert problems(report)[: len(expected)] == expected
    assert not report.criteria


@pytest.mark.parametrize(
    ("text", "code", "line"),
    [
        ("version: 1\n\tcriteria: []\n", "spec_syntax", 2),
        ("version: 1\ncriteria:\n\t- text: x\n", "spec_syntax", 3),
        ("version: 1\ncriteria:\n  - text: x\n      deeper: y\n", "spec_syntax", 4),
        ("version: 1\nnot a mapping line\n", "spec_syntax", 2),
        ("version: 1\ncriteria: []\n---\nversion: 1\n", "spec_syntax", 3),
        ("version: 1\ncriteria: []\ntrailing\n", "spec_syntax", 3),
        ("version: 1\ncriteria:\n  - text: |\n      a\n     b\n", "spec_syntax", 5),
        ("version: 1\n- x\n", "spec_syntax", 2),
        ("version: 1\ncriteria:\n  - text: ok\n    bad key: x\n", "spec_syntax", 4),
        ("version: 1\ncriteria:\n  - text: |\n\ttab\n", "spec_syntax", 4),
    ],
)
def test_structural_errors_are_reported_not_raised(text, code, line):
    report = run(text)
    assert problems(report)[0] == (code, line)
    assert report.errors[0].severity is Severity.ERROR


def test_duplicate_ids_and_keys_keep_the_first_and_report_the_second():
    dup_id = run(HEAD + "  - id: C1\n    text: a\n  - id: C1\n    text: b\n")
    assert [c.text for c in dup_id.criteria] == ["a"]
    assert problems(dup_id) == [("spec_duplicate_id", 5)]
    dup_key = run(HEAD + "  - text: a\n    text: b\n")
    assert ("spec_duplicate_key", 4) in problems(dup_key)


def test_quoted_list_item_is_not_a_mapping():
    report = run(HEAD + "  - 'quoted: not a key'\n")
    assert problems(report) == [("spec_criterion_not_mapping", 3)]


def test_one_bad_criterion_does_not_hide_the_others():
    report = run(
        HEAD
        + "  - text: first\n  - text: bad\n    weight: 9\n  - text: third\n    weight: 0.5\n"
    )
    assert [c.text for c in report.criteria] == ["first", "third"]
    assert problems(report) == [("spec_invalid_weight", 5)]


def test_unknown_keys_are_warnings_with_lines():
    report = run("version: 1\nextra: 1\ncriteria:\n  - text: ok\n    flavour: x\n")
    assert [c.text for c in report.criteria] == ["ok"]
    unknown = [d for d in report.diagnostics if d.code == "spec_unknown_key"]
    assert [(d.line, d.severity) for d in unknown] == [
        (2, Severity.WARNING),
        (5, Severity.WARNING),
    ]
    assert not report.errors


def test_spec_errors_do_not_stop_other_sources():
    bad = src("version: 3\n", IntentSourceKind.SPEC_FILE, "spec")
    good = src("## Acceptance Criteria\n- Still extracted\n")
    report = EXTRACTOR.extract_sources([bad, good])
    assert [c.text for c in report.criteria] == ["Still extracted"]
    assert ("spec_unsupported_version", 1) in problems(report)


def test_yaml_features_supported_by_the_subset():
    text = (
        "# comment\n---\nversion: 1  # trailing\ncriteria:\n"
        "- id: 7\n  text: 'it''s'\n  paths:\n  - a\n  - 'b c'\n"
        '- text: "tab\\there \\"q\\" \\\\ \\/ \\n"\n'
        "- text: >\n    folded\n\n    para\n"
        "- text: |\n    lit\n    eral\n"
        "- text: plain # not part\n  weight: 1\n  tests: []\n  paths: ~\n"
        "...\n"
    )
    report = run(text)
    assert not report.diagnostics, report.diagnostics
    assert [c.text for c in report.criteria] == [
        "it's",
        'tab here "q" \\ /',
        "folded para",
        "lit eral",
        "plain",
    ]
    assert report.criteria[0].hints == CriterionHints(paths=("a", "b c"), label="7")


def test_limits_on_number_of_criteria_and_hints():
    many = HEAD + "".join(f"  - text: criterion number {i} here\n" for i in range(600))
    report = run(many)
    assert len(report.criteria) == 500
    assert "max_criteria" in {d.code for d in report.diagnostics}
    hints = ", ".join(f"p{i}" for i in range(60))
    assert (
        problems(run(HEAD + f"  - text: ok\n    paths: [{hints}]\n"))[0][0]
        == "spec_invalid_paths"
    )
    long_text = "x" * 2001
    assert problems(run(HEAD + f"  - text: {long_text}\n"))[0][0] == "spec_invalid_text"


def test_empty_and_comment_only_files_are_fine():
    empty = run("")
    assert [d.code for d in empty.diagnostics] == ["spec_empty"]
    assert not empty.errors
    assert not run("# only a comment\n\n").errors
    assert not run("---\n").errors
    assert problems(run("version: 1\ncriteria:\n"))[0:1] == []


def test_spec_text_is_not_comment_masked():
    text = HEAD + "  - text: 'a <!-- b --> c'\n"
    (c,) = run(text).criteria
    assert c.text == "a <!-- b --> c"


def test_documented_example_parses_without_diagnostics():
    path = (
        Path(__file__).resolve().parents[3] / "docs" / "intent" / "intent.example.yml"
    )
    report = run(path.read_text(encoding="utf-8"))
    assert not report.diagnostics
    assert [c.hints.label for c in report.criteria] == ["C1", "C2", None]
    assert report.criteria[1].weight == 0.8
