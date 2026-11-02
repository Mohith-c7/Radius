"""VD-05: waivers.yml validity, expiry, scope, non-waivable cases and the audit record."""

from __future__ import annotations

from datetime import date

import pytest
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.policy.apply import (
    CriterionWaiverFacts,
    apply_criterion_waivers,
    apply_finding_waivers,
    audit_digest,
    unused_waivers,
)
from radius_evidence.policy.waivers import parse_waivers

TODAY = date(2026, 11, 2)
REASON = "Legacy fixture is regenerated nightly, tracked in SEC-42"
FID = "tf_0123456789abcdef"


def waiver(**over: object) -> str:
    fields: dict[str, object] = {
        "id": "W-1",
        "finding": FID,
        "reason": f'"{REASON}"',
        "owner": "alice",
        "created": "2026-10-30",
        "expires": "2026-12-01",
    }
    fields.update(over)
    lines: list[str] = []
    for key, value in fields.items():
        if value is not None:
            lines.append(("  - " if not lines else "    ") + f"{key}: {value}")
    return "version: 1" + chr(10) + "waivers:" + chr(10) + chr(10).join(lines) + chr(10)


def parsed(text: str, today: date = TODAY):
    return parse_waivers(text, today=today)


def test_valid_finding_waiver() -> None:
    r = parsed(waiver())
    assert len(r.waivers) == 1 and not r.ignored and not r.errors
    w = r.waivers[0]
    assert (w.id, w.kind, w.target, w.owner) == ("W-1", "finding", FID, "alice")
    assert w.expires == date(2026, 12, 1) and w.created == date(2026, 10, 30)
    assert w.to_dict()["expires"] == "2026-12-01"


def test_valid_rule_and_criterion_waivers() -> None:
    text = (
        "version: 1\nwaivers:\n"
        "  - id: R-1\n    rule: T002\n    paths: [tests/legacy/**]\n"
        f"    reason: \"{REASON}\"\n    owner: '@team/qa'\n    created: 2026-10-01\n    expires: 2026-11-30\n"
        "  - id: C-1\n    criterion: crit_9\n"
        f"    reason: \"{REASON}\"\n    owner: bob@example.com\n    created: 2026-10-01\n    expires: 2026-11-30\n"
    )
    r = parsed(text)
    assert [w.kind for w in r.waivers] == ["rule", "criterion"] and not r.ignored


INVALID = [
    ("no id", dict(id=None), "invalid_id"),
    ("bad id", dict(id="'a b'"), "invalid_id"),
    ("no target", dict(finding=None), "target"),
    ("two targets", dict(rule="T002"), "target"),
    ("bad finding id", dict(finding="nope"), "invalid_target"),
    ("short reason", dict(reason="'too short'"), "reason"),
    ("missing reason", dict(reason=None), "reason"),
    ("long reason", dict(reason='"' + "x" * 501 + '"'), "reason"),
    ("missing owner", dict(owner=None), "owner"),
    ("bad owner", dict(owner="'!!'"), "owner"),
    ("missing created", dict(created=None), "created"),
    ("bad created", dict(created="2026-13-40"), "created"),
    ("missing expires", dict(expires=None), "expires"),
    ("bad expires", dict(expires="tomorrow"), "expires"),
    ("created in future", dict(created="2026-11-03", expires="2026-12-01"), "created_in_future"),
    ("expires before created", dict(created="2026-10-30", expires="2026-10-01"), "expires_before_created"),
    ("lifetime 91 days", dict(created="2026-09-01", expires="2026-12-01"), "lifetime_exceeds_max"),
    ("expired yesterday", dict(created="2026-10-01", expires="2026-11-01"), "expired"),
    ("bad paths", dict(paths="['../x']"), "paths"),
    ("paths not list", dict(paths="{a: 1}"), None),
]


@pytest.mark.parametrize(("name", "over", "code"), INVALID, ids=[c[0] for c in INVALID])
def test_invalid_waivers_are_ignored_and_reported(name, over, code) -> None:
    r = parsed(waiver(**over))
    if code is None:  # a syntax problem makes the whole file unusable
        assert r.structural_failure and not r.waivers
        return
    assert not r.waivers
    assert [i.code for i in r.ignored] == [code], r.ignored
    assert r.ignored[0].message


def test_lifetime_boundary_is_exactly_90_days() -> None:
    ok = parsed(waiver(created="2026-09-03", expires="2026-12-02"))  # 90 days
    assert len(ok.waivers) == 1
    bad = parsed(waiver(created="2026-09-02", expires="2026-12-02"))  # 91 days
    assert bad.ignored[0].code == "lifetime_exceeds_max"


