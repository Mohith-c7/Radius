"""Map changed files to the tests that can provide evidence about them.

This module decides, per changed file, whether Radius has a credible way to
verify it. It is deliberately conservative: when impact cannot be computed
from the head snapshot (deleted/renamed files, build or dependency manifests,
shared test fixtures) it requests the full discovered suite rather than
guessing, and when a file cannot be analyzed it says so instead of treating it
as unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath

NON_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".rst",
        ".adoc",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
    }
)
NON_EXECUTABLE_NAMES = frozenset(
    {
        "LICENSE",
        "LICENSE.txt",
        "NOTICE",
        "AUTHORS",
        "CODEOWNERS",
        ".gitignore",
        ".editorconfig",
        ".mailmap",
    }
)
NON_EXECUTABLE_DIRS = frozenset({"docs", "doc"})

# Changes to these files can alter the behavior of any test, and their impact
# is not visible in the import graph.
FULL_SUITE_PATTERNS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "constraints*.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "tox.ini",
    "pytest.ini",
    "conftest.py",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig*.json",
    "jest.config.*",
    "vitest.config.*",
    "babel.config.*",
    ".babelrc",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


@dataclass(frozen=True, slots=True)
class ChangedFileRef:
    """A changed file and its git change type."""

    path: str
    change_type: str = "modified"


@dataclass(frozen=True, slots=True)
class ChangeTestMapping:
    """Result of mapping changed files to tests."""

    covered_files: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    unanalyzed_files: tuple[str, ...] = ()
    non_executable_files: tuple[str, ...] = ()
    parse_failures: tuple[str, ...] = ()
    full_suite_reasons: tuple[str, ...] = ()
    graph_selected_tests: tuple[str, ...] = ()
    tests_by_changed_file: dict[str, tuple[str, ...]] = field(default_factory=dict)


def is_non_executable(path: str) -> bool:
    """Return whether a change to ``path`` cannot alter runtime behavior."""

    pure = PurePosixPath(path)
    if pure.name in NON_EXECUTABLE_NAMES:
        return True
    if pure.suffix.lower() in NON_EXECUTABLE_SUFFIXES:
        return True
    return bool(pure.parts) and pure.parts[0] in NON_EXECUTABLE_DIRS


def full_suite_trigger(path: str) -> bool:
    """Return whether a change to ``path`` should trigger the full suite."""

    name = PurePosixPath(path).name
    return any(fnmatch(name, pattern) for pattern in FULL_SUITE_PATTERNS)


def map_changes_to_tests(
    *,
    changed_files: tuple[ChangedFileRef, ...],
    dependents: dict[str, frozenset[str]],
    test_paths: frozenset[str],
    conventional_tests: dict[str, tuple[str, ...]],
    parse_failures: frozenset[str] = frozenset(),
) -> ChangeTestMapping:
    """Classify every changed file into exactly one evidence bucket.

    Args:
        changed_files: Files changed by the pull request.
        dependents: For each changed path, every repository file that
            transitively imports it (including itself). An empty set means the
            file is not in the dependency graph.
        test_paths: Paths of all tests discovered in this snapshot.
        conventional_tests: Tests matched to a changed path by naming
            convention.
        parse_failures: Repository files the parser could not process. Only
            *changed* files that failed to parse block verification: an
            unparseable unchanged file cannot be a working importer of the
            changed code.
    """

    covered: list[str] = []
    unmapped: list[str] = []
    unanalyzed: list[str] = []
    non_executable: list[str] = []
    failed_to_parse: list[str] = []
    full_suite: list[str] = []
    graph_tests: set[str] = set()
    tests_by_file: dict[str, tuple[str, ...]] = {}

    for change in changed_files:
        path = change.path.replace("\\", "/")
        if is_non_executable(path):
            non_executable.append(path)
            continue
        if change.change_type in {"deleted", "renamed"}:
            full_suite.append(
                f"{path} was {change.change_type}; its former importers cannot be "
                "derived from the head snapshot"
            )
            _cover_with_full_suite(path, test_paths, covered, unmapped, tests_by_file)
            continue
        if full_suite_trigger(path):
            full_suite.append(f"{path} is build, dependency, or shared test configuration")
            _cover_with_full_suite(path, test_paths, covered, unmapped, tests_by_file)
            continue
        if path in test_paths:
            covered.append(path)
            tests_by_file[path] = (path,)
            continue
        if path in parse_failures:
            failed_to_parse.append(path)
            continue
        reached = dependents.get(path, frozenset())
        if not reached:
            unanalyzed.append(path)
            continue
        reaching_tests = tuple(sorted(reached & test_paths))
        graph_tests.update(reaching_tests)
        matched = tuple(sorted(set(reaching_tests) | set(conventional_tests.get(path, ()))))
        if matched:
            covered.append(path)
            tests_by_file[path] = matched
        else:
            unmapped.append(path)

    return ChangeTestMapping(
        covered_files=tuple(covered),
        unmapped_files=tuple(unmapped),
        unanalyzed_files=tuple(unanalyzed),
        non_executable_files=tuple(non_executable),
        parse_failures=tuple(failed_to_parse),
        full_suite_reasons=tuple(full_suite),
        graph_selected_tests=tuple(sorted(graph_tests)),
        tests_by_changed_file=tests_by_file,
    )


def _cover_with_full_suite(
    path: str,
    test_paths: frozenset[str],
    covered: list[str],
    unmapped: list[str],
    tests_by_file: dict[str, tuple[str, ...]],
) -> None:
    if test_paths:
        covered.append(path)
        tests_by_file[path] = tuple(sorted(test_paths))
    else:
        unmapped.append(path)
