"""Offline tests for scripts/github_app_scenarios.py (pure logic + a fake gh/git shell)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "github_app_scenarios.py"
_spec = importlib.util.spec_from_file_location("github_app_scenarios", _SCRIPT)
gas = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gas
_spec.loader.exec_module(gas)

BOT = {"type": "Bot"}
HUMAN = {"type": "User"}


def _run(i, status="completed", name=gas.CHECK_NAME):
    return {"id": i, "name": name, "status": status, "conclusion": "neutral"}


def test_parse_repo() -> None:
    assert gas.parse_repo("a/b-c.d") == "a/b-c.d"
    for bad in ("", "a", "a/b/c", "a b/c", "--yes/x"):
        with pytest.raises(ValueError):
            gas.parse_repo(bad)


def test_check_run_filtering_and_single_run_check() -> None:
    runs = gas.radius_check_runs({"check_runs": [_run(1), _run(2, name="other")]})
    assert [r["id"] for r in runs] == [1]
    assert gas.check_single_completed_run(runs, "a" * 40).ok
    assert not gas.check_single_completed_run([], "a" * 40).ok
    assert not gas.check_single_completed_run([_run(1), _run(2)], "a" * 40).ok
    assert not gas.check_single_completed_run([_run(1, "in_progress")], "a" * 40).ok


def test_comment_checks_ignore_human_quotes_and_detect_duplicates() -> None:
    mk = lambda i, user, body=gas.COMMENT_MARKER: {"id": i, "user": user, "body": body}  # noqa: E731
    assert gas.check_single_comment([mk(1, BOT), mk(2, HUMAN)]).ok
    assert not gas.check_single_comment([mk(1, BOT), mk(2, BOT)]).ok
    assert not gas.check_single_comment([mk(2, HUMAN)]).ok
    assert gas.check_comment_edited_in_place(1, [mk(1, BOT)]).ok
    assert not gas.check_comment_edited_in_place(1, [mk(3, BOT)]).ok
    assert not gas.check_comment_edited_in_place(None, [mk(1, BOT)]).ok


def test_no_new_activity() -> None:
    a = {"check_run_ids": {1}, "comment_ids": {5}}
    assert gas.check_no_new_activity(a, {"check_run_ids": {1}, "comment_ids": {5}}).ok
    bad = gas.check_no_new_activity(a, {"check_run_ids": {1, 2}, "comment_ids": {5}})
    assert not bad.ok and "[2]" in bad.detail


def test_poll_returns_when_done_or_times_out() -> None:
    ticks = iter(range(100))
    clock = lambda: float(next(ticks))  # noqa: E731
    calls = []
    result, ok = gas.poll(
        lambda: calls.append(1) or len(calls), lambda r: r >= 3, timeout=50, interval=1,
        sleep=lambda s: None, clock=clock,
    )
    assert (result, ok) == (3, True)
    result, ok = gas.poll(lambda: 0, lambda r: False, timeout=3, interval=1, sleep=lambda s: None, clock=clock)
    assert ok is False


def test_render_evidence_marks_failures() -> None:
    good = gas.StepResult("open_pr", "d", checks=[gas.Check(True, "c1", "ok")])
    bad = gas.StepResult("push_commit", "d", checks=[gas.Check(False, "c2", "nope")])
    skip = gas.StepResult("redeliver", "d", skipped="manual")
    text = gas.render_evidence("o/r", "https://x/pull/1", [good, bad, skip], "t")
    assert "Overall: FAIL" in text
    assert "| push_commit | FAIL |" in text and "| redeliver | SKIPPED |" in text
    assert "- [x] c1" in text and "- [ ] c2" in text
    assert "Overall: PASS" in gas.render_evidence("o/r", None, [good, skip], "t")


def test_dry_run_executes_nothing_and_requires_valid_repo(capsys, monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("dry run must not spawn processes")

    monkeypatch.setattr(gas.subprocess, "run", boom)
    assert gas.main(["--repo", "o/r"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "force_push" in out
    assert gas.main(["--repo", "nonsense"]) == 2


class FakeShell:
    """Simulates git/gh plus a perfectly behaving Radius App on the other side."""

    def __init__(self, duplicate_comment: bool = False):
        self.sha = "a" * 40
        self.n = 0
        self.runs: dict[str, list[dict]] = {}
        self.comment_ids: list[int] = []
        self.duplicate_comment = duplicate_comment
        self.log: list[list[str]] = []

    def _publish(self):
        self.runs.setdefault(self.sha, [{"id": len(self.runs) + 100, "name": gas.CHECK_NAME,
                                         "status": "completed", "conclusion": "neutral"}])
        if not self.comment_ids:
            self.comment_ids.append(500)
        elif self.duplicate_comment and len(self.comment_ids) < 2:
            self.comment_ids.append(501)

    def run(self, args, cwd=None, env=None):
        self.log.append(args)
        if args[0] == "git":
            if args[1] == "rev-parse":
                return self.sha + "\n"
            if args[1] == "commit":
                self.n += 1
                self.sha = f"{self.n:040x}"
            if args[1] == "push":
                self._publish()
            return ""
        if args[:3] == ["gh", "pr", "create"]:
            return "https://github.com/o/r/pull/9\n"
        return ""

    def gh_json(self, args):
        path = args[0]
        if path == "repos/o/r":
            return {"default_branch": "main"}
        if "/check-runs" in path:
            sha = path.split("/commits/")[1].split("/")[0]
            return {"check_runs": self.runs.get(sha, [])}
        if path.endswith("/comments?per_page=100"):
            return [{"id": i, "user": BOT, "body": gas.COMMENT_MARKER} for i in self.comment_ids]
        raise AssertionError(path)


def _driver(shell):
    args = argparse.Namespace(timeout=5, poll=0, quiet_seconds=0, app_id=None, app_key_file=None)
    drv = gas.Driver("o/r", shell, args, sleep=lambda s: None)
    drv.workdir = Path(__file__).parent  # never written: FakeShell swallows git; commit() writes a file below
    return drv


def test_full_scenario_sequence_passes_against_well_behaved_fake(tmp_path, monkeypatch) -> None:
    shell = FakeShell()
    drv = _driver(shell)
    monkeypatch.setattr(gas.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    results = gas.run_scenarios(drv, None, cleanup=True)
    by_name = {r.scenario: r for r in results}
    assert [r.scenario for r in results] == list(gas.SCENARIOS)
    for name in ("open_pr", "push_commit", "edit_description", "close_reopen", "force_push"):
        assert by_name[name].status == "PASS", (name, by_name[name])
    assert by_name["redeliver"].status == "SKIPPED"
    assert drv.pr_number == 9
    assert ["gh", "pr", "close", "9", "--repo", "o/r", "--delete-branch"] in shell.log


def test_duplicate_comment_is_detected(tmp_path, monkeypatch) -> None:
    shell = FakeShell(duplicate_comment=True)
    drv = _driver(shell)
    monkeypatch.setattr(gas.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    results = gas.run_scenarios(drv, ["open_pr", "push_commit"], cleanup=False)
    assert any(r.status == "FAIL" for r in results)


def test_later_scenarios_are_skipped_when_pr_creation_fails(tmp_path, monkeypatch) -> None:
    class Broken(FakeShell):
        def run(self, args, cwd=None, env=None):
            if args[:3] == ["gh", "pr", "create"]:
                raise RuntimeError("denied")
            return super().run(args, cwd, env)

    drv = _driver(Broken())
    monkeypatch.setattr(gas.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    results = gas.run_scenarios(drv, None, cleanup=False)
    assert results[0].status == "FAIL"
    assert all(r.status == "SKIPPED" for r in results[1:])
    json.dumps([r.status for r in results])