@pytest.mark.parametrize(
    ("today", "active"),
    [
        (date(2026, 11, 2), True),
        (date(2026, 12, 1), True),  # the expiry day itself still counts
        (date(2026, 12, 2), False),
        (date(2027, 6, 1), False),
    ],
)
def test_expiry_follows_the_date_passed_in(today, active) -> None:
    r = parsed(waiver(created="2026-10-30", expires="2026-12-01"), today=today)
    assert bool(r.waivers) is active
    assert (not active) == bool(r.ignored and r.ignored[0].code == "expired")


def test_rule_waiver_needs_paths() -> None:
    r = parsed(waiver(finding=None, rule="T002"))
    assert r.ignored[0].code == "rule_needs_paths"


def test_duplicate_ids_keep_only_the_first() -> None:
    text = waiver() + "  - id: W-1\n    finding: tf_aaaaaaaaaaaaaaaa\n"
    r = parsed(text)
    assert [w.target for w in r.waivers] == [FID]
    assert r.ignored[0].code == "duplicate_id"


def test_a_bad_entry_does_not_hide_the_good_ones() -> None:
    text = waiver() + "  - id: W-2\n    finding: nope\n"
    r = parsed(text)
    assert len(r.waivers) == 1 and len(r.ignored) == 1


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("", "empty"),
        ("waivers: []\n", "version"),
        ("version: 3\nwaivers: []\n", "version"),
        ("- a\n", "mapping"),
        ("version: 1\nwaivers: 5\n", "'waivers' must be a list"),
        ("version: 1\nwaivers: [\n", "line 2"),
    ],
)
def test_structural_failures_ignore_every_waiver(text, needle) -> None:
    r = parsed(text)
    assert r.structural_failure and not r.waivers
    assert any(needle in str(e) for e in r.errors)


def test_unknown_keys_warn_and_empty_list_is_fine() -> None:
    r = parsed("version: 1\ncolour: red\nwaivers:\n")
    assert not r.structural_failure and not r.waivers
    assert any("colour" in w.message for w in r.warnings)
    r = parsed(waiver(note="hello"))
    assert len(r.waivers) == 1 and any("note" in w.message for w in r.warnings)


def test_non_mapping_entry_is_ignored() -> None:
    r = parsed("version: 1\nwaivers:\n  - just text\n")
    assert r.ignored[0].code == "malformed"


def test_too_many_waivers_are_truncated_with_an_error() -> None:
    body = "".join(
        f"  - id: W{i}\n    finding: tf_{i:016x}\n    reason: \"{REASON}\"\n"
        "    owner: a\n    created: 2026-10-30\n    expires: 2026-12-01\n"
        for i in range(205)
    )
    r = parsed("version: 1\nwaivers:\n" + body)
    assert len(r.waivers) == 200 and any("first 200" in str(e) for e in r.errors)


# ------------------------------------------------------------------ application


def finding(fid: str = FID, rule: str = "T002", check: str = "skip", path: str = "tests/a.py", sev: str = "high"):
    return TamperFindingInput(fid, rule, check, sev, 0.9, path, reason="because")


def make(text: str):
    return parsed(text).waivers


def test_finding_waiver_moves_the_finding_to_waived_with_reason_and_owner() -> None:
    out = apply_finding_waivers([finding(), finding("tf_ffffffffffffffff")], make(waiver()))
    assert [f.finding_id for f in out.remaining] == ["tf_ffffffffffffffff"]
    (w,) = out.waived
    assert w["waived"] is True and w["finding_id"] == FID and w["severity"] == "high"
    assert w["waiver"] == {"id": "W-1", "reason": REASON, "owner": "alice", "expires": "2026-12-01"}
    (a,) = out.applied
    assert a["id"] == "W-1" and a["finding_ids"] == [FID] and a["owner"] == "alice"


RULE_WAIVER = (
    "version: 1\nwaivers:\n  - id: R-1\n    rule: {rule}\n    paths: [tests/legacy/**]\n"
    f"    reason: \"{REASON}\"\n    owner: alice\n    created: 2026-10-30\n    expires: 2026-12-01\n"
)


