"""``tests:`` hints link directly, the base ref is recorded as a commit, budgets come from env.

Regression for a production run on a 0.1 CPU host: a pull request that changed only
docker-compose.yml got "no linked test" on every standing criterion of a base-branch
``.radius/intent.yml``, because hints were resolved only against tests reached through
changed symbols, and the policy line said "base branch (unknown)" because the base was
recorded as ``origin/<branch>`` instead of a commit.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_testing.domain.entities import ReportedTestCase
from radius_worker.config import WorkerSettings
from radius_worker.verdict_v2 import sources
from radius_worker.verdict_v2.collect import (
    CollectLimits,
    Producers,
    VerdictStageACollector,
    default_link_tests,
    default_repo_config,
)
from radius_worker.verdict_v2.link_scope import scope_link_sources
from radius_worker.verdict_v2.scoring import collect_limits, run_verdict_v2_best_effort
from radius_worker.verdict_v2.sources import IntentFacts, StaticIntent

HINT = "pkg/tests/test_flag.py::test_flag_parsing_table"
TEST_SRC = (
    "from pkg.flag import parse\n\n\n"
    "def test_flag_parsing_table():\n    assert parse('on') is True\n    assert parse('x') is False\n\n\n"
    "def test_other():\n    assert parse('off') is False\n"
)
SPEC = (
    "version: 1\ncriteria:\n  - id: flag-fail-closed\n    text: an unknown flag value is off\n"
    f"    weight: 0.1\n    tests:\n      - {HINT}\n"
)


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


def _pr_repo(
    tmp_path: Path, change: tuple[str, str], extra: tuple[tuple[str, str], ...] = ()
) -> NS:
    """Base branch ``develop`` holds the spec and tests; the PR changes one file."""

    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    _write(repo, "pkg/flag.py", "def parse(v):\n    return v in ('on', 'true', '1')\n")
    _write(repo, "pkg/tests/test_flag.py", TEST_SRC)
    for rel, text in extra:
        _write(repo, rel, text)
    _write(repo, ".radius/intent.yml", SPEC)
    _write(repo, "docker-compose.yml", "services: {}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, *change)
    _git(repo, "commit", "-q", "-am", "change")
    head = _git(repo, "rev-parse", "HEAD")
    return NS(
        repository_id=uuid4(), repository_path=repo, diff_text=None,
        base_ref="develop", head_ref=head, base_sha=_git(repo, "rev-parse", "develop"),
    )


@pytest.fixture
def compose_only_pr(tmp_path: Path) -> NS:
    return _pr_repo(tmp_path, ("docker-compose.yml", "services:\n  api: {}\n"))


@pytest.fixture
def code_pr(tmp_path: Path) -> NS:
    return _pr_repo(
        tmp_path, ("pkg/flag.py", "def parse(v):\n    return str(v).lower() in ('on', 'true', '1')\n")
    )


def spec_criterion(tests=(HINT,), paths=("pkg/flag.py",)):
    return NS(
        id="flag-fail-closed", text="an unknown flag value is off", state=NS(value="proposed"),
        weight=0.1, testability="behavioral_testable",
        hints=NS(paths=paths, tests=tests),
        origin=NS(source=NS(kind=NS(value="spec_file")), extraction_method=NS(value="deterministic")),
    )


class _Outcomes:
    def __init__(self, *cases):
        self.cases = cases

    def load(self, analysis_id, stage_a):  # noqa: ARG002
        upload = NS(commit_sha=stage_a.head_sha, cases=self.cases, result=NS(flaky_tests=()),
                    provenance_status="verified_provenance")
        return sources.outcomes_from_uploads([upload] if self.cases else [], stage_a)


def _run(cmd: NS, *cases, criteria=None, producers=None, limits=None):
    collector = VerdictStageACollector(
        StaticIntent(IntentFacts(criteria=criteria or (spec_criterion(),))),
        producers=producers, limits=limits,
    )
    return run_verdict_v2_best_effort(
        mode=VerdictV2Mode.ON, analysis_id=uuid4(), command=cmd, collector=collector,
        outcomes=_Outcomes(*cases), clock=lambda: datetime(2026, 11, 20, tzinfo=UTC),
    )


# ------------------------------------------------------------------ the whole chain


PASSED = ReportedTestCase("pkg/tests/test_flag.py", None, "test_flag_parsing_table", "passed")


def _assert_trusted_hint_edge(report, base_sha: str) -> None:
    assert report.status == "ok", report.reason_code
    stage_a = report.bundle["stage_a"]
    (crit,) = stage_a["criteria"]
    assert (crit["provenance"], crit["hints_provenance"]) == ("base_spec", "base_spec")
    (edge,) = [e for e in stage_a["criterion_test"] if e["method"] == "intent_yml_hint"]
    assert edge["test_id"] == HINT
    assert edge["weight"] == 1.0  # base_spec: no author-hint cap
    assert stage_a["repo_config"]["base_ref"] == base_sha


def test_chain_base_spec_hint_link_ci_outcome_supports_the_criterion(code_pr) -> None:
    """base_spec provenance -> hinted test linked -> Stage B with a passing CI case -> proven."""

    report = _run(code_pr, PASSED)
    _assert_trusted_hint_edge(report, code_pr.base_sha)
    (row,) = report.payload["criteria"]
    assert row["state"] == "proven", row["reasons"]
    assert "author_supplied_hint" not in row["flags"]
    assert (HINT, "counted") in [(i["test_id"], i["status"]) for i in row["items"]]


PARAM_TEST_SRC = (
    "import pytest\n\nfrom pkg.flag import parse\n\n\n"
    "@pytest.mark.parametrize(('raw', 'expected'), [('on', True), ('x', False), ('1', True)])\n"
    "def test_flag_parsing_table(raw, expected):\n    assert parse(raw) is expected\n"
)
MORE_SRC = "from pkg.flag import parse\n\n\ndef test_more():\n    assert parse('on')\n"


def test_hinted_test_keeps_its_symbol_link_when_whole_repo_linking_times_out(
    tmp_path: Path,
) -> None:
    """Production PR #184: whole-repo linking timed out on a 0.1 CPU host.

    The base_spec ``tests:`` hint still linked the criterion to the test, but the test had
    no symbol path, so it showed link strength 0.00 and ``gated:test_link_below_min``
    although it calls the changed function directly.
    """

    cmd = _pr_repo(
        tmp_path,
        ("pkg/flag.py", "def parse(v):\n    return str(v).strip().lower() in ('on', 'true', '1')\n"),
        extra=(("pkg/tests/test_flag.py", PARAM_TEST_SRC), ("pkg/tests/test_more.py", MORE_SRC)),
    )

    def link_tests(srcs, targets):
        if "pkg/tests/test_more.py" in srcs:  # the whole-repo call
            raise TimeoutError
        return default_link_tests(srcs, targets)

    cases = [
        ReportedTestCase("pkg/tests/test_flag.py", None, f"test_flag_parsing_table[{c}]", "passed")
        for c in ("on-True", "x-False", "1-True")
    ]
    report = _run(cmd, *cases, producers=Producers(link_tests=link_tests))
    stage_a = report.bundle["stage_a"]
    assert "producer_timeout:symbol_test_links" in stage_a["degraded"]
    assert [(e["test_id"], e["kind"]) for e in stage_a["symbol_test"]] == [(HINT, "direct_call")]
    (row,) = report.payload["criteria"]
    (item,) = [i for i in row["items"] if i["test_id"] == HINT]
    assert (item["status"], item["l_st"]) == ("counted", 0.9), item


def test_compose_only_pr_links_the_hint_but_stage_b_gates_it_without_a_changed_symbol(
    compose_only_pr,
) -> None:
    """The hint is linked and shown with its CI outcome.

    Stage B still gates a test that reaches no changed symbol (``l_cs = l_st = 0``,
    design: "audit rows, gated"). The criterion has no ``paths:``, so DEC-043 keeps it in
    scope (a criterion with paths would be excluded as not affected, see
    test_verdict_v2_scope.py).
    """

    report = _run(compose_only_pr, PASSED, criteria=(spec_criterion(paths=()),))
    _assert_trusted_hint_edge(report, compose_only_pr.base_sha)
    (row,) = report.payload["criteria"]
    assert [(i["test_id"], i["outcome"]) for i in row["items"]] == [(HINT, "passed")]
    assert row["items"][0]["status"] == "gated:test_link_below_min"
    assert "author_supplied_hint" not in row["flags"]


def test_without_ci_results_the_hint_is_linked_and_awaits_ci(compose_only_pr) -> None:
    report = _run(compose_only_pr, criteria=(spec_criterion(paths=()),))
    assert report.status == "ok", report.reason_code
    assert [e["test_id"] for e in report.bundle["stage_a"]["criterion_test"]] == [HINT]
    (row,) = report.payload["criteria"]
    assert "pending_results" in row["flags"]


def test_hint_to_a_missing_test_never_invents_one(compose_only_pr) -> None:
    crit = spec_criterion(tests=("pkg/tests/test_flag.py::test_nope", "../outside.py::test_x"))
    report = _run(compose_only_pr, criteria=(crit,))
    stage_a = report.bundle["stage_a"]
    assert stage_a["criterion_test"] == []
    assert "adapter_dropped:hint_unresolved" in stage_a["degraded"]


def test_hinted_tests_link_when_the_whole_repo_read_times_out(compose_only_pr, caplog) -> None:
    def slow_read(root):
        time.sleep(4.0)
        return {}, False

    caplog.set_level(logging.WARNING)
    report = _run(
        compose_only_pr,
        producers=Producers(read_sources=slow_read),
        limits=CollectLimits(step_timeout_s=2.0),
    )
    stage_a = report.bundle["stage_a"]
    assert "producer_timeout:read_sources" in stage_a["degraded"]
    assert [e["test_id"] for e in stage_a["criterion_test"]] == [HINT]
    timed_out = [r for r in caplog.records if r.getMessage() == "Verdict v2 producer timed out"]
    assert [r.producer for r in timed_out] == ["read_sources"]


# ------------------------------------------------------------------ base ref, budgets


def test_repo_config_records_the_base_commit_not_the_branch_name(compose_only_pr) -> None:
    config = default_repo_config(compose_only_pr)
    assert config["base_ref"] == compose_only_pr.base_sha
    compose_only_pr.base_ref = "no-such-branch"
    missing = default_repo_config(compose_only_pr)
    assert missing["base_ref"] == "no-such-branch"
    assert missing["policy"]["status"] == "unreadable"


def test_stage_a_budgets_come_from_the_worker_settings(monkeypatch) -> None:
    defaults = collect_limits(WorkerSettings())
    assert (defaults.timeout_s, defaults.step_timeout_s) == (300.0, 120.0)
    monkeypatch.setenv("RADIUS_VERDICT_V2_STAGE_A_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("RADIUS_VERDICT_V2_STEP_TIMEOUT_SECONDS", "400")
    limits = collect_limits(WorkerSettings(), CollectLimits(mutation_timeout_s=99.0))
    assert (limits.timeout_s, limits.step_timeout_s, limits.mutation_timeout_s) == (900, 400, 99)
    assert collect_limits(NS()) == CollectLimits()


def test_read_hinted_files_stays_inside_the_checkout(tmp_path: Path) -> None:
    _write(tmp_path, "t/test_a.py", "def test_a(): pass\n")
    _write(tmp_path, "t/notes.txt", "x")
    got = sources.read_hinted_files(
        tmp_path, ["t/test_a.py", "../x.py", "/etc/test.py", "C:/x.py", "t/notes.txt", "t\\test_a.py"]
    )
    assert got == {"t/test_a.py": "def test_a(): pass\n"}


# ------------------------------------------------------------------ link scoping


def _target(path: str, name: str = "parse"):
    return NS(path=path, qualified_name=name, language="python")


SCOPE_SOURCES = {
    "pkg/flag.py": "def parse(v): ...\n",
    "pkg/api.py": "from pkg.flag import parse\n",
    "pkg/__init__.py": "from .api import *\n",
    "tests/test_api.py": "from pkg import api\n",  # reaches flag through api
    "tests/test_unrelated.py": "def test_x(): assert 1\n",
    "tests/test_hinted.py": "def test_h(): assert 1\n",
    "fix/conftest.py": "import pkg\n",
    "fix/test_uses_fixture.py": "def test_f(client): assert client\n",
    "tests/test_named.py": "def test_parse_table(): assert 1\n",
    "lib/helpers.py": "x = 1\n",
}


def test_scope_keeps_reaching_tests_and_every_non_test_file() -> None:
    scoped = scope_link_sources(SCOPE_SOURCES, [_target("pkg/flag.py")], keep={"tests/test_hinted.py"})
    assert set(SCOPE_SOURCES) - set(scoped) == {"tests/test_unrelated.py"}


def test_scope_does_nothing_without_python_targets_or_when_it_cannot_settle() -> None:
    assert scope_link_sources(SCOPE_SOURCES, [_target("web/a.ts")]) == SCOPE_SOURCES
    assert scope_link_sources(SCOPE_SOURCES, [_target("pkg/flag.py")], max_rounds=1) == SCOPE_SOURCES
