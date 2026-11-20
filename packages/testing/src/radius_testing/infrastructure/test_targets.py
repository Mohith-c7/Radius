"""Derive each test's target (the module it exercises) from its real imports.

Discovery alone can only guess a target from the test's file name
(``apps/dashboard/tests/account-model.test.mjs`` ->
``apps/dashboard/tests/account-model.mjs``), which is usually a file that does
not exist. Once the dependency graph is built, the test's resolved imports are
known (``"../lib/account-model.ts"`` -> ``apps/dashboard/lib/account-model.ts``),
so the target is chosen from them:

1. an imported repository file whose name matches the test's name;
2. the name-based guess, only when that file really exists;
3. the only imported non-test repository file;
4. otherwise no target (several unrelated imports; nothing is guessed).

A target taken from imports is marked ``metadata["target_source"] = "imports"``.
Selection already follows those imports through the dependency graph (and the
symbol-level refinement may prune them on purpose), so name-convention
selection must not re-add a test through such a target; see
``PathBasedTestSelector``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import PurePosixPath

from radius_testing.domain.entities import TestCase
from radius_testing.domain.value_objects import SourcePath

_TEST_MARKERS = (".test", ".spec")
TARGET_SOURCE_KEY = "target_source"
TARGET_FROM_IMPORTS = "imports"
_INDEX_STEMS = frozenset({"index", "__init__", "mod", "main"})


def refine_test_targets(
    tests: tuple[TestCase, ...],
    imports_by_file: Mapping[str, Iterable[str]],
    repository_files: frozenset[str],
) -> tuple[TestCase, ...]:
    """Return ``tests`` with ``target_path`` taken from resolved imports."""

    test_paths = {test.path.value for test in tests}
    refined: list[TestCase] = []
    for test in tests:
        target, from_imports = _choose_target(
            test,
            tuple(
                path
                for path in sorted(set(imports_by_file.get(test.path.value, ())))
                if path not in test_paths and path != test.path.value
            ),
            repository_files,
        )
        metadata = {
            key: value for key, value in test.metadata.items() if key != TARGET_SOURCE_KEY
        }
        if from_imports:
            metadata[TARGET_SOURCE_KEY] = TARGET_FROM_IMPORTS
        test = replace(
            test,
            target_path=SourcePath(target) if target else None,
            metadata=metadata,
        )
        refined.append(test)
    return tuple(refined)


def subject_name_of_test(test_path: str) -> str:
    """Return the name of the module a test file is named after (``account-model``)."""

    name = PurePosixPath(test_path).name
    for marker in _TEST_MARKERS:
        if marker + "." in name:
            return name.split(marker + ".", 1)[0]
    stem = name.split(".", 1)[0]
    if stem.startswith("test_"):
        return stem.removeprefix("test_")
    if stem.endswith("_test"):
        return stem.removesuffix("_test")
    return stem


def _choose_target(
    test: TestCase,
    imported: tuple[str, ...],
    repository_files: frozenset[str],
) -> tuple[str | None, bool]:
    """Return ``(target, taken_from_imports)``."""

    subject = _normalize(subject_name_of_test(test.path.value))
    named = [path for path in imported if _normalize(_module_name(path)) == subject]
    if named:
        return _closest(test.path.value, named), True
    conventional = test.target_path.value if test.target_path is not None else None
    if conventional is not None and conventional in repository_files:
        return conventional, conventional in imported
    if len(imported) == 1:
        return imported[0], True
    return None, False


def target_from_imports(test: TestCase) -> bool:
    """Return whether ``test.target_path`` was derived from the test's imports."""

    return test.metadata.get(TARGET_SOURCE_KEY) == TARGET_FROM_IMPORTS


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    stem = pure.name.split(".", 1)[0]
    if stem in _INDEX_STEMS and pure.parent.name:
        return pure.parent.name
    return stem


def _normalize(name: str) -> str:
    return name.lower().replace("-", "_")


def _closest(test_path: str, candidates: list[str]) -> str:
    """Prefer the candidate sharing the longest directory prefix with the test."""

    test_parts = PurePosixPath(test_path).parts

    def shared(path: str) -> int:
        count = 0
        for left, right in zip(test_parts, PurePosixPath(path).parts, strict=False):
            if left != right:
                break
            count += 1
        return count

    return sorted(candidates, key=lambda path: (-shared(path), path))[0]
