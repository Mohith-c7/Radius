"""DEC-043: standing ``.radius/intent.yml`` criteria a PR does not touch are excluded.

Uses the repository's own ``.radius/intent.yml`` (7 standing criteria) as the base-branch
spec of a scratch git repository, and the real Stage A producers.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from radius_evidence.domain.inputs import CriterionInput
from radius_evidence.policy.scope import NOT_AFFECTED, criterion_in_scope, path_in_scope
from radius_github.verdict_v2.markdown import render_check_run, render_comment
from radius_github.verdict_v2.view import VerdictV2View
from radius_intent.infrastructure.extraction.candidates import Collector
from radius_intent.infrastructure.extraction.spec_file import extract_spec
from radius_intent.infrastructure.extraction.text import split_lines
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_testing.domain.entities import ReportedTestCase
from radius_worker.verdict_v2 import sources
from radius_worker.verdict_v2.collect import VerdictStageACollector
from radius_worker.verdict_v2.scoring import run_verdict_v2_best_effort
from radius_worker.verdict_v2.sources import IntentFacts, StaticIntent

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".radius" / "intent.yml").is_file())
SPEC = (ROOT / ".radius" / "intent.yml").read_text(encoding="utf-8")
FLAG = "packages/shared/src/radius_shared/verdict_v2_flag.py"
FLAG_TEST = "packages/shared/tests/test_verdict_v2_scaffold.py"
FLAG_HINT = f"{FLAG_TEST}::test_flag_parsing_table"
FLAG_SRC = (
    "def parse_mode(value):\n"
    "    v = str(value).strip().lower()\n"
    "    return v if v in ('off', 'shadow', 'on') else 'off'\n"
)
FLAG_TEST_SRC = (
    "from radius_shared.verdict_v2_flag import parse_mode\n\n\n"
    "def test_flag_parsing_table():\n"
    "    assert parse_mode('on') == 'on'\n"
    "    assert parse_mode('shadow') == 'shadow'\n"
    "    assert parse_mode('typo') == 'off'\n"
)
PASSED = ReportedTestCase(FLAG_TEST, None, "test_flag_parsing_table", "passed")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",  # noqa: S607
         "-c", "core.autocrlf=false", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pr(tmp_path: Path, changes: dict[str, str]) -> NS:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    _write(repo, FLAG, FLAG_SRC)
    _write(repo, "packages/shared/src/radius_shared/__init__.py", "")
    _write(repo, FLAG_TEST, FLAG_TEST_SRC)
    _write(repo, ".radius/intent.yml", SPEC)
    _write(repo, "docker-compose.yml", "services: {}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    for rel, text in changes.items():
        _write(repo, rel, text)
    _git(repo, "commit", "-q", "-am", "change")
    return NS(repository_id=uuid4(), repository_path=repo, diff_text=None,
              base_ref="develop", head_ref=_git(repo, "rev-parse", "HEAD"))


def _criteria(spec_text: str) -> tuple[NS, ...]:
    """The spec's criteria as the intent snapshot would carry them (proposed, spec_file)."""

    col = Collector("spec")
    extract_spec(split_lines(spec_text), "spec", col)
    return tuple(
        NS(id=c.hints.label, text=c.text, state=NS(value="proposed"), weight=c.weight,
           testability="behavioral_testable",
           hints=NS(paths=tuple(c.hints.paths), tests=tuple(c.hints.tests)),
           origin=NS(source=NS(kind=NS(value="spec_file")),
                     extraction_method=NS(value="deterministic")))
        for c in col.candidates
    )


class _Outcomes:
    def __init__(self, *cases):
        self.cases = cases

    def load(self, analysis_id, stage_a):  # noqa: ARG002
        upload = NS(commit_sha=stage_a.head_sha, cases=self.cases, result=NS(flaky_tests=()),
                    provenance_status="verified_provenance")
        return sources.outcomes_from_uploads([upload] if self.cases else [], stage_a)


