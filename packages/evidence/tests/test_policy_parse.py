"""VD-04: ``.radius/policy.yml`` parsing, bounds, errors and warnings."""

from __future__ import annotations

import pytest
from radius_evidence.policy.policy import (
    BOUNDS,
    HeadPolicyMode,
    Mode,
    parse_policy,
)

FULL = """\
version: 1
mode: blocking
head_policy: tighten_only
thresholds:
  tau_support: 0.6
  uim_max: 0.1
  intent_coverage_min: 0.7
  link_review_min: 0.55
  cap_static: 0.5
tamper:
  fail_on_at_least: medium
  review_on_at_least: low
  rules:
    T002: medium
    T012:unverified_new_dependency:
      severity: low
    T005:
      enabled: false
      allow_disable: "approved by security, ticket SEC-12"
require:
  - paths: ["src/auth/**", "src/payments/**"]
    min_state: proven
  - paths: src/api/**
    min_state: weak
evidence:
  require_non_agent_test: true
  paths: [src/auth/**]
exclude:
  paths:
    - docs/**
    - "**/*.md"
"""


def test_full_policy_round_trip() -> None:
    result = parse_policy(FULL)
    assert not result.structural_failure
    assert result.errors == () and result.warnings == ()
    p = result.policy
    assert p is not None
    assert p.mode is Mode.BLOCKING and p.head_policy is HeadPolicyMode.TIGHTEN_ONLY
    assert p.thresholds == {
        "tau_support": 0.6,
        "uim_max": 0.1,
        "intent_coverage_min": 0.7,
        "link_review_min": 0.55,
        "cap_static": 0.5,
    }
    assert (p.fail_on_at_least, p.review_on_at_least) == ("medium", "low")
    rules = {r.rule: r for r in p.tamper_rules}
    assert rules["T002"].severity == "medium"
    assert rules["T012:unverified_new_dependency"].severity == "low"
    assert rules["T005"].enabled is False and "SEC-12" in (rules["T005"].allow_disable or "")
    assert [(r.paths, r.min_state) for r in p.requirements] == [
        (("src/auth/**", "src/payments/**"), "proven"),
        (("src/api/**",), "weak"),
    ]
    assert p.evidence is not None and p.evidence.paths == ("src/auth/**",)
    assert p.exclude_paths == ("docs/**", "**/*.md")
    assert p.lines["thresholds.tau_support"] == 5  # provenance keeps the source line
    assert p.lines["mode"] == 2


@pytest.mark.parametrize(
    ("key", "low", "high"),
    [(k, lo, hi) for k, (lo, hi) in BOUNDS.items()],
)
def test_threshold_bounds_are_inclusive_and_enforced(key: str, low: float, high: float) -> None:
    for value, ok in ((low, True), (high, True), (low - 0.01, False), (high + 0.01, False)):
        result = parse_policy(f"version: 1\nthresholds:\n  {key}: {value}\n")
        assert result.policy is not None
        assert (key in result.policy.thresholds) is ok, (key, value)
        if not ok:
            assert any("outside the allowed range" in e.message for e in result.errors)
            assert result.errors[0].line == 3
            assert not result.structural_failure


@pytest.mark.parametrize("value", ["abc", "true", "[1]", "'0.5'"])
def test_threshold_must_be_a_number(value: str) -> None:
    result = parse_policy(f"version: 1\nthresholds:\n  tau_support: {value}\n")
    assert result.policy is not None and result.policy.thresholds == {}
    assert result.errors


STRUCTURAL = [
    ("empty", "", "empty"),
    ("no version", "mode: blocking\n", "version"),
    ("wrong version", "version: 2\n", "version"),
    ("bool version", "version: true\n", "version"),
    ("root list", "- a\n", "mapping"),
    ("syntax error", "version: 1\nmode: [\n", "line 2"),
    ("flow map", "version: 1\nthresholds: {a: 1}\n", "Flow mappings"),
    ("tab", "version: 1\nthresholds:\n\ttau_support: 0.5\n", "Tabs"),
    ("too big", "version: 1\n# " + "x" * 70000 + "\n", "larger"),
]


@pytest.mark.parametrize(("name", "text", "needle"), STRUCTURAL, ids=[c[0] for c in STRUCTURAL])
def test_structural_failures_are_reported_not_raised(name: str, text: str, needle: str) -> None:
    result = parse_policy(text)
    assert result.structural_failure and result.policy is None
    assert any(needle in str(e) for e in result.errors), [str(e) for e in result.errors]