@pytest.mark.parametrize(
    ("rule", "f_rule", "f_check", "path", "waived"),
    [
        ("T002", "T002", "skip", "tests/legacy/a.py", True),
        ("T002", "T002", "skipif", "tests/legacy/sub/a.py", True),
        ("T002:skip", "T002", "skip", "tests/legacy/a.py", True),
        ("T002:skip", "T002", "skipif", "tests/legacy/a.py", False),
        ("T002", "T002", "skip", "tests/new/a.py", False),
        ("T002", "T001", "skip", "tests/legacy/a.py", False),
    ],
)
def test_rule_waiver_matches_rule_check_and_path_scope(rule, f_rule, f_check, path, waived) -> None:
    out = apply_finding_waivers(
        [finding(rule=f_rule, check=f_check, path=path)], make(RULE_WAIVER.format(rule=rule))
    )
    assert bool(out.waived) is waived and bool(out.remaining) is (not waived)


def test_finding_waiver_with_paths_must_match_the_path() -> None:
    text = waiver(paths="[tests/x/**]")
    assert apply_finding_waivers([finding(path="tests/y/a.py")], make(text)).waived == ()
    assert len(apply_finding_waivers([finding(path="tests/x/a.py")], make(text)).waived) == 1


def test_first_matching_waiver_wins_and_unused_ones_are_reported() -> None:
    text = waiver() + (
        f"  - id: W-2\n    finding: {FID}\n    reason: \"{REASON}\"\n    owner: bob\n"
        "    created: 2026-10-30\n    expires: 2026-12-01\n"
        "  - id: W-3\n    finding: tf_eeeeeeeeeeeeeeee\n"
        f"    reason: \"{REASON}\"\n    owner: bob\n    created: 2026-10-30\n    expires: 2026-12-01\n"
    )
    waivers = make(text)
    out = apply_finding_waivers([finding()], waivers)
    assert out.waived[0]["waiver"]["id"] == "W-1"
    unused = unused_waivers(waivers, {a["id"] for a in out.applied})
    assert sorted(u["id"] for u in unused) == ["W-2", "W-3"]
    assert all(u["code"] == "unused" for u in unused)


CRIT = (
    "version: 1\nwaivers:\n  - id: C-1\n    criterion: c_1\n{paths}"
    f"    reason: \"{REASON}\"\n    owner: alice\n    created: 2026-10-30\n    expires: 2026-12-01\n"
)


@pytest.mark.parametrize("state", ["unevidenced", "weak", "proven"])
def test_criterion_waiver_applies_to_non_contradicted_states(state) -> None:
    out = apply_criterion_waivers({"c_1": CriterionWaiverFacts(state)}, make(CRIT.format(paths="")))
    assert "c_1" in out.waived and out.applied[0]["criterion_id"] == "c_1" and not out.ignored


def test_a_contradicted_criterion_can_never_be_waived() -> None:
    out = apply_criterion_waivers({"c_1": CriterionWaiverFacts("contradicted")}, make(CRIT.format(paths="")))
    assert out.waived == {} and out.applied == ()
    assert out.ignored[0]["code"] == "not_waivable_contradicted"


def test_criterion_waiver_scope_uses_the_linked_paths() -> None:
    text = CRIT.format(paths="    paths: [src/auth/**]\n")
    miss = apply_criterion_waivers({"c_1": CriterionWaiverFacts("weak", ("src/other.py",))}, make(text))
    assert miss.ignored[0]["code"] == "scope_mismatch" and not miss.waived
    hit = apply_criterion_waivers({"c_1": CriterionWaiverFacts("weak", ("src/auth/a.py",))}, make(text))
    assert "c_1" in hit.waived


def test_unknown_criterion_waiver_is_left_for_the_unused_report() -> None:
    out = apply_criterion_waivers({"other": CriterionWaiverFacts("weak")}, make(CRIT.format(paths="")))
    assert out.waived == {} and out.ignored == ()


def test_no_waiver_kind_can_address_a_ci_case() -> None:
    # ids of CI cases / tests are not valid finding, rule or criterion targets in the strict
    # grammar, so a waiver naming one is rejected at parse time.
    r = parsed(waiver(finding=None, criterion=None, **{"test": "tests/a.py::test_x"}))
    assert not r.waivers and r.ignored[0].code == "target"


def test_audit_digest_is_stable_and_sensitive() -> None:
    a = {"applied": [{"id": "W-1"}], "ignored": []}
    assert audit_digest(a) == audit_digest(dict(a))
    assert audit_digest(a) != audit_digest({"applied": [], "ignored": []})
    assert audit_digest(a).startswith("sha256:")
