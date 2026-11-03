#!/usr/bin/env python
"""Build the Radius live-demo repository: one ``main`` and three scripted PR branches.

    python scripts/demo_repo.py --out ./demo-out
    python scripts/demo_repo.py --out ./demo-out --repo OWNER/REPO     # also print push commands

The layout is a small pricing-service-like Python package (``src/pricing.py``,
``src/emails.py``, ``src/stock.py`` with tests) and ``.radius/intent.yml`` on ``main``. It is built
from the F-14 intent fixtures (``benchmarks/fixtures/intent``), so the three scenarios are the
same code the Verdict v2 acceptance tests and ``scripts/smoke_e2e.py`` already exercise:

====  =====================  ==========================================  ==========================
PR    branch                 change                                      fixture / expected verdict
====  =====================  ==========================================  ==========================
A     demo/a-strong-tests    ``apply_discount`` + exact-value tests      01 / verified
B     demo/b-weak-tests      ``normalize_email`` + truthiness tests      02 / insufficient evidence
C     demo/c-tampered-tests  validation removed, tests weakened/skipped  04 / failed (tamper)
====  =====================  ==========================================  ==========================

The output is deterministic: fixed author, committer and dates, so the same commit SHAs come out
on every run. Nothing here talks to GitHub and no token is ever read, taken or stored. The script
only creates local repositories and PRINTS the git commands for you to run yourself:

* ``DIR/work`` is the working repository (``main``, three ``demo/*-base``, three PR branches).
* ``DIR/radius-demo.git`` is a bare repository with the same branches (a local "remote" you can
  clone from or push from).
* ``--repo OWNER/REPO`` (or ``--remote-url URL``) only changes the commands printed at the end.

Standard library only; needs ``git`` on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTENT_FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
DEFAULT_BRANCH = "main"
AUTHOR_NAME = "Radius Demo"
AUTHOR_EMAIL = "demo@example.invalid"
BASE_DATE = "2026-01-05T10:00:00+0000"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Scenario:
    key: str  # A, B, C
    fixture: str
    branch: str
    base_branch: str
    title: str
    body: str
    commit_message: str
    short: str
    expected_verdict: str
    expected_rule: str
    expected_check: str
    what_to_point_at: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="A",
        fixture="01_correct_strong_tests",
        branch="demo/a-strong-tests",
        base_branch="demo/a-base",
        title="Add apply_discount to pricing",
        body=(
            "Adds `apply_discount(price, percent)` to `pricing.py`: the price reduced by "
            "percent, rounded to 2 decimals; a percent outside 0..100 raises ValueError.\n"
        ),
        commit_message="feat(pricing): add apply_discount",
        short="strong tests",
        expected_verdict="verified",
        expected_rule="R4",
        expected_check="neutral (advisory; the alpha never blocks a merge by itself)",
        what_to_point_at=(
            "Both criteria proven; the evidence names exact-value and boundary assertions."
        ),
    ),
    Scenario(
        key="B",
        fixture="02_correct_weak_tests",
        branch="demo/b-weak-tests",
        base_branch="demo/b-base",
        title="Add normalize_email",
        body=(
            "Adds `normalize_email(addr)` to `emails.py`: trims whitespace, lowercases, and "
            "raises ValueError for an address without an `@`.\n"
        ),
        commit_message="feat(emails): add normalize_email",
        short="weak tests",
        expected_verdict="insufficient_evidence",
        expected_rule="R2b",
        expected_check="neutral",
        what_to_point_at=(
            "The code is correct and CI is green, yet Radius will not call it supported: the "
            "tests only assert truthiness, and the ValueError criterion has no test at all."
        ),
    ),
    Scenario(
        key="C",
        fixture="04_test_tampering",
        branch="demo/c-tampered-tests",
        base_branch="demo/c-base",
        title="Speed up reserve",
        body=(
            "`reserve` does redundant validation on a hot path. Drop it so the function is a "
            "single subtraction. No behaviour change is intended for valid input.\n"
        ),
        commit_message="perf(stock): speed up reserve",
        short="tampered tests",
        expected_verdict="failed",
        expected_rule="R1c",
        expected_check="failure (the only outcome where the Check Run blocks)",
        what_to_point_at=(
            "CI is green, but the PR removed validation, deleted one test, weakened another "
            "and skipped a third. The tamper findings are listed with file and line."
        ),
    ),
)

README = """\
# radius-demo

A tiny pricing-service-like package used to demonstrate Radius on real pull requests.

* `src/pricing.py`, `src/emails.py`, `src/stock.py`: small helpers.
* `tests/`: their tests (`python -m pytest`).
* `.radius/intent.yml`: what the code is supposed to do, read by Radius from the base branch.

