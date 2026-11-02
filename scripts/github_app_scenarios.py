"""Drive the F-06 live GitHub App scenarios against a SANDBOX repository (gh CLI).

Dry-run by default: prints the plan and touches nothing. To execute you must pass
``--repo owner/name`` AND ``--yes``. The script creates a throwaway branch and one
pull request in that repository, pushes commits, edits/closes/reopens the PR,
force-pushes, optionally asks GitHub to redeliver a webhook, and after each step
polls the Check Runs and PR comments through ``gh api``, asserting:

  * exactly one completed ``Radius confidence`` Check Run per head SHA,
  * exactly one Radius bot comment on the PR, edited in place (same comment id),
  * description edits / close / reopen do not create new comments or check runs,
  * a redelivered webhook creates no duplicates.

Results are written as markdown to docs/github-app-validation/evidence/.
Authentication is whatever ``gh auth status`` has; no secrets are read or logged
(the optional App key is only used to mint a short-lived JWT for redelivery).

Usage
    python scripts/github_app_scenarios.py --repo me/radius-sandbox                # dry run
    python scripts/github_app_scenarios.py --repo me/radius-sandbox --yes          # execute
    python scripts/github_app_scenarios.py --repo me/radius-sandbox --yes \
        --app-id 123456 --app-key-file ~/radius-github-app/app.pem                 # + redelivery
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "github-app-validation" / "evidence"
CHECK_NAME = "Radius confidence"
COMMENT_MARKER = "<!-- radius-confidence-report -->"
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.][A-Za-z0-9_.-]*$")
SCENARIOS = (
    "open_pr",
    "push_commit",
    "edit_description",
    "close_reopen",
    "force_push",
    "redeliver",
)


# --------------------------------------------------------------------------- pure logic


def parse_repo(value: str) -> str:
    if not REPO_RE.match(value or ""):
        raise ValueError(f"--repo must look like owner/name, got {value!r}")
    return value


def radius_check_runs(payload: dict, name: str = CHECK_NAME) -> list[dict]:
    return [run for run in payload.get("check_runs", []) if run.get("name") == name]


def radius_comments(comments: list[dict], marker: str = COMMENT_MARKER) -> list[dict]:
    """Comments that carry the marker and were written by a bot (the App)."""

    return [
        c
        for c in comments
        if marker in (c.get("body") or "")
        and str((c.get("user") or {}).get("type", "")).lower() == "bot"
    ]


@dataclass
class Check:
    ok: bool
    name: str
    detail: str


def check_single_completed_run(runs: list[dict], sha: str) -> Check:
    name = f"exactly one completed '{CHECK_NAME}' check run on {sha[:7]}"
    if len(runs) != 1:
        return Check(False, name, f"found {len(runs)} (ids {[r.get('id') for r in runs]})")
    run = runs[0]
    if run.get("status") != "completed":
        return Check(False, name, f"status is {run.get('status')!r}")
    return Check(True, name, f"id {run.get('id')} conclusion {run.get('conclusion')}")


def check_single_comment(comments: list[dict]) -> Check:
    name = "exactly one Radius bot comment on the PR"
    found = radius_comments(comments)
    if len(found) != 1:
        return Check(False, name, f"found {len(found)} (ids {[c.get('id') for c in found]})")
    return Check(True, name, f"id {found[0].get('id')}")


def check_comment_edited_in_place(previous_id: int | None, comments: list[dict]) -> Check:
    name = "Radius comment is edited in place (same comment id)"
    found = radius_comments(comments)
    if previous_id is None or len(found) != 1:
        return Check(False, name, f"previous id {previous_id}, now {[c.get('id') for c in found]}")
    same = found[0].get("id") == previous_id
    return Check(same, name, f"id {found[0].get('id')} (previous {previous_id})")


def check_no_new_activity(before: dict, after: dict) -> Check:
    """``before``/``after`` are snapshots: {'check_run_ids': set, 'comment_ids': set}."""

    name = "no new check runs or comments were created"
    new_checks = set(after["check_run_ids"]) - set(before["check_run_ids"])
    new_comments = set(after["comment_ids"]) - set(before["comment_ids"])
    if new_checks or new_comments:
        return Check(False, name, f"new check runs {sorted(new_checks)}, new comments {sorted(new_comments)}")
    return Check(True, name, "unchanged")


def poll(
    fetch: Callable[[], object],
    done: Callable[[object], bool],
    *,
    timeout: float,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
):
    """Call ``fetch`` until ``done(result)`` or timeout; return (result, satisfied)."""

    deadline = clock() + timeout
    while True:
        result = fetch()
        if done(result):
            return result, True
        if clock() >= deadline:
            return result, False
        sleep(interval)


@dataclass
class StepResult:
    scenario: str
    description: str
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    skipped: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIPPED"
        if self.error or any(not c.ok for c in self.checks):
            return "FAIL"
        return "PASS"


def render_evidence(repo: str, pr_url: str | None, results: list[StepResult], started: str) -> str:
    lines = [
        f"# F-06 live scenario evidence: {repo}",
        "",
        f"- Run started (UTC): {started}",
        f"- Pull request: {pr_url or 'n/a'}",
        f"- Overall: {'PASS' if all(r.status in ('PASS', 'SKIPPED') for r in results) else 'FAIL'}",
        "",
        "| Scenario | Result |",
        "| --- | --- |",
    ]
    lines += [f"| {r.scenario} | {r.status} |" for r in results]
    for r in results:
        lines += ["", f"## {r.scenario}: {r.status}", "", r.description, ""]
        if r.skipped:
            lines.append(f"Skipped: {r.skipped}")
        if r.error:
            lines.append(f"Error: `{r.error}`")
        lines += [f"- [{'x' if c.ok else ' '}] {c.name} ({c.detail})" for c in r.checks]
        lines += [f"- note: {n}" for n in r.notes]
    lines.append("")
    return "\n".join(lines)


def plan_lines(repo: str, base_branch: str | None = None) -> list[str]:
    base = base_branch or "<default branch>"
    return [
        f"clone {repo} into a temp directory (gh repo clone)",
        f"[open_pr] create branch radius-f06-<ts> from {base}, commit f06_sandbox/greet.py, push, "
        "gh pr create; poll for 1 completed check run + 1 bot comment",
        "[push_commit] commit + push a change; poll for a completed check run on the NEW sha; "
        "assert the comment was edited in place",
        "[edit_description] gh pr edit --body/--title; wait; assert no new check run/comment",
        "[close_reopen] gh pr close, wait, gh pr reopen, wait; assert no duplicates",
        "[force_push] git commit --amend + push --force-with-lease; poll check run on the new sha; "
        "assert a single comment",
        "[redeliver] (needs --app-id and --app-key-file) redeliver the latest pull_request delivery "
        "via the App deliveries API; assert no duplicates",
        "write markdown evidence to docs/github-app-validation/evidence/",
    ]


# --------------------------------------------------------------------------- side effects


class Shell:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self._runner = runner

    def run(self, args: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
        proc = self._runner(args, cwd=cwd, env=env, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()[:500]}")
        return proc.stdout

    def gh_json(self, args: list[str]):
        out = self.run(["gh", "api", *args])
        return json.loads(out) if out.strip() else None


class Driver:
    def __init__(self, repo: str, sh: Shell, args: argparse.Namespace, sleep=time.sleep):
        self.repo, self.sh, self.args, self.sleep = repo, sh, args, sleep
        self.workdir: Path | None = None
        self.branch = f"radius-f06-{int(time.time())}"
        self.pr_number: int | None = None
        self.pr_url: str | None = None
        self.base: str = "main"
        self.comment_id: int | None = None
        self.head_sha = ""

    # git / gh helpers
    def git(self, *a: str) -> str:
        return self.sh.run(["git", *a], cwd=self.workdir)

    def checks_for(self, sha: str) -> list[dict]:
        payload = self.sh.gh_json([f"repos/{self.repo}/commits/{sha}/check-runs?per_page=100"]) or {}
        return radius_check_runs(payload)

    def comments(self) -> list[dict]:
        return self.sh.gh_json([f"repos/{self.repo}/issues/{self.pr_number}/comments?per_page=100"]) or []

    def snapshot(self) -> dict:
        return {
            "check_run_ids": {r["id"] for r in self.checks_for(self.head_sha)},
            "comment_ids": {c["id"] for c in self.comments()},
        }

    def wait_completed_check(self, sha: str) -> list[dict]:
        runs, _ = poll(
            lambda: self.checks_for(sha),
            lambda r: len(r) >= 1 and all(x.get("status") == "completed" for x in r),
            timeout=self.args.timeout,
            interval=self.args.poll,
            sleep=self.sleep,
        )
        return runs

    def wait_comment(self) -> list[dict]:
        comments, _ = poll(
            self.comments,
            lambda c: len(radius_comments(c)) >= 1,
            timeout=self.args.timeout,
            interval=self.args.poll,
            sleep=self.sleep,
        )
        return comments

    def quiet(self) -> None:
        self.sleep(self.args.quiet_seconds)

    def commit(self, text: str, amend: bool = False) -> str:
        path = self.workdir / "f06_sandbox" / "greet.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f'def greet(name):\n    return "hello " + name  # {text}\n', encoding="utf-8")
        self.git("add", "f06_sandbox")
        if amend:
            self.git("commit", "--amend", "-m", f"f06: {text}")
        else:
            self.git("commit", "-m", f"f06: {text}")
        return self.git("rev-parse", "HEAD").strip()

    def expect_completed(self, res: StepResult) -> None:
        runs = self.wait_completed_check(self.head_sha)
        res.checks.append(check_single_completed_run(runs, self.head_sha))
        comments = self.wait_comment()
        res.checks.append(check_single_comment(comments))

    # scenarios
    def setup(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="radius-f06-"))
        self.sh.run(["gh", "repo", "clone", self.repo, str(self.workdir)])
        info = self.sh.gh_json([f"repos/{self.repo}"])
        self.base = info["default_branch"]
        self.git("checkout", "-b", self.branch)

    def open_pr(self) -> StepResult:
        res = StepResult("open_pr", "Open a PR with a new Python file; expect one check run and one comment.")
        self.head_sha = self.commit("initial")
        self.git("push", "-u", "origin", self.branch)
        url = self.sh.run(
            ["gh", "pr", "create", "--repo", self.repo, "--head", self.branch, "--base", self.base,
             "--title", f"F-06 validation {self.branch}", "--body", "F-06 live validation. Safe to close."]
        ).strip().splitlines()[-1]
        self.pr_url, self.pr_number = url, int(url.rstrip("/").split("/")[-1])
        self.expect_completed(res)
        found = radius_comments(self.comments())
        self.comment_id = found[0]["id"] if found else None
        return res

    def push_commit(self) -> StepResult:
        res = StepResult("push_commit", "Push a second commit; expect a new completed check run, same comment.")
        previous = self.head_sha
        self.head_sha = self.commit("second commit")
        self.git("push", "origin", self.branch)
        self.expect_completed(res)
        res.checks.append(check_comment_edited_in_place(self.comment_id, self.comments()))
        res.notes.append(f"previous head {previous[:7]} keeps its own check run; new head {self.head_sha[:7]}.")
        return res

    def edit_description(self) -> StepResult:
        res = StepResult("edit_description", "Edit title/body; expect NO new analysis, check run or comment.")
        before = self.snapshot()
        self.sh.run(["gh", "pr", "edit", str(self.pr_number), "--repo", self.repo,
                     "--title", f"F-06 validation {self.branch} (edited)", "--body", "Edited description."])
        self.quiet()
        res.checks.append(check_no_new_activity(before, self.snapshot()))
        return res

    def close_reopen(self) -> StepResult:
        res = StepResult("close_reopen", "Close then reopen; expect no duplicate comment or check run.")
        before = self.snapshot()
        self.sh.run(["gh", "pr", "close", str(self.pr_number), "--repo", self.repo])
        self.quiet()
        self.sh.run(["gh", "pr", "reopen", str(self.pr_number), "--repo", self.repo])
        self.quiet()
        runs = self.wait_completed_check(self.head_sha)
        res.checks.append(check_single_completed_run(runs, self.head_sha))
        res.checks.append(check_single_comment(self.comments()))
        res.checks.append(check_no_new_activity(before, self.snapshot()))
        return res

    def force_push(self) -> StepResult:
        res = StepResult("force_push", "Amend and force-push; expect a completed check run on the new SHA.")
        previous = self.head_sha
        self.head_sha = self.commit("amended", amend=True)
        self.git("push", "--force-with-lease", "origin", self.branch)
        self.expect_completed(res)
        res.checks.append(check_comment_edited_in_place(self.comment_id, self.comments()))
        res.notes.append(f"orphaned head {previous[:7]} may keep a stale check run; this is expected on GitHub.")
        return res

    def redeliver(self) -> StepResult:
        res = StepResult("redeliver", "Redeliver the latest pull_request webhook; expect no duplicates.")
        if not (self.args.app_id and self.args.app_key_file):
            res.skipped = (
                "needs --app-id and --app-key-file. Manual alternative: GitHub App settings > Advanced > "
                "Recent Deliveries > Redeliver the latest pull_request delivery, then re-run the "
                "'no duplicates' queries in RUNBOOK section 6."
            )
            return res
        token = mint_app_jwt(self.args.app_id, Path(self.args.app_key_file).expanduser())
        env = {**os.environ, "GH_TOKEN": token}
        out = self.sh.run(["gh", "api", "/app/hook/deliveries?per_page=50"], env=env)
        deliveries = [d for d in json.loads(out) if d.get("event") == "pull_request"]
        if not deliveries:
            res.error = "no pull_request deliveries found"
            return res
        target = deliveries[0]
        before = self.snapshot()
        self.sh.run(["gh", "api", "-X", "POST", f"/app/hook/deliveries/{target['id']}/attempts"], env=env)
        self.sleep(self.args.quiet_seconds)
        after_deliveries = json.loads(self.sh.run(["gh", "api", "/app/hook/deliveries?per_page=50"], env=env))
        attempts = [d for d in after_deliveries if d.get("guid") == target.get("guid")]
        res.checks.append(Check(len(attempts) >= 2, "redelivery attempt recorded", f"{len(attempts)} attempts"))
        latest = max(attempts, key=lambda d: d.get("delivered_at") or "")
        res.checks.append(
            Check(latest.get("status_code") == 202, "redelivery answered 202", f"status {latest.get('status_code')}")
        )
        res.checks.append(check_no_new_activity(before, self.snapshot()))
        res.checks.append(check_single_comment(self.comments()))
        return res

    def cleanup(self) -> None:
        if self.pr_number:
            self.sh.run(["gh", "pr", "close", str(self.pr_number), "--repo", self.repo, "--delete-branch"])


def mint_app_jwt(app_id: str, key_file: Path) -> str:
    """Short-lived App JWT (needs PyJWT, which the Radius env already has)."""

    import jwt  # local import: only needed for redelivery

    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, key_file.read_text(), "RS256")


def run_scenarios(driver: Driver, only: list[str] | None, cleanup: bool) -> list[StepResult]:
    results: list[StepResult] = []
    driver.setup()
    try:
        for name in SCENARIOS:
            if only and name not in only:
                continue
            if name != "open_pr" and driver.pr_number is None:
                results.append(StepResult(name, "", skipped="open_pr did not produce a PR"))
                continue
            try:
                results.append(getattr(driver, name)())
            except Exception as exc:  # record, keep going with what is possible
                results.append(StepResult(name, "", error=str(exc)[:500]))
    finally:
        if cleanup:
            try:
                driver.cleanup()
            except Exception as exc:
                print(f"cleanup failed: {exc}", file=sys.stderr)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--repo", required=True, help="Sandbox repository, owner/name.")
    p.add_argument("--yes", action="store_true", help="Actually perform the scenarios (default: dry run).")
    p.add_argument("--only", nargs="*", choices=SCENARIOS, help="Run only these scenarios.")
    p.add_argument("--timeout", type=float, default=300, help="Seconds to wait for each check run.")
    p.add_argument("--poll", type=float, default=10)
    p.add_argument("--quiet-seconds", type=float, default=30, help="Wait used for 'nothing should happen' steps.")
    p.add_argument("--app-id")
    p.add_argument("--app-key-file")
    p.add_argument("--cleanup", action="store_true", help="Close the PR and delete the branch at the end.")
    p.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    args = p.parse_args(argv)
    try:
        repo = parse_repo(args.repo)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.yes:
        print(f"DRY RUN against {repo} (nothing will be changed; add --yes to execute):")
        for line in plan_lines(repo):
            print(f"  - {line}")
        return 0
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    driver = Driver(repo, Shell(), args)
    results = run_scenarios(driver, args.only, args.cleanup)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    out = args.evidence_dir / f"scenarios-{started.replace(':', '')}.md"
    out.write_text(render_evidence(repo, driver.pr_url, results, started), encoding="utf-8")
    print(f"evidence written to {out}")
    for r in results:
        print(f"{r.scenario}: {r.status}")
    return 0 if all(r.status in ("PASS", "SKIPPED") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
