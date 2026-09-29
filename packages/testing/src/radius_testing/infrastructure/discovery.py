"""Conventional filesystem test discovery."""

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
    def _framework(path: str) -> TestFramework:
        suffixes = Path(path).suffixes
        if suffixes[-1:] == [".py"]:
            return TestFramework.PYTEST
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
