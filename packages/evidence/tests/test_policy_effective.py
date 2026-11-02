"""VD-04: overlay onto VerdictV2Config, provenance, base-vs-head source rules."""

from __future__ import annotations

import pytest
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.policy.effective import (
    NO_POLICY,
    apply_to_config,
    at_least_as_strict,
    default_threshold,
    resolve_policy,
)
from radius_evidence.policy.policy import HeadPolicyMode, Mode, parse_policy

DEFAULT = VerdictV2Config()


def pol(body: str):
    parsed = parse_policy("version: 1\n" + body)
    assert parsed.policy is not None and not parsed.errors, parsed.errors
    return parsed.policy


OVERLAY = [
    ("tau_support", "0.7", lambda c: c.support.tau_support, 0.7),
    ("uim_max", "0.1", lambda c: c.rules.uim_max, 0.1),
    ("intent_coverage_min", "0.8", lambda c: c.rules.min_intent_coverage, 0.8),
    ("link_review_min", "0.6", lambda c: c.rules.link_review_min, 0.6),
    ("cap_static", "0.45", lambda c: c.quality.cap_static, 0.45),
]


@pytest.mark.parametrize(("key", "value", "read", "expected"), OVERLAY)
def test_each_threshold_lands_in_the_config(key, value, read, expected) -> None:
    eff = resolve_policy(pol(f"thresholds:\n  {key}: {value}\n"))
    cfg = apply_to_config(eff)
    assert read(cfg) == expected
    assert cfg.digest() != DEFAULT.digest()
    # nothing else moved
    other = {k for k, *_ in OVERLAY} - {key}
    for k, _, rd, _ in OVERLAY:
        if k in other:
            assert rd(cfg) == rd(DEFAULT)


def test_no_policy_leaves_the_config_byte_identical() -> None:
    assert apply_to_config(NO_POLICY).digest() == DEFAULT.digest()
    assert apply_to_config(resolve_policy(pol(""))).digest() == DEFAULT.digest()


def test_tamper_thresholds_overlay() -> None:
    cfg = apply_to_config(resolve_policy(pol("tamper:\n  fail_on_at_least: medium\n  review_on_at_least: low\n")))
    assert cfg.rules.fail_on_tamper_at_least == "medium"
    assert cfg.rules.review_on_tamper_at_least == "low"


def test_provenance_names_the_policy_line_of_every_setting() -> None:
    body = (
        "mode: blocking\n"
        "thresholds:\n"
        "  tau_support: 0.7\n"
        "  uim_max: 0.1\n"
        "tamper:\n"
        "  rules:\n"
        "    T002: high\n"
        "require:\n"
        "  - paths: [src/auth/**]\n"
        "    min_state: proven\n"
        "evidence:\n"
        "  require_non_agent_test: true\n"
    )
    eff = resolve_policy(pol(body))
    got = {p.key: (p.line, p.origin, p.file) for p in eff.provenance}
    assert got["mode"] == (2, "base", ".radius/policy.yml")
    assert got["thresholds.tau_support"][0] == 4
    assert got["thresholds.uim_max"][0] == 5
    assert got["tamper.rules.T002"][0] == 8
    assert got["require[0]"][0] == 10
    assert got["evidence.require_non_agent_test"][0] == 13
    assert all(p.origin == "base" for p in eff.provenance)
    assert eff.has_rules and eff.mode is Mode.BLOCKING


def test_policy_without_requirements_adds_no_verdict_rules() -> None:
    assert not resolve_policy(pol("thresholds:\n  uim_max: 0.1\n")).has_rules
    assert resolve_policy(pol("evidence:\n  require_non_agent_test: true\n")).has_rules


# ---------------------------------------------------------------- head policy

OPT_IN = "head_policy: tighten_only\n"


def merged(base_body: str, head_body: str, *, opt_in: bool = True):
    base = pol((OPT_IN if opt_in else "") + base_body)
    head = pol(head_body)
    return resolve_policy(base, head), resolve_policy(base)


HEAD_CASES = [
    # (name, base, head, key, expected merged value)
    ("tighter tau accepted", "thresholds:\n  tau_support: 0.5\n", "thresholds:\n  tau_support: 0.7\n", "tau_support", 0.7),
    ("looser tau dropped", "thresholds:\n  tau_support: 0.6\n", "thresholds:\n  tau_support: 0.4\n", "tau_support", 0.6),
    ("tighter uim accepted", "thresholds:\n  uim_max: 0.2\n", "thresholds:\n  uim_max: 0.05\n", "uim_max", 0.05),
    ("looser uim dropped", "thresholds:\n  uim_max: 0.1\n", "thresholds:\n  uim_max: 0.4\n", "uim_max", 0.1),
    ("looser than default dropped", "", "thresholds:\n  uim_max: 0.4\n", "uim_max", None),
    ("cap lower is stricter", "thresholds:\n  cap_static: 0.6\n", "thresholds:\n  cap_static: 0.4\n", "cap_static", 0.4),
    ("cap higher dropped", "thresholds:\n  cap_static: 0.4\n", "thresholds:\n  cap_static: 0.8\n", "cap_static", 0.4),
    ("coverage higher accepted", "", "thresholds:\n  intent_coverage_min: 0.9\n", "intent_coverage_min", 0.9),
    ("coverage lower dropped", "thresholds:\n  intent_coverage_min: 0.7\n", "thresholds:\n  intent_coverage_min: 0.3\n", "intent_coverage_min", 0.7),
    ("link higher accepted", "", "thresholds:\n  link_review_min: 0.8\n", "link_review_min", 0.8),
    ("link lower dropped", "thresholds:\n  link_review_min: 0.7\n", "thresholds:\n  link_review_min: 0.3\n", "link_review_min", 0.7),
]


