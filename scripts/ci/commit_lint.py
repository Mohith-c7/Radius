"""Conventional Commits check for pull requests (PRD-06).

Dependency-free (standard library only). Lints the pull-request title and the
subjects of the commits in the pull request, and, for user-visible change types,
checks that a changelog fragment exists unless the `no-changelog` label is set.

Invoked by `.github/workflows/commit-lint.yml`; all inputs arrive as environment
variables so untrusted text (the title) is never interpolated into a shell line.
Run `python scripts/ci/commit_lint.py --help` for local use.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence

TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
# Types that change what a user or operator sees; they need a changelog fragment.
FRAGMENT_TYPES = frozenset({"feat", "fix", "perf"})
MAX_HEADER_LENGTH = 100
NO_CHANGELOG_LABEL = "no-changelog"
FRAGMENT_DIR = "changelog.d/"
# Owner-driven branch promotions (develop -> dev -> main) are exempt.
PROMOTION_HEADS = frozenset({"develop", "dev"})
PROMOTION_BASES = frozenset({"dev", "main"})

_HEADER = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[A-Za-z0-9._/-]+(?:, ?[A-Za-z0-9._/-]+)*)\))?"
    r"(?P<breaking>!)?"
    r": (?P<description>\S.*)$"
)
# Subjects git or GitHub generate; not written by the author.
_GENERATED = re.compile(r'^(Merge |Revert ")')


def parse_header(subject: str) -> re.Match[str] | None:
    return _HEADER.match(subject)


def check_subject(subject: str, *, allow_generated: bool = False) -> list[str]:
    """Return problems with one title or commit subject (empty list means OK)."""
    if allow_generated and _GENERATED.match(subject):
        return []
    match = parse_header(subject)
    if match is None:
        return [
            f"not a Conventional Commit: {subject!r}. Expected "
            "'type(scope)!: description', for example 'fix(api): reject empty key'."
        ]
    problems: list[str] = []
    if match["type"] not in TYPES:
        problems.append(
            f"unknown type {match['type']!r} in {subject!r}; allowed: {', '.join(TYPES)}"
        )
    if len(subject) > MAX_HEADER_LENGTH:
        problems.append(
            f"header is {len(subject)} characters, limit is {MAX_HEADER_LENGTH}: {subject!r}"
        )
    return problems


def is_exempt(author: str, head_ref: str, base_ref: str) -> str | None:
    """Return the reason a pull request is exempt, or None."""
    if author.endswith("[bot]"):
        return f"opened by bot {author}"
    if head_ref in PROMOTION_HEADS and base_ref in PROMOTION_BASES:
        return f"branch promotion {head_ref} -> {base_ref}"
    return None


def needs_fragment(title: str) -> bool:
    match = parse_header(title)
    if match is None:
        return False
    return match["type"] in FRAGMENT_TYPES or bool(match["breaking"])


def check_fragment(
    title: str, changed_files: Iterable[str], labels: Iterable[str]
) -> list[str]:
    if not needs_fragment(title) or NO_CHANGELOG_LABEL in set(labels):
        return []
    for path in changed_files:
        if (
            path.startswith(FRAGMENT_DIR)
            and path.endswith(".md")
            and path != f"{FRAGMENT_DIR}README.md"
        ):
            return []
    return [
        f"this change type needs a changelog fragment in {FRAGMENT_DIR} "
        f"(see {FRAGMENT_DIR}README.md) or the '{NO_CHANGELOG_LABEL}' label"
    ]


def lint(
    title: str,
    commit_subjects: Sequence[str],
    changed_files: Sequence[str],
    labels: Sequence[str],
    *,
    require_fragment: bool = True,
) -> list[str]:
    problems = [f"PR title: {p}" for p in check_subject(title)]
    for subject in commit_subjects:
        problems.extend(
            f"commit: {p}" for p in check_subject(subject, allow_generated=True)
        )
    if require_fragment:
        problems.extend(
            f"changelog: {p}" for p in check_fragment(title, changed_files, labels)
        )
    return problems


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    env = os.environ.get
    parser.add_argument("--title", default=env("PR_TITLE", ""))
    parser.add_argument("--author", default=env("PR_AUTHOR", ""))
    parser.add_argument("--base-ref", default=env("PR_BASE_REF", ""))
    parser.add_argument("--head-ref", default=env("PR_HEAD_REF", ""))
    parser.add_argument("--base-sha", default=env("PR_BASE_SHA", ""))
    parser.add_argument("--head-sha", default=env("PR_HEAD_SHA", ""))
    parser.add_argument(
        "--labels", default=env("PR_LABELS", ""), help="comma-separated label names"
    )
    parser.add_argument("--no-fragment-check", action="store_true")
    args = parser.parse_args(argv)

    reason = is_exempt(args.author, args.head_ref, args.base_ref)
    if reason:
        print(f"commit-lint: skipped ({reason})")
        return 0
    if not args.title:
        print("commit-lint: no pull request title (PR_TITLE)", file=sys.stderr)
        return 2

    subjects: list[str] = []
    changed: list[str] = []
    if args.base_sha and args.head_sha:
        subjects = _git(
            "log", "--no-merges", "--format=%s", f"{args.base_sha}..{args.head_sha}"
        )
        changed = _git("diff", "--name-only", f"{args.base_sha}...{args.head_sha}")

    labels = [x.strip() for x in args.labels.split(",") if x.strip()]
    problems = lint(
        args.title,
        subjects,
        changed,
        labels,
        require_fragment=not args.no_fragment_check,
    )
    if problems:
        print("commit-lint: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nAllowed types: " + ", ".join(TYPES) + ". See docs/RELEASING.md.",
            file=sys.stderr,
        )
        return 1
    print(f"commit-lint: ok ({len(subjects)} commit subject(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
