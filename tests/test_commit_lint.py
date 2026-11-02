"""Unit tests for scripts/ci/commit_lint.py (PRD-06)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "commit_lint.py"
_spec = importlib.util.spec_from_file_location("commit_lint", _PATH)
assert _spec and _spec.loader
commit_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(commit_lint)


@pytest.mark.parametrize(
    "subject",
    [
        "feat: add thing",
        "fix(api): reject empty key",
        "docs(readme)!: rewrite quickstart",
        "chore(deps-dev): bump ruff",
        "feat(intent/api): add route",
        "feat(github,worker,api): restrict links",
        "fix(api, worker): handle empty body",
        "revert: undo bad change",
        "ci: pin actions (PRD-06)",
    ],
)
def test_valid_subjects(subject):
    assert commit_lint.check_subject(subject) == []


@pytest.mark.parametrize(
    "subject",
    [
        "",
        "Add thing",
        "feat add thing",
        "feat:no space",
        "feat(): empty scope",
        "feat(api,): trailing comma scope",
        "Feat: capitalised type",
        "feat: ",
        "feat(api) : space before colon",
    ],
)
def test_malformed_subjects(subject):
    assert commit_lint.check_subject(subject)


def test_unknown_type_is_reported():
    problems = commit_lint.check_subject("wip: stuff")
    assert any("unknown type" in p for p in problems)


def test_header_length_limit():
    assert any("limit" in p for p in commit_lint.check_subject("fix: " + "x" * 100))
    assert commit_lint.check_subject("fix: " + "x" * 95) == []


def test_generated_subjects_only_allowed_for_commits():
    merge = "Merge branch 'develop'"
    assert commit_lint.check_subject(merge, allow_generated=True) == []
    assert commit_lint.check_subject('Revert "feat: x"', allow_generated=True) == []
    assert commit_lint.check_subject(merge)


def test_exemptions():
    assert commit_lint.is_exempt("dependabot[bot]", "dependabot/x", "develop")
    assert commit_lint.is_exempt("someapp[bot]", "x", "develop")
    assert commit_lint.is_exempt("alice", "develop", "dev")
    assert commit_lint.is_exempt("alice", "dev", "main")
    assert commit_lint.is_exempt("alice", "feature/x", "develop") is None
    assert commit_lint.is_exempt("alice", "develop", "feature/y") is None


def test_needs_fragment():
    assert commit_lint.needs_fragment("feat: x")
    assert commit_lint.needs_fragment("fix(api): x")
    assert commit_lint.needs_fragment("perf: x")
    assert commit_lint.needs_fragment("refactor!: x")
    assert not commit_lint.needs_fragment("docs: x")
    assert not commit_lint.needs_fragment("chore: x")
    assert not commit_lint.needs_fragment("garbage")


def test_fragment_rules():
    check = commit_lint.check_fragment
    assert check("feat: x", ["a.py"], [])
    assert check("feat: x", ["changelog.d/README.md"], [])
    assert check("feat: x", ["a.py"], ["no-changelog"]) == []
    assert check("feat: x", ["changelog.d/12.added.md"], []) == []
    assert check("docs: x", ["a.md"], []) == []
    assert check("fix: x", ["changelog.d/9.fixed.md", "a.py"], []) == []


def test_lint_combines_title_commits_and_fragment():
    ok = commit_lint.lint(
        "fix: a", ["fix: a", "Merge branch 'x'"], ["changelog.d/1.fixed.md"], []
    )
    assert ok == []
    bad = commit_lint.lint("Fix a", ["oops"], ["a.py"], [])
    assert any(p.startswith("PR title") for p in bad)
    assert any(p.startswith("commit") for p in bad)
    assert commit_lint.lint("fix: a", [], [], [], require_fragment=False) == []


def test_main_skips_bots_and_promotions(capsys):
    assert commit_lint.main(["--author", "dependabot[bot]", "--title", "Bump x"]) == 0
    assert "skipped" in capsys.readouterr().out
    args = ["--head-ref", "develop", "--base-ref", "dev", "--title", "Promote"]
    assert commit_lint.main(args) == 0


def test_main_title_results(capsys, monkeypatch):
    for name in ("PR_TITLE", "PR_AUTHOR", "PR_LABELS"):
        monkeypatch.delenv(name, raising=False)
    assert commit_lint.main(["--title", "nope", "--no-fragment-check"]) == 1
    assert "FAILED" in capsys.readouterr().err
    assert commit_lint.main(["--title", "docs: fine"]) == 0
    assert commit_lint.main([]) == 2


def test_main_reads_git_range(tmp_path, monkeypatch):
    def git(*a):
        return subprocess.run(
            ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", *a],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1")
    git("add", ".")
    git("commit", "-q", "-m", "chore: base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "a.txt").write_text("2")
    git("commit", "-qam", "bad subject")
    bad_head = git("rev-parse", "HEAD")
    git("reset", "-q", "--hard", base)
    (tmp_path / "a.txt").write_text("3")
    git("commit", "-qam", "docs: good subject")
    good_head = git("rev-parse", "HEAD")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PR_TITLE", raising=False)
    common = ["--title", "docs: ok", "--base-sha", base]
    assert commit_lint.main([*common, "--head-sha", bad_head]) == 1
    assert commit_lint.main([*common, "--head-sha", good_head]) == 0