SOFT_ERRORS = [
    ("bad mode", "mode: loud\n", 2, "mode must be"),
    ("bad head policy", "head_policy: always\n", 2, "head_policy must be"),
    ("thresholds not map", "thresholds: 5\n", 2, "'thresholds' must be a mapping"),
    ("bad fail_on", "tamper:\n  fail_on_at_least: critical\n", 3, "fail_on_at_least must be one of"),
    ("bad review_on", "tamper:\n  review_on_at_least: critical\n", 3, "review_on_at_least must be one of"),
    ("bad rule id", "tamper:\n  rules:\n    X1: low\n", 4, "expected a rule id"),
    ("bad severity", "tamper:\n  rules:\n    T001: loud\n", 4, "severity must be one of"),
    ("rule neither", "tamper:\n  rules:\n    T001:\n      allow_disable: 'long enough reason'\n", 4, "sets neither"),
    ("rule enabled not bool", "tamper:\n  rules:\n    T001:\n      enabled: maybe\n", 5, "enabled must be true or false"),
    ("short ack", "tamper:\n  rules:\n    T001:\n      enabled: false\n      allow_disable: no\n", 6, "allow_disable must be a reason"),
    ("require not list", "require: 5\n", 2, "'require' must be a list"),
    ("require entry scalar", "require:\n  - x\n", 3, "must be a mapping"),
    ("require no paths", "require:\n  - min_state: proven\n", 3, "needs 'paths'"),
    ("require bad state", "require:\n  - paths: [a/**]\n    min_state: excellent\n", 4, "min_state must be"),
    ("require bad glob", "require:\n  - paths: ['/etc/**']\n    min_state: proven\n", 3, "absolute paths"),
    ("glob traversal", "exclude:\n  paths: ['../x']\n", 3, "'..'"),
    ("evidence flag not bool", "evidence:\n  require_non_agent_test: yes please\n", 3, "true or false"),
    ("evidence not map", "evidence: 3\n", 2, "'evidence' must be a mapping"),
    ("exclude not map", "exclude: 3\n", 2, "'exclude' must be a mapping"),
    ("tamper not map", "tamper: 3\n", 2, "'tamper' must be a mapping"),
    ("rules not map", "tamper:\n  rules: 3\n", 3, "'tamper.rules' must be a mapping"),
    ("duplicate key", "mode: advisory\nmode: blocking\n", 3, "Duplicate key"),
    ("review above fail", "tamper:\n  fail_on_at_least: medium\n  review_on_at_least: high\n", 4, "at or below"),
]


@pytest.mark.parametrize(("name", "body", "line", "needle"), SOFT_ERRORS, ids=[c[0] for c in SOFT_ERRORS])
def test_value_errors_are_line_numbered_and_do_not_invalidate_the_file(
    name: str, body: str, line: int, needle: str
) -> None:
    result = parse_policy("version: 1\n" + body)
    assert not result.structural_failure and result.policy is not None
    hit = [e for e in result.errors if needle in e.message]
    assert hit, [str(e) for e in result.errors]
    assert hit[0].line == line, (hit[0], name)


UNKNOWN = [
    ("top level", "colour: red\n", 2, "Unknown key 'colour'"),
    ("thresholds", "thresholds:\n  tau: 0.5\n", 3, "thresholds.tau"),
    ("tamper", "tamper:\n  foo: 1\n", 3, "tamper.foo"),
    ("rule", "tamper:\n  rules:\n    T001:\n      severity: low\n      colour: 1\n", 6, "T001.colour"),
    ("require", "require:\n  - paths: [a/**]\n    weight: 3\n", 4, "require[].weight"),
    ("evidence", "evidence:\n  require_non_agent_test: true\n  other: 1\n", 4, "evidence.other"),
    ("exclude", "exclude:\n  paths: [a/**]\n  other: 1\n", 4, "exclude.other"),
]


@pytest.mark.parametrize(("name", "body", "line", "needle"), UNKNOWN, ids=[c[0] for c in UNKNOWN])
def test_unknown_keys_are_warnings_not_errors(name: str, body: str, line: int, needle: str) -> None:
    result = parse_policy("version: 1\n" + body)
    assert result.policy is not None and not result.structural_failure
    assert any(needle in w.message and w.line == line for w in result.warnings), result.warnings
    assert not any("Unknown" in e.message for e in result.errors)


def test_invalid_values_fall_back_to_defaults_individually() -> None:
    text = "version: 1\nmode: blocking\nthresholds:\n  tau_support: 5\n  uim_max: 0.3\n"
    p = parse_policy(text).policy
    assert p is not None and p.mode is Mode.BLOCKING
    assert p.thresholds == {"uim_max": 0.3}


def test_minimal_policy_has_no_effect() -> None:
    p = parse_policy("version: 1\n").policy
    assert p is not None
    assert p.mode is None and p.thresholds == {} and p.requirements == ()
    assert p.head_policy is HeadPolicyMode.IGNORE


def test_item_limits() -> None:
    globs = ", ".join(f"a{i}/**" for i in range(60))
    result = parse_policy(f"version: 1\nexclude:\n  paths: [{globs}]\n")
    assert result.policy is not None and len(result.policy.exclude_paths) == 50
    assert any("at most 50" in e.message for e in result.errors)


def test_the_shipped_examples_parse_cleanly() -> None:
    from datetime import date
    from pathlib import Path

    from radius_evidence.policy.waivers import parse_waivers

    root = next(p for p in Path(__file__).resolve().parents if (p / ".radius").is_dir())
    policy = parse_policy((root / ".radius" / "policy.example.yml").read_text(encoding="utf-8"))
    assert policy.policy is not None and not policy.errors and not policy.warnings
    assert policy.policy.mode is Mode.ADVISORY and policy.policy.requirements and policy.policy.evidence
    waivers = parse_waivers((root / ".radius" / "waivers.example.yml").read_text(encoding="utf-8"), today=date(2026, 11, 2))
    assert [w.kind for w in waivers.waivers] == ["finding", "rule", "criterion"]
    assert not waivers.errors and not waivers.ignored
