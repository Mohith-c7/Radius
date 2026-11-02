"""VD-04: tamper severity overrides, allow_disable, requirements, exclusions, repo config."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.policy.apply import (
    CriterionFacts,
    SymbolFacts,
    apply_tamper_policy,
    evaluate_requirements,
    is_excluded_path,
)
from radius_evidence.policy.effective import resolve_policy
from radius_evidence.policy.policy import parse_policy
from radius_evidence.policy.repo_config import (
    collect_repo_config,
    resolve_repo_config,
)

TODAY = date(2026, 11, 2)
ACK = "approved by security, ticket SEC-12"


def pol(body: str, head: str | None = None):
    base = parse_policy("version: 1\n" + body).policy
    assert base is not None
    return resolve_policy(base, parse_policy("version: 1\n" + head).policy if head else None)


def tf(rule: str = "T002", check: str = "skip", sev: str = "medium", fid: str | None = None, path: str = "tests/a.py"):
    return TamperFindingInput(fid or f"tf_{rule}{check}", rule, check, sev, 0.9, path)


def run(body: str, findings):
    return apply_tamper_policy(findings, pol(body).tamper_rules)


# --------------------------------------------------------------- tamper rules

SEVERITY_CASES = [
    # name, rules, finding severity, expected severity (None = dropped)
    ("raise medium to high", "T002: high", "medium", "high"),
    ("lower medium to low", "T002: low", "medium", "low"),
    ("lower medium to info", "T002: info", "medium", "info"),
    ("same severity is a no-op", "T002: medium", "medium", "medium"),
    ("lower high to low is refused", "T002: low", "high", "high"),
    ("lower critical to medium is refused", "T002: medium", "critical", "critical"),
    ("critical to high needs no ack", "T002: high", "critical", "high"),
    ("high to critical", "T002: critical", "high", "critical"),
    ("disable medium rule without ack", "T002:\n      enabled: false", "medium", None),
    ("disable low rule without ack", "T002:\n      enabled: false", "low", None),
    ("disable high rule without ack is refused", "T002:\n      enabled: false", "high", "high"),
    ("disable critical rule without ack is refused", "T002:\n      enabled: false", "critical", "critical"),
    ("disable high with ack", f"T002:\n      enabled: false\n      allow_disable: '{ACK}'", "high", None),
    ("lower high with ack", f"T002:\n      severity: low\n      allow_disable: '{ACK}'", "high", "low"),
    ("enabled true is a no-op", "T002:\n      enabled: true", "high", "high"),
    ("other rule untouched", "T001: low", "high", "high"),
    ("check-specific beats rule-wide", "T002: low\n    T002:skip: high", "medium", "high"),
    ("check-specific only matches its check", "T002:skipif: low", "medium", "medium"),
]


@pytest.mark.parametrize(("name", "rules", "sev", "expected"), SEVERITY_CASES, ids=[c[0] for c in SEVERITY_CASES])
def test_tamper_severity_overrides(name, rules, sev, expected) -> None:
    res = run(f"tamper:\n  rules:\n    {rules}\n", [tf(sev=sev)])
    if expected is None:
        assert res.findings == () and res.disabled == ("tf_T002skip",)
    else:
        assert [f.severity for f in res.findings] == [expected]


def test_refused_lowering_is_reported_and_leaves_the_finding_intact() -> None:
    res = run("tamper:\n  rules:\n    T002:\n      enabled: false\n", [tf(sev="high")])
    assert len(res.findings) == 1 and res.findings[0].severity == "high"
    (refusal,) = res.refused
    assert refusal["code"] == "needs_allow_disable" and refusal["action"] == "disable"
    assert refusal["finding_id"] == "tf_T002skip" and refusal["line"] == 4
    assert res.acknowledgements == ()


def test_allow_disable_is_recorded_as_an_acknowledgement() -> None:
    res = run(f"tamper:\n  rules:\n    T002:\n      enabled: false\n      allow_disable: '{ACK}'\n", [tf(sev="critical")])
    (ack,) = res.acknowledgements
    assert ack["action"] == "disable" and ack["reason"] == ACK and ack["from_severity"] == "critical"
    assert ack["rule"] == "T002" and ack["origin"] == "base" and ack["finding_id"] == "tf_T002skip"
    assert res.changes[0]["change"] == "disabled"


def test_lowering_a_medium_finding_needs_no_acknowledgement() -> None:
    res = run("tamper:\n  rules:\n    T002: low\n", [tf(sev="medium")])
    assert res.acknowledgements == () and res.refused == ()
    assert res.changes == ({"finding_id": "tf_T002skip", "rule": "T002", "change": "severity", "from": "medium", "to": "low"},)


def test_empty_rules_are_the_identity() -> None:
    findings = (tf(sev="high"), tf("T005", "x", "low"))
    res = apply_tamper_policy(findings, ())
    assert res.findings == findings and res.changes == ()


def test_head_raise_only_rule_never_lowers() -> None:
    p = pol("head_policy: tighten_only\n", "tamper:\n  rules:\n    T002: low\n")
    res = apply_tamper_policy([tf(sev="high")], p.tamper_rules)
    assert res.findings[0].severity == "high"
    res = apply_tamper_policy([tf(sev="info")], pol("head_policy: tighten_only\n", "tamper:\n  rules:\n    T002: high\n").tamper_rules)
    assert res.findings[0].severity == "high"


# ------------------------------------------------------------- requirements

def crit(cid: str, state: str, paths=("src/auth/a.py",), counted: int = 1, non_agent: int = 1):
    return CriterionFacts(cid, state, tuple(paths), counted, non_agent)


REQ_POLICY = "require:\n  - paths: [src/auth/**]\n    min_state: proven\n"

REQ_CASES = [
    ("proven meets proven", "proven", "proven", 0),
    ("weak fails proven", "weak", "proven", 1),
    ("unevidenced fails proven", "unevidenced", "proven", 1),
    ("contradicted fails proven", "contradicted", "proven", 1),
    ("excluded is not required", "excluded", "proven", 0),
    ("weak meets weak", "weak", "weak", 0),
    ("unevidenced fails weak", "unevidenced", "weak", 1),
    ("proven meets weak", "proven", "weak", 0),
]


@pytest.mark.parametrize(("name", "state", "need", "unmet"), REQ_CASES, ids=[c[0] for c in REQ_CASES])
def test_required_state_per_path(name, state, need, unmet) -> None:
    body = f"require:\n  - paths: [src/auth/**]\n    min_state: {need}\n"
    res = evaluate_requirements(pol(body), [crit("c1", state)], [])
    assert len(res.required) == unmet
    if unmet:
        assert res.required[0]["criterion_id"] == "c1" and res.required[0]["line"] == 3


def test_criteria_outside_the_required_paths_are_not_checked() -> None:
    res = evaluate_requirements(pol(REQ_POLICY), [crit("c1", "weak", ("src/other/x.py",))], [])
    assert res.required == ()


def test_a_criterion_matches_when_any_linked_path_is_in_scope() -> None:
    res = evaluate_requirements(pol(REQ_POLICY), [crit("c1", "weak", ("src/x.py", "src/auth/b.py"))], [])
    assert len(res.required) == 1


def test_uncovered_changed_code_under_a_required_path_is_unmet() -> None:
    symbols = [SymbolFacts("s1", "src/auth/a.py", False), SymbolFacts("s2", "src/auth/b.py", True), SymbolFacts("s3", "src/x.py", False)]
    res = evaluate_requirements(pol(REQ_POLICY), [], symbols)
    assert [(u["symbol_id"], u["state"]) for u in res.required] == [("s1", "uncovered")]


def test_multiple_requirements_are_all_checked() -> None:
    body = REQ_POLICY + "  - paths: [src/pay/**]\n    min_state: weak\n"
    res = evaluate_requirements(
        pol(body), [crit("a", "weak"), crit("b", "unevidenced", ("src/pay/p.py",)), crit("c", "weak", ("src/pay/q.py",))], []
    )
    assert sorted((u["criterion_id"], u["requirement"]) for u in res.required) == [("a", 0), ("b", 1)]


EVIDENCE_CASES = [
    ("has non-agent test", "proven", 2, 1, 0),
    ("only agent tests", "proven", 2, 0, 1),
    ("weak criterion also checked", "weak", 1, 0, 1),
    ("unevidenced criterion not checked", "unevidenced", 0, 0, 0),
    ("contradicted not checked", "contradicted", 1, 0, 0),
    ("excluded not checked", "excluded", 1, 0, 0),
]


@pytest.mark.parametrize(("name", "state", "counted", "non_agent", "unmet"), EVIDENCE_CASES, ids=[c[0] for c in EVIDENCE_CASES])
def test_minimum_evidence_requires_a_non_agent_test(name, state, counted, non_agent, unmet) -> None:
    p = pol("evidence:\n  require_non_agent_test: true\n")
    res = evaluate_requirements(p, [crit("c1", state, counted=counted, non_agent=non_agent)], [])
    assert len(res.evidence) == unmet and res.required == ()


def test_minimum_evidence_can_be_limited_to_paths() -> None:
    p = pol("evidence:\n  require_non_agent_test: true\n  paths: [src/auth/**]\n")
    res = evaluate_requirements(p, [crit("a", "proven", non_agent=0), crit("b", "proven", ("src/x.py",), non_agent=0)], [])
    assert [u["criterion_id"] for u in res.evidence] == ["a"]


def test_no_requirements_means_nothing_unmet() -> None:
    res = evaluate_requirements(pol(""), [crit("a", "unevidenced")], [SymbolFacts("s", "src/auth/a.py", False)])
    assert res.required == () and res.evidence == ()


@pytest.mark.parametrize(
    ("path", "excluded"),
    [("docs/a.md", True), ("README.md", True), ("src/a.py", False), ("docs", False)],
)
def test_exclusions_only_answer_for_matching_paths(path, excluded) -> None:
    p = pol("exclude:\n  paths: [docs/**, '*.md']\n")
    assert is_excluded_path(p, path) is excluded
    assert is_excluded_path(pol(""), path) is False


# --------------------------------------------------------------- repo config


def reader(files: dict[str, bytes]):
    return lambda path: files.get(path)


def test_collect_reads_both_files_from_the_base_reader_only() -> None:
    base = reader({".radius/policy.yml": b"version: 1\nmode: blocking\n", ".radius/waivers.yml": b"version: 1\n"})
    head = reader({".radius/policy.yml": b"version: 1\nmode: advisory\n", ".radius/waivers.yml": b"version: 1\nwaivers: []\n"})
    cfg = collect_repo_config(base, head, base_ref="abc")
    assert cfg["policy"]["text"].endswith("blocking\n")
    assert cfg["policy"]["sha256"] == hashlib.sha256(b"version: 1\nmode: blocking\n").hexdigest()
    assert "head_policy" not in cfg  # no opt-in: the head is not even read
    assert cfg["base_ref"] == "abc"


def test_head_policy_is_read_only_after_the_base_opt_in() -> None:
    base = reader({".radius/policy.yml": b"version: 1\nhead_policy: tighten_only\n"})
    head = reader({".radius/policy.yml": b"version: 1\nmode: blocking\n"})
    cfg = collect_repo_config(base, head)
    assert cfg["head_policy"]["status"] == "ok"
    res = resolve_repo_config(cfg, VerdictV2Config(), TODAY)
    assert res.policy.mode is not None and res.policy.mode.value == "blocking"


def test_a_pr_that_adds_a_policy_or_waivers_has_no_effect_on_itself() -> None:
    base = reader({})  # nothing on the base branch
    head = reader({".radius/policy.yml": b"version: 1\nthresholds:\n  uim_max: 0.4\n", ".radius/waivers.yml": b"version: 1\n"})
    cfg = collect_repo_config(base, head)
    assert cfg["policy"]["status"] == "absent" and cfg["waivers"]["status"] == "absent"
    res = resolve_repo_config(cfg, VerdictV2Config(), TODAY)
    assert res.config.digest() == VerdictV2Config().digest() and not res.policy.present


@pytest.mark.parametrize(
    ("kwargs", "policy_status", "marker"),
    [
        ({"read_base": None}, "no_base", None),
        ({"read_base": reader({}), "base_available": False}, "unreadable", "policy_unreadable"),
    ],
)
def test_missing_or_unresolvable_base(kwargs, policy_status, marker) -> None:
    cfg = collect_repo_config(kwargs.pop("read_base"), None, **kwargs)
    assert cfg["policy"]["status"] == policy_status
    res = resolve_repo_config(cfg, None, TODAY)
    assert (marker in res.degraded) if marker else not res.degraded


def test_reader_exceptions_never_escape() -> None:
    def boom(path: str) -> bytes:
        raise OSError(path)

    cfg = collect_repo_config(boom, None)
    assert cfg["policy"]["status"] == "unreadable"
    assert "policy_unreadable" in resolve_repo_config(cfg, None, TODAY).degraded


def test_oversized_and_non_utf8_files() -> None:
    cfg = collect_repo_config(reader({".radius/policy.yml": b"x" * 70000, ".radius/waivers.yml": b"\xff\xfe"}), None)
    assert cfg["policy"]["status"] == "too_large" and cfg["waivers"]["status"] == "unreadable"
    res = resolve_repo_config(cfg, None, TODAY)
    assert "policy_invalid" in res.degraded and bool(res.waiver_errors)


def test_invalid_base_policy_is_a_blocking_marker_and_default_config() -> None:
    cfg = collect_repo_config(reader({".radius/policy.yml": b"version: 9\n"}), None)
    res = resolve_repo_config(cfg, None, TODAY)
    assert res.status == "invalid" and res.degraded == ("policy_invalid",)
    assert res.config.digest() == VerdictV2Config().digest()


def test_invalid_head_policy_is_ignored_with_a_note() -> None:
    cfg = collect_repo_config(
        reader({".radius/policy.yml": b"version: 1\nhead_policy: tighten_only\n"}),
        reader({".radius/policy.yml": b"version: 7\n"}),
    )
    res = resolve_repo_config(cfg, None, TODAY)
    assert res.head_note and not res.degraded


def test_resolution_is_deterministic_for_a_given_day() -> None:
    cfg = collect_repo_config(
        reader({".radius/policy.yml": b"version: 1\nthresholds:\n  tau_support: 0.7\n"}), None, base_ref="b"
    )
    a = resolve_repo_config(cfg, None, TODAY)
    b = resolve_repo_config(cfg, None, TODAY)
    assert a.config.digest() == b.config.digest() and a.policy == b.policy
    assert resolve_repo_config(None, None, TODAY).policy.present is False
    assert resolve_repo_config({}, None, TODAY).status == "absent"
