"""Conventional filesystem test discovery."""

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from radius_testing.domain.entities import TestCase
from radius_testing.domain.enums import TestFramework, TestType
from radius_testing.domain.value_objects import TestName, TestPath

IGNORED_DIRECTORIES = {
    ".git",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
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
            tests.append(
                TestCase(
                    id=uuid5(NAMESPACE_URL, f"radius:test:{relative}"),
                    name=TestName(Path(relative).stem),
                    path=TestPath(relative),
                    framework=self._framework(relative),
                    test_type=TestType.UNIT,
                )
            )
        return tuple(tests)

    @staticmethod
    def _is_ignored(path: Path, root: Path) -> bool:
        return any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)

    @staticmethod
    def _is_test_path(path: str) -> bool:
        name = Path(path).name
        return (
            name.startswith("test_")
            and name.endswith(".py")
            or name.endswith("_test.py")
            or ".test." in name
            or ".spec." in name
        )

    @staticmethod
    def _framework(path: str) -> TestFramework:
        suffix = Path(path).suffix
        if suffix == ".py":
            return TestFramework.PYTEST
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return TestFramework.UNKNOWN
        return TestFramework.UNKNOWN