def _run(cmd: NS, *cases, spec_text: str = SPEC, extra=()):
    collector = VerdictStageACollector(
        StaticIntent(IntentFacts(criteria=(*_criteria(spec_text), *extra)))
    )
    report = run_verdict_v2_best_effort(
        mode=VerdictV2Mode.ON, analysis_id=uuid4(), command=cmd, collector=collector,
        outcomes=_Outcomes(*cases), clock=lambda: datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert report.status == "ok", report.reason_code
    return report, {c["criterion_id"]: c for c in report.payload["criteria"]}


def test_the_repository_spec_has_seven_standing_criteria_with_paths() -> None:
    crits = _criteria(SPEC)
    assert len(crits) == 7
    assert all(c.hints.paths for c in crits)


def test_compose_only_pr_excludes_every_standing_criterion_and_is_not_verified(tmp_path) -> None:
    cmd = _pr(tmp_path, {"docker-compose.yml": "services:\n  api: {}\n"})
    report, rows = _run(cmd, PASSED)
    assert len(rows) == 7
    for row in rows.values():
        assert row["state"] == "excluded"
        assert row["reasons"][0]["code"] == NOT_AFFECTED
        assert row["scope"]["in_scope"] is False and row["scope"]["paths"]
    assert report.payload["summary"]["excluded"] == 7
    assert report.payload["summary"]["uim"] == 0.0
    just = report.payload["justification"]
    assert report.payload["verdict"] == "insufficient_evidence"
    assert just["decided_by"] == "R2e"  # no applicable intent: never a vacuous "verified"
    fired = {r["id"] for r in just["rules"] if r["fired"]}
    assert "R2b" not in fired and "R2c" not in fired

    body = render_comment(VerdictV2View.from_payload(report.payload))
    assert body.count("not scored (not affected by this PR)") == 7
    check = render_check_run(VerdictV2View.from_payload(report.payload))
    assert check.conclusion != "success"


def test_compose_only_pr_without_ci_results_is_not_verified_either(tmp_path) -> None:
    report, rows = _run(_pr(tmp_path, {"docker-compose.yml": "x: 1\n"}))
    assert {r["state"] for r in rows.values()} == {"excluded"}
    assert report.payload["verdict"] != "verified"


def test_pr_touching_the_flag_module_scores_the_flag_criterion(tmp_path) -> None:
    cmd = _pr(tmp_path, {FLAG: FLAG_SRC.replace("strip().lower()", "lower().strip()")})
    report, rows = _run(cmd, PASSED)
    flag = rows["flag-fail-closed"]
    assert flag["scope"] == {"paths": [FLAG], "in_scope": True}
    assert flag["state"] == "proven", flag["reasons"]
    others = [r for cid, r in rows.items() if cid != "flag-fail-closed"]
    assert len(others) == 6 and all(r["state"] == "excluded" for r in others)
    assert report.payload["verdict"] == "verified", report.payload["justification"]["decided_by"]


def test_failing_hinted_test_still_fails_an_in_scope_criterion(tmp_path) -> None:
    cmd = _pr(tmp_path, {FLAG: FLAG_SRC.replace("'off'\n", "'on'\n")})
    failed = ReportedTestCase(FLAG_TEST, None, "test_flag_parsing_table", "failed")
    report, rows = _run(cmd, failed)
    assert rows["flag-fail-closed"]["state"] == "contradicted"
    assert report.payload["verdict"] == "failed"


def test_editing_paths_in_the_pr_cannot_move_a_criterion_out_of_scope(tmp_path) -> None:
    dodged = SPEC.replace(f'paths: ["{FLAG}"]', 'paths: ["nowhere/**"]')
    assert dodged != SPEC
    cmd = _pr(tmp_path, {
        FLAG: FLAG_SRC.replace("'off'\n", "'on'\n"),
        ".radius/intent.yml": dodged,
    })
    report, rows = _run(cmd, spec_text=dodged)  # the snapshot carries the HEAD spec
    flag = rows["flag-fail-closed"]
    assert flag["provenance"] == "author_head_spec"
    assert flag["scope"] == {"paths": [FLAG], "in_scope": True}  # base copy decides
    assert flag["state"] != "excluded"
    assert report.payload["verdict"] != "verified"


def test_pr_derived_criteria_are_never_scoped_out(tmp_path) -> None:
    body = NS(id="pr-1", text="the compose file defines the api service", state=NS(value="proposed"),
              weight=1.0, testability="behavioral_testable",
              hints=NS(paths=("src/never.py",), tests=()),
              origin=NS(source=NS(kind=NS(value="pr_body")),
                        extraction_method=NS(value="deterministic")))
    _report, rows = _run(_pr(tmp_path, {"docker-compose.yml": "x: 1\n"}), PASSED, extra=(body,))
    assert rows["pr-1"]["state"] != "excluded" and "scope" not in rows["pr-1"]


# ------------------------------------------------------------------ path semantics


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        (FLAG, FLAG, True),
        ("packages/shared", FLAG, True),  # a directory
        ("packages/shared/", FLAG, True),
        ("packages/shared/**", FLAG, True),
        ("packages/*/src/**/*.py", FLAG, True),
        ("packages/share", FLAG, False),  # not a path prefix
        ("packages/shared/src/radius_shared/verdict_v2_flag.py", "docker-compose.yml", False),
        ("**/*.yml", "docker-compose.yml", True),
    ],
)
def test_path_in_scope(pattern, path, expected) -> None:
    assert path_in_scope(pattern, path) is expected


def test_unknown_facts_keep_a_criterion_in_scope() -> None:
    assert criterion_in_scope(None, ["a.py"]) is True
    assert criterion_in_scope((), ["a.py"]) is True
    assert criterion_in_scope(("src/**",), None) is True
    assert criterion_in_scope(("src/**x",), ["a.py"]) is True  # invalid glob
    assert criterion_in_scope(("src/**",), []) is False
    assert criterion_in_scope(("src/**",), ["src/a.py"]) is True


def test_scope_fields_round_trip_and_are_omitted_when_unset() -> None:
    c = CriterionInput("c", "t", 1.0, "behavioral_testable", "proposed", scope_paths=("a/",))
    assert CriterionInput.from_dict(c.to_dict()) == c
    assert "scope_paths" not in CriterionInput("c", "t", 1.0, "x", "proposed").to_dict()
