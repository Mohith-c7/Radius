"""Conventional filesystem test discovery.

A file is a test when its path follows a test convention *and* its content
defines at least one test: helper modules under ``tests/`` and scripts that only
look like tests (``scripts/load_test.py``) are not tests, because CI running
them reports nothing and every selected-but-unreported file blocks the verdict.
The framework is read from what the file imports (``node:test``, ``vitest``,
``@playwright/test``, ``@jest/globals``, ``mocha``); the file suffix is only a
fallback.
"""

import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from radius_testing.domain.entities import TestCase
from radius_testing.domain.enums import TestFramework, TestType
from radius_testing.domain.value_objects import SourcePath, TestName, TestPath

IGNORED_DIRECTORIES = {
    ".git",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


# Support code that lives under test directories but is not itself a test.
NON_TEST_SUPPORT_DIRECTORIES = {
    "fixtures",
    "__fixtures__",
    "helpers",
    "__mocks__",
    "testdata",
    "data",
}


_MAX_SNIFF_BYTES = 1_000_000
_PY_TEST_DEFINITION = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+test|^[ \t]*class[ \t]+Test", re.M)
_JS_TEST_CALL = re.compile(r"\b(?:test|it|describe|suite)(?:\.\w+)*\s*\(")
_JS_RUNNER_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(?\s*)["']"""
    r"""(node:test|vitest|@playwright/test|@jest/globals|mocha)["']"""
)
_RUNNER_FRAMEWORKS = {
    "node:test": TestFramework.NODE_TEST,
    "vitest": TestFramework.VITEST,
    "@playwright/test": TestFramework.PLAYWRIGHT,
    "@jest/globals": TestFramework.JEST,
    "mocha": TestFramework.MOCHA,
}


class ConventionalTestDiscoverer:
    """Discover tests from conventional file paths."""

    def discover(self, repository_path: Path) -> tuple[TestCase, ...]:
        """Return discovered tests in stable path order."""

        root = repository_path.resolve()
        tests: list[TestCase] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or self._is_ignored(path, root):
                continue
            relative = path.relative_to(root).as_posix()
            if not self._is_test_path(relative):
                continue
            content = self._sniff(path)
            if content is not None and not self._defines_tests(relative, content):
                continue
            framework = self._framework(relative, content)
            tests.append(
                TestCase(
                    id=uuid5(NAMESPACE_URL, f"radius:test:{relative}"),
                    name=TestName(Path(relative).stem),
                    path=TestPath(relative),
                    framework=framework,
                    test_type=(
                        TestType.E2E if framework == TestFramework.PLAYWRIGHT else TestType.UNIT
                    ),
                    target_path=self._target_path(relative),
                )
            )
        return tuple(tests)

    @staticmethod
    def _is_ignored(path: Path, root: Path) -> bool:
        return any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)

    @staticmethod
    def _is_test_path(path: str) -> bool:
        p = Path(path)
        name = p.name
        if name in {"conftest.py", "__init__.py", "setup.py"}:
            return False
        if any(part in NON_TEST_SUPPORT_DIRECTORIES for part in p.parts[:-1]):
            return False
        is_conventional_name = (
            name.startswith("test_")
            and name.endswith(".py")
            or name.endswith("_test.py")
            or ".test." in name
            or ".spec." in name
        )
        if is_conventional_name:
            return True
        parts = p.parts
        in_test_dir = any(part in {"test", "tests", "__tests__"} for part in parts[:-1])
        is_code_file = name.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs"))
        return in_test_dir and is_code_file and not name.startswith(("_", "."))

    @staticmethod
    def _sniff(path: Path) -> str | None:
        """Return the file text, or ``None`` when it cannot be read cheaply."""

        try:
            if path.stat().st_size > _MAX_SNIFF_BYTES:
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    @staticmethod
    def _defines_tests(path: str, content: str) -> bool:
        if path.endswith(".py"):
            return _PY_TEST_DEFINITION.search(content) is not None
        return _JS_TEST_CALL.search(content) is not None

    @staticmethod
    def _framework(path: str, content: str | None = None) -> TestFramework:
        suffixes = Path(path).suffixes
        if suffixes[-1:] == [".py"]:
            return TestFramework.PYTEST
        if content:
            match = _JS_RUNNER_IMPORT.search(content)
            if match is not None:
                return _RUNNER_FRAMEWORKS[match.group(1)]
        if suffixes[-1:] in ([".ts"], [".tsx"]):
            return TestFramework.VITEST
        if suffixes[-1:] in ([".js"], [".jsx"]):
            return TestFramework.JEST
        return TestFramework.UNKNOWN

    @staticmethod
    def _target_path(path: str) -> SourcePath | None:
        candidate = ConventionalTestDiscoverer._target_candidate(path)
        return SourcePath(candidate) if candidate is not None else None

    @staticmethod
    def _target_candidate(path: str) -> str | None:
        relative = Path(path)
        name = relative.name
        parent = relative.parent.as_posix()
        if name.startswith("test_") and name.endswith(".py"):
            stem = name.removeprefix("test_").removesuffix(".py")
            if parent in {"tests", "test"}:
                return f"src/{stem}.py"
            if "/tests" in parent:
                return f"{parent.replace('/tests', '')}/{stem}.py"
            if "/test" in parent:
                return f"{parent.replace('/test', '')}/{stem}.py"
            return f"{parent}/{stem}.py"
        if name.endswith("_test.py"):
            return f"{parent}/{name.removesuffix('_test.py')}.py"

        for marker in (".test.", ".spec."):
            if marker in name:
                stem, suffix = name.split(marker, maxsplit=1)
                extension = suffix.rsplit(".", maxsplit=1)[-1]
                return f"{parent}/{stem}.{extension}"
        return None
