"""DEC-043: is a ``.radius/intent.yml`` criterion affected by this pull request?

A standing criterion of the repository spec that declares ``paths:`` is in scope only
when at least one changed file matches one of those paths. The paths come from the
BASE copy of the spec (``CriterionInput.scope_paths``), so a PR cannot move a criterion
out of scope by editing its ``paths:``. Matching follows the hint semantics of
``paths:`` (``packages/intent/README.md``): a repository-relative glob (``*``, ``?``,
``**``), an exact file, or a directory (``src/auth`` or ``src/auth/`` matches every file
below it).

Everything unknown keeps the criterion in scope: no scope paths, unknown changed files,
or a path that is not a valid glob.
"""

from __future__ import annotations

from collections.abc import Iterable

from radius_evidence.policy.globs import glob_problem, normalize_path, path_matches

#: Reason code of a criterion excluded because no changed file matches its paths.
NOT_AFFECTED = "not_affected_by_pr"
NOT_AFFECTED_DETAIL = "not affected by this PR: no changed file matches its paths"


def path_in_scope(pattern: str, path: str) -> bool:
    """True when ``path`` is the file, lies under the directory, or matches the glob."""

    pat = normalize_path(pattern)
    target = normalize_path(path)
    if not pat or not target:
        return False
    if pat.endswith("/"):
        return target.startswith(pat)
    if path_matches(pat, target):
        return True
    return not any(c in pat for c in "*?") and target.startswith(pat + "/")


def criterion_in_scope(
    scope_paths: Iterable[str] | None, changed_paths: Iterable[str] | None
) -> bool:
    """False only when every fact is known and no changed file matches a scope path."""

    if changed_paths is None or not scope_paths:
        return True
    patterns = [p for p in scope_paths if isinstance(p, str)]
    if not patterns or any(glob_problem(normalize_path(p).rstrip("/") or p) for p in patterns):
        return True
    changed = [c for c in changed_paths if isinstance(c, str) and c]
    return any(path_in_scope(p, c) for p in patterns for c in changed)