@pytest.mark.parametrize(("name", "base", "head", "key", "expected"), HEAD_CASES, ids=[c[0] for c in HEAD_CASES])
def test_head_thresholds_may_only_tighten(name, base, head, key, expected) -> None:
    eff, base_only = merged(base, head)
    want = expected if expected is not None else default_threshold(DEFAULT, key)
    assert eff.thresholds.get(key, default_threshold(DEFAULT, key)) == want
    assert at_least_as_strict(eff, base_only)
    if expected is None or eff.thresholds.get(key) != head_value(head, key):
        assert any(i.key == f"thresholds.{key}" and i.origin == "head" for i in eff.ignored_head)


def head_value(body: str, key: str) -> float:
    return pol(body).thresholds[key]


def test_head_policy_is_ignored_without_the_base_opt_in() -> None:
    eff, base_only = merged("", "thresholds:\n  tau_support: 0.9\nmode: blocking\n", opt_in=False)
    assert eff.thresholds == {} and eff.mode is None
    assert eff == base_only


def test_head_policy_is_ignored_when_there_is_no_base_policy() -> None:
    assert resolve_policy(None, pol("mode: blocking\nthresholds:\n  tau_support: 0.9\n")) is NO_POLICY


def test_head_can_not_loosen_mode_or_exclusions_or_disable_rules() -> None:
    base = "mode: blocking\nexclude:\n  paths: [docs/**]\n"
    head = (
        "mode: advisory\n"
        "exclude:\n  paths: [src/**]\n"
        "tamper:\n  rules:\n    T005:\n      enabled: false\n      allow_disable: 'head wants this off'\n"
    )
    eff, base_only = merged(base, head)
    assert eff.mode is Mode.BLOCKING
    assert eff.exclude_paths == ("docs/**",)
    assert not [r for r in eff.tamper_rules if r.origin == "head"]
    keys = {i.key for i in eff.ignored_head}
    assert {"mode", "exclude.paths", "tamper.rules.T005"} <= keys
    assert at_least_as_strict(eff, base_only)


def test_head_can_add_requirements_evidence_mode_and_severity_raises() -> None:
    head = (
        "mode: blocking\n"
        "tamper:\n  fail_on_at_least: medium\n  rules:\n    T016: high\n"
        "require:\n  - paths: [src/core/**]\n    min_state: proven\n"
        "evidence:\n  require_non_agent_test: true\n"
    )
    eff, base_only = merged("mode: advisory\n", head)
    assert eff.mode is Mode.BLOCKING
    assert eff.fail_on_at_least == "medium"
    assert [r.paths for r in eff.requirements] == [("src/core/**",)]
    assert eff.requirements[0].origin == "head"
    assert eff.evidence is not None and eff.evidence.origin == "head"
    rule = next(r for r in eff.tamper_rules if r.rule == "T016")
    assert rule.raise_only and rule.origin == "head" and rule.enabled is None
    assert at_least_as_strict(eff, base_only) and not at_least_as_strict(base_only, eff)
    assert {p.origin for p in eff.provenance} == {"base", "head"}


def test_head_looser_tamper_thresholds_are_dropped() -> None:
    eff, base_only = merged("tamper:\n  fail_on_at_least: medium\n", "tamper:\n  fail_on_at_least: high\n  review_on_at_least: low\n")
    assert eff.fail_on_at_least == "medium"
    assert eff.review_on_at_least == "low"  # stricter review accepted
    assert any(i.key == "tamper.fail_on_at_least" for i in eff.ignored_head)
    assert at_least_as_strict(eff, base_only)


def test_review_threshold_is_clamped_below_fail_after_a_merge() -> None:
    eff, _ = merged("tamper:\n  review_on_at_least: high\n", "tamper:\n  fail_on_at_least: medium\n")
    assert eff.fail_on_at_least == "medium" and eff.review_on_at_least == "medium"


def test_head_mode_absent_in_base_is_adopted_only_when_blocking() -> None:
    eff, _ = merged("", "mode: advisory\n")
    assert eff.mode is None
    eff, _ = merged("", "mode: blocking\n")
    assert eff.mode is Mode.BLOCKING


def test_base_policy_opt_in_is_recorded() -> None:
    assert resolve_policy(pol(OPT_IN)).head_policy is HeadPolicyMode.TIGHTEN_ONLY
    assert resolve_policy(pol("")).head_policy is HeadPolicyMode.IGNORE


def test_strictness_order_detects_loosening() -> None:
    strict = resolve_policy(pol("mode: blocking\nthresholds:\n  tau_support: 0.7\n  uim_max: 0.1\nrequire:\n  - paths: [a/**]\n"))
    loose = resolve_policy(pol("thresholds:\n  tau_support: 0.4\n  uim_max: 0.3\nexclude:\n  paths: [a/**]\n"))
    assert not at_least_as_strict(loose, strict)
    assert at_least_as_strict(strict, strict)
    assert at_least_as_strict(strict, NO_POLICY)
    assert not at_least_as_strict(NO_POLICY, strict)
