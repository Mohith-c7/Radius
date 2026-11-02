"""File-role classification for the tamper rules.

The test-file convention mirrors ``radius_testing.infrastructure.discovery``
(``ConventionalTestDiscoverer._is_test_path``). ``radius_analysis`` must not import
another domain's implementation, so the convention is restated here and a parity
test (``test_tamper_classify.py``) keeps the two in sync.
"""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from pathlib import PurePosixPath


class Role(StrEnum):
    TEST = "test"
    CONFTEST = "conftest"
    SOURCE = "source"
    CI_WORKFLOW = "ci_workflow"
    BUILD_CONFIG = "build_config"
    MANIFEST = "manifest"
    LOCKFILE = "lockfile"
    SNAPSHOT = "snapshot"
    DOC = "doc"
    OTHER = "other"


_NON_TEST_SUPPORT_DIRECTORIES = frozenset(
    {"fixtures", "__fixtures__", "helpers", "__mocks__", "testdata", "data"}
)
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")
_LOCKFILES = frozenset(
    {"uv.lock", "poetry.lock", "pipfile.lock", "pdm.lock", "package-lock.json",
     "pnpm-lock.yaml", "yarn.lock"}
)
_BUILD_CONFIG_NAMES = frozenset(
    {"pytest.ini", "tox.ini", "setup.cfg", ".coveragerc", "mypy.ini", ".mypy.ini",
     "ruff.toml", ".ruff.toml", "pyproject.toml", "makefile", "noxfile.py", "justfile",
     ".pre-commit-config.yaml", ".flake8", "pylintrc", ".pylintrc", "codecov.yml",
     ".codecov.yml"}
)
_SNAPSHOT_GLOBS = (
    "*.snap", "*.golden", "*.approved.*", "*.received.*", "*_snapshot.json", "*.ambr",
)
_SNAPSHOT_DIRS = frozenset({"__snapshots__", "snapshots", "golden", "goldens", "__golden__"})
_CI_NAMES = frozenset({".gitlab-ci.yml", "azure-pipelines.yml", "jenkinsfile", ".travis.yml"})


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    if name in {"conftest.py", "__init__.py", "setup.py"}:
        return False
    if any(part in _NON_TEST_SUPPORT_DIRECTORIES for part in p.parts[:-1]):
        return False
    conventional = (
        name.startswith("test_")
        and name.endswith(".py")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )
    if conventional:
        return True
    in_test_dir = any(part in {"test", "tests", "__tests__"} for part in p.parts[:-1])
    return in_test_dir and name.endswith(_CODE_SUFFIXES) and not name.startswith(("_", "."))


def classify_path(path: str) -> frozenset[Role]:
    """Roles of a path; a path can have several (``pyproject.toml`` is config and manifest)."""
    p = PurePosixPath(path)
    lower = p.name.lower()
    parts = p.parts
    roles: set[Role] = set()
    if lower in _LOCKFILES:
        roles.add(Role.LOCKFILE)
    if lower == "conftest.py":
        roles.add(Role.CONFTEST)
    if is_test_path(path):
        roles.add(Role.TEST)
    if (
        len(parts) >= 3
        and parts[0] == ".github"
        and parts[1] == "workflows"
        and lower.endswith((".yml", ".yaml"))
    ) or lower in _CI_NAMES:
        roles.add(Role.CI_WORKFLOW)
    if lower in _BUILD_CONFIG_NAMES or lower.endswith(".mk"):
        roles.add(Role.BUILD_CONFIG)
    if (
        lower in {"pyproject.toml", "setup.py", "pipfile", "package.json"}
        or (lower.startswith("requirements") and lower.endswith((".txt", ".in")))
    ):
        roles.add(Role.MANIFEST)
    if any(fnmatch.fnmatchcase(lower, g) for g in _SNAPSHOT_GLOBS) or any(
        d in _SNAPSHOT_DIRS for d in parts[:-1]
    ):
        roles.add(Role.SNAPSHOT)
    if lower.endswith((".md", ".rst", ".txt")) and Role.MANIFEST not in roles:
        roles.add(Role.DOC)
    if lower.endswith((".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")) and not (
        roles & {Role.TEST, Role.CONFTEST, Role.BUILD_CONFIG, Role.SNAPSHOT}
    ):
        roles.add(Role.SOURCE)
    if not roles:
        roles.add(Role.OTHER)
    return frozenset(roles)