`demo/a-base`, `demo/b-base` and `demo/c-base` are `main` with an intent file scoped to one
module (Radius judges a PR against every criterion of its base spec). Open each pull request
against its own base branch. The pull-request branches `demo/a-strong-tests`, `demo/b-weak-tests` and
`demo/c-tampered-tests` each change one module (see the base branches below).
"""

GITIGNORE = "__pycache__/\n*.pyc\n.pytest_cache/\n"


def _git_env() -> dict[str, str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    for name in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        env.pop(name, None)
    return env


def git(args: list[str], cwd: Path, *, date: str | None = None) -> str:
    env = _git_env()
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _load_expected(fixture: str) -> dict:
    return json.loads((INTENT_FIXTURES / fixture / "expected.json").read_text(encoding="utf-8"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def combined_intent_spec(scenarios: tuple[Scenario, ...] = SCENARIOS) -> str:
    """``.radius/intent.yml`` with the scenarios' criteria and the gold links as hints.

    ``main`` carries all of them. Each PR's base branch carries only its own, because Radius
    judges a PR against every criterion of the base spec: with the other modules' criteria
    present, PR A could never be ``verified`` (observed with ``scripts/demo_verify.py``).
    Criterion ids are prefixed with the module name so they stay unique.
    """

    lines = ["version: 1", "criteria:"]
    for scenario in scenarios:
        expected = _load_expected(scenario.fixture)
        links = {link["criterion"]: link for link in expected["links"]}
        module = links[expected["criteria"][0]["id"]]["symbol"].split("::", 1)[0]
        prefix = Path(module).stem
        for criterion in expected["criteria"]:
            link = links[criterion["id"]]
            lines += [
                f"  - id: {prefix}-{criterion['id']}",
                f'    text: "{criterion["text"]}"',
                "    paths:",
                f'      - "{link["symbol"].split("::", 1)[0]}"',
                "    tests:",
                *[f'      - "{t}"' for t in link["tests"]],
            ]
    return "\n".join(lines) + "\n"


def _copy_tree(source: Path, target: Path) -> list[str]:
    """Copy ``src/`` and ``tests/`` of a fixture side into ``target``; return the files."""

    copied = []
    for sub in ("src", "tests"):
        base = source / sub
        if not base.is_dir():
            continue
        for item in sorted(base.rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts:
                dest = target / item.relative_to(source)
                _write(dest, _read(item))
                copied.append(dest.relative_to(target).as_posix())
    return copied


def build_work_repo(work: Path) -> dict[str, str]:
    """Create ``work`` with ``main`` and one branch per scenario; return branch -> head SHA."""

    if work.exists():
        raise SystemExit(f"{work} already exists; choose an empty --out directory.")
    work.mkdir(parents=True)
    git(["init", "-q", "-b", DEFAULT_BRANCH], work)

    # main: the union of every scenario's base side.
    for scenario in SCENARIOS:
        _copy_tree(INTENT_FIXTURES / scenario.fixture / "base", work)
    _write(work / "pytest.ini", _read(INTENT_FIXTURES / SCENARIOS[0].fixture / "base" / "pytest.ini"))
    _write(work / "README.md", README)
    _write(work / ".gitignore", GITIGNORE)
    _write(work / ".radius" / "intent.yml", combined_intent_spec())
    git(["add", "-A"], work)
    git(["commit", "-q", "-m", "chore: initial demo service"], work, date=BASE_DATE)
    shas = {DEFAULT_BRANCH: git(["rev-parse", "HEAD"], work)}

    for index, scenario in enumerate(SCENARIOS, start=1):
        git(["checkout", "-q", "-b", scenario.base_branch, DEFAULT_BRANCH], work)
        _write(work / ".radius" / "intent.yml", combined_intent_spec((scenario,)))
        git(["add", "-A"], work)
        git(["commit", "-q", "-m", f"chore: scope intent to PR {scenario.key}"], work,
            date=BASE_DATE.replace("10:00:00", f"09:{index:02d}:00"))
        shas[scenario.base_branch] = git(["rev-parse", "HEAD"], work)
        git(["checkout", "-q", "-b", scenario.branch], work)
        _copy_tree(INTENT_FIXTURES / scenario.fixture / "head", work)
        git(["add", "-A"], work)
        date = BASE_DATE.replace("10:00:00", f"10:{index:02d}:00")
        git(["commit", "-q", "-m", scenario.commit_message], work, date=date)
        shas[scenario.branch] = git(["rev-parse", "HEAD"], work)
        git(["checkout", "-q", DEFAULT_BRANCH], work)
    return shas


def build_bare(work: Path, bare: Path) -> None:
    if bare.exists():
        raise SystemExit(f"{bare} already exists; choose an empty --out directory.")
    subprocess.run(  # noqa: S603 - fixed argv
        ["git", "clone", "-q", "--bare", str(work), str(bare)],
        check=True, capture_output=True, env=_git_env(),
    )
    # a bare clone has every branch of work as a branch; keep main as HEAD.
    git(["symbolic-ref", "HEAD", f"refs/heads/{DEFAULT_BRANCH}"], bare)


def push_commands(remote: str) -> list[str]:
    branches = " ".join(
        [DEFAULT_BRANCH, *(s.base_branch for s in SCENARIOS), *(s.branch for s in SCENARIOS)]
    )
    return [
        "cd <OUT>/work",
        f"git remote add origin {remote}",
        f"git push -u origin {branches}",
    ]


def remote_url(repo: str | None, url: str | None) -> str:
    if url:
        return url
    if repo:
        if not _REPO.match(repo):
            raise SystemExit("--repo must look like OWNER/REPO.")
        return f"https://github.com/{repo}.git"
    return "https://github.com/OWNER/REPO.git"


def expected_markdown() -> str:
    """The text of ``demo/EXPECTED.md`` (kept in git; ``--check-expected`` verifies it)."""

    lines = [
        "# Demo scenarios and expected outcomes",
        "",
        "Generated by `python scripts/demo_repo.py --print-expected`; do not edit by hand. The",
        "three scenarios are the F-14 intent fixtures 01, 02 and 04. The verdicts below are the",
        "ones `scripts/smoke_e2e.py` asserts for those fixtures (fake GitHub, real services); the",
        "demo repository itself was validated with `scripts/demo_verify.py`, see",
        "`docs/DEMO_RUNBOOK.md` for what was and was not observed.",
        "",
        "| PR | Branch (base) | Change | Before CI results | After CI results (uploaded) | Deciding rule | Check Run conclusion |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    before = {"A": "insufficient evidence", "B": "insufficient evidence", "C": "failed"}
    for s in SCENARIOS:
        lines.append(
            f"| {s.key} ({s.short}) | `{s.branch}` (into `{s.base_branch}`) | {s.title} | {before[s.key]} | "
            f"**{s.expected_verdict.replace('_', ' ')}** | {s.expected_rule} | {s.expected_check} |"
        )
    lines += ["", "## What to point at", ""]
    for s in SCENARIOS:
        lines.append(f"* **PR {s.key} ({s.short}):** {s.what_to_point_at}")
    lines += [
        "",
        "## Notes",
        "",
        "* \"Before CI results\" is the first comment Radius posts right after `analyze`. For A and B it",
        "  is deliberately unimpressive (\"insufficient evidence\"): Radius has no test results yet.",
        "  The verdict becomes meaningful after `scripts/radius_ci.py run`.",
        "* PR C already fails before CI results because tamper detection is static (R1c).",
        "* The Check Run is advisory (`neutral`) unless a decisive rule fails the PR (`failure`).",
        "* Verdict v2 is alpha; the PR comment says so. Do not present it as a merge decision.",
        "",
    ]
    return "\n".join(lines)


def pr_bodies_markdown() -> str:
    out = ["# Pull request titles and bodies", ""]
    for s in SCENARIOS:
        out += [f"## PR {s.key}: `{s.branch}` into `{s.base_branch}`", "", f"Title: {s.title}", "",
                s.body, ""]
    return "\n".join(out)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", help="Empty directory to create (will contain work/ and radius-demo.git/)")
    parser.add_argument("--repo", help="OWNER/REPO of an empty repository YOU own (only used to print commands)")
    parser.add_argument("--remote-url", help="Full remote URL to print in the push commands")
    parser.add_argument("--print-expected", action="store_true",
                        help="Print demo/EXPECTED.md and exit")
    parser.add_argument("--check-expected", action="store_true",
                        help="Exit 1 if demo/EXPECTED.md differs from the generated text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.print_expected:
        sys.stdout.write(expected_markdown())
        return 0
    if args.check_expected:
        current = (ROOT / "demo" / "EXPECTED.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != expected_markdown():
            print("demo/EXPECTED.md is stale; regenerate with --print-expected", file=sys.stderr)
            return 1
        return 0
    if not args.out:
        print("--out DIR is required", file=sys.stderr)
        return 2
    if not shutil.which("git"):
        print("git is required on PATH", file=sys.stderr)
        return 2
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work, bare = out / "work", out / "radius-demo.git"
    shas = build_work_repo(work)
    build_bare(work, bare)
    _write(out / "PR_BODIES.md", pr_bodies_markdown())

    print(f"Built {work} ({len(shas)} branches)")
    print(f"Bare copy: {bare}")
    for name, sha in shas.items():
        print(f"  {name:<24}{sha}")
    url = remote_url(args.repo, args.remote_url)
    print("\nPush to a repository you own (nothing is pushed by this script):\n")
    for line in push_commands(url):
        print("  " + line.replace("<OUT>", str(out)))
    print("\nThen open one pull request per scenario branch against ITS base branch (titles and bodies in "
          f"{out / 'PR_BODIES.md'}).")
    print("Do this on an empty, throw-away repository, with the Radius GitHub App installed on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
