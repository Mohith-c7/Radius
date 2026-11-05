"""VD-04/VD-05 property tests (seeded random generation; no extra dependency).

Properties:
* the parsers never raise, whatever the text;
* every accepted threshold is inside its safe bounds;
* a head-supplied policy merged under ``tighten_only`` is never less strict than the
  base policy alone (thresholds, mode, requirements, exclusions, tamper severities);
* a policy can never lower a high/critical tamper finding without ``allow_disable``;
* a waiver can never apply to a ``contradicted`` criterion.
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.policy import miniyaml
from radius_evidence.policy.apply import (
    CriterionWaiverFacts,
    apply_criterion_waivers,
    apply_tamper_policy,
)
from radius_evidence.policy.effective import at_least_as_strict, resolve_policy
from radius_evidence.policy.policy import (
    BOUNDS,
    SEVERITIES,
    parse_policy,
    severity_rank,
)
from radius_evidence.policy.waivers import parse_waivers

SEEDS = range(60)
RULES = ["T001", "T002", "T005", "T012", "T012:unverified_new_dependency", "T016"]


def rand_policy(rng: random.Random, *, opt_in: bool = False, allow_ack: bool = True) -> str:
    lines = ["version: 1"]
    if opt_in:
        lines.append("head_policy: tighten_only")
    if rng.random() < 0.6:
        lines.append(f"mode: {rng.choice(['advisory', 'blocking'])}")
    if rng.random() < 0.8:
        lines.append("thresholds:")
        for key, (lo, hi) in BOUNDS.items():
            if rng.random() < 0.6:
                lines.append(f"  {key}: {round(rng.uniform(lo, hi), 2)}")
    if rng.random() < 0.7:
        lines.append("tamper:")
        if rng.random() < 0.4:
            lines.append(f"  fail_on_at_least: {rng.choice(['medium', 'high'])}")
        if rng.random() < 0.4:
            lines.append(f"  review_on_at_least: {rng.choice(['low', 'medium'])}")
        lines.append("  rules:")
        for rule in rng.sample(RULES, rng.randint(1, 4)):
            lines.append(f"    {rule}:")
            body = []
            if rng.random() < 0.7:
                body.append(f"      severity: {rng.choice(SEVERITIES)}")
            if rng.random() < 0.4:
                body.append("      enabled: false")
            if not body:
                body.append("      severity: low")
            if allow_ack and rng.random() < 0.3:
                body.append("      allow_disable: 'acknowledged by the security owner'")
            lines.extend(body)
    if rng.random() < 0.5:
        lines.append("require:")
        for _ in range(rng.randint(1, 2)):
            lines.append(f"  - paths: [{rng.choice(['src/a/**', 'src/b/**', 'lib/**'])}]")
            lines.append(f"    min_state: {rng.choice(['weak', 'proven'])}")
    if rng.random() < 0.3:
        lines.append("evidence:")
        lines.append("  require_non_agent_test: true")
    if rng.random() < 0.4:
        lines.append("exclude:")
        lines.append(f"  paths: [{rng.choice(['docs/**', 'tests/**', 'src/a/**'])}]")
    return "\n".join(lines) + "\n"


def rand_findings(rng: random.Random) -> list[TamperFindingInput]:
    out = []
    for i in range(rng.randint(1, 8)):
        rule = rng.choice(["T001", "T002", "T005", "T012", "T016"])
        check = rng.choice(["unverified_new_dependency", "skip", "x"])
        out.append(TamperFindingInput(f"tf_{i:016x}", rule, check, rng.choice(SEVERITIES), 0.9, "tests/a.py"))
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_generated_policies_parse_inside_the_bounds(seed: int) -> None:
    text = rand_policy(random.Random(seed))
    result = parse_policy(text)
    assert result.policy is not None and not result.errors, (text, result.errors)
    for key, value in result.policy.thresholds.items():
        lo, hi = BOUNDS[key]
        assert lo <= value <= hi


@pytest.mark.parametrize("seed", SEEDS)
def test_head_policy_can_only_tighten(seed: int) -> None:
    rng = random.Random(1000 + seed)
    base = parse_policy(rand_policy(rng, opt_in=True)).policy
    head = parse_policy(rand_policy(rng)).policy
    assert base is not None and head is not None
    merged = resolve_policy(base, head)
    alone = resolve_policy(base)
    assert at_least_as_strict(merged, alone), (base, head)
    # per finding: the effective severity never drops and nothing gets disabled by the head
    for f in rand_findings(rng):
        got = apply_tamper_policy([f], merged.tamper_rules)
        ref = apply_tamper_policy([f], alone.tamper_rules)
        if ref.findings:
            assert got.findings, "head policy disabled a finding the base kept"
            assert severity_rank(got.findings[0].severity) >= severity_rank(ref.findings[0].severity)


@pytest.mark.parametrize("seed", SEEDS)
def test_head_policy_without_opt_in_is_inert(seed: int) -> None:
    rng = random.Random(2000 + seed)
    base = parse_policy(rand_policy(rng, opt_in=False)).policy
    head = parse_policy(rand_policy(rng)).policy
    assert base is not None and head is not None
    assert resolve_policy(base, head) == resolve_policy(base)


@pytest.mark.parametrize("seed", SEEDS)
def test_no_acknowledgement_means_no_lowering_of_high_findings(seed: int) -> None:
    rng = random.Random(3000 + seed)
    eff = resolve_policy(parse_policy(rand_policy(rng, allow_ack=False)).policy)
    for f in rand_findings(rng):
        res = apply_tamper_policy([f], eff.tamper_rules)
        if severity_rank(f.severity) >= severity_rank("high"):
            assert res.findings, "a high finding was disabled without acknowledgement"
            assert severity_rank(res.findings[0].severity) >= severity_rank("high")
            assert not res.acknowledgements


@pytest.mark.parametrize("seed", SEEDS)
def test_acknowledged_lowering_is_always_recorded(seed: int) -> None:
    rng = random.Random(4000 + seed)
    eff = resolve_policy(parse_policy(rand_policy(rng)).policy)
    for f in rand_findings(rng):
        res = apply_tamper_policy([f], eff.tamper_rules)
        original = severity_rank(f.severity)
        now = severity_rank(res.findings[0].severity) if res.findings else -1
        if original >= severity_rank("high") and now < severity_rank("high"):
            assert res.acknowledgements and all(a["reason"] for a in res.acknowledgements)


@pytest.mark.parametrize("seed", SEEDS)
def test_parsers_never_raise_on_mutated_text(seed: int) -> None:
    rng = random.Random(5000 + seed)
    text = rand_policy(rng)
    chars = list(text)
    for _ in range(rng.randint(1, 12)):
        pos = rng.randrange(len(chars))
        chars[pos] = rng.choice(["\t", ":", "-", "[", "]", "{", "&", "*", "'", '"', "#", "\n", " ", "\x00", "é"])
    mutated = "".join(chars)
    assert parse_policy(mutated) is not None
    assert parse_waivers(mutated, today=date(2026, 11, 2)) is not None
    assert miniyaml.parse(mutated) is not None


@pytest.mark.parametrize("seed", range(30))
def test_a_contradicted_criterion_is_never_waived(seed: int) -> None:
    rng = random.Random(6000 + seed)
    ids = [f"c{i}" for i in range(6)]
    states = {c: rng.choice(["proven", "weak", "unevidenced", "contradicted"]) for c in ids}
    body = "".join(
        f"  - id: W{i}\n    criterion: {c}\n    reason: \"a long enough reason for the waiver\"\n"
        "    owner: alice\n    created: 2026-10-30\n    expires: 2026-12-01\n"
        for i, c in enumerate(ids)
    )
    waivers = parse_waivers("version: 1\nwaivers:\n" + body, today=date(2026, 11, 2)).waivers
    out = apply_criterion_waivers({c: CriterionWaiverFacts(states[c]) for c in ids}, waivers)
    for c in ids:
        if states[c] == "contradicted":
            assert c not in out.waived
        else:
            assert c in out.waived


def test_default_config_is_inside_the_bounds() -> None:
    from radius_evidence.policy.effective import default_threshold

    cfg = VerdictV2Config()
    for key, (lo, hi) in BOUNDS.items():
        assert lo <= default_threshold(cfg, key) <= hi
