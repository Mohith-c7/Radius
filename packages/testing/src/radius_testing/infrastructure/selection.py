"""Path-based deterministic test selection."""

from pathlib import Path
from uuid import UUID

from radius_testing.domain.entities import SelectedTest, TestCase, TestSelection
from radius_testing.domain.enums import TestSelectionReason


class PathBasedTestSelector:
    """Select tests using changed and affected paths."""

    def select(
        self,
        analysis_id: UUID,
        tests: tuple[TestCase, ...],
        changed_file_paths: tuple[str, ...],
        affected_file_paths: tuple[str, ...] = (),
    ) -> TestSelection:
        """Return selected tests in stable path order."""

        by_path = {test.path.value: test for test in tests}
        by_target = {
            test.target_path.value: test
            for test in tests
            if test.target_path is not None
        }
        selected: dict[str, SelectedTest] = {}

        for path in changed_file_paths:
            normalized = self._normalize(path)
            if normalized in by_path:
                selected[normalized] = SelectedTest(
                    by_path[normalized],
                    TestSelectionReason.CHANGED_FILE,
                )
            if normalized in by_target:
                test = by_target[normalized]
                selected[test.path.value] = SelectedTest(
                    test,
                    TestSelectionReason.AFFECTED_FILE,
                )
            self._select_conventional(
                normalized,
                by_path,
                selected,
                TestSelectionReason.CONVENTION,
            )

        for path in affected_file_paths:
            normalized = self._normalize(path)
            if normalized in by_target:
                test = by_target[normalized]
                selected[test.path.value] = SelectedTest(
                    test,
                    TestSelectionReason.AFFECTED_FILE,
                )
            self._select_conventional(
                normalized,
                by_path,
                selected,
                TestSelectionReason.AFFECTED_FILE,
            )

        return TestSelection(
            analysis_id=analysis_id,
            selected_tests=tuple(
                selected[path] for path in sorted(selected)
            ),
        )

    def _select_conventional(
        self,
        source_path: str,
        by_path: dict[str, TestCase],
        selected: dict[str, SelectedTest],
        reason: TestSelectionReason,
    ) -> None:
        for candidate in self._candidate_tests(source_path):
            if candidate in by_path and candidate not in selected:
                selected[candidate] = SelectedTest(by_path[candidate], reason)

    @staticmethod
    def _candidate_tests(source_path: str) -> tuple[str, ...]:
        path = Path(source_path)
        stem = path.stem
        parent = path.parent.as_posix()
        return (
            f"tests/{parent}/test_{stem}.py",
            f"tests/test_{stem}.py",
            f"{parent}/test_{stem}.py",
            f"{parent}/{stem}_test.py",
            f"{parent}/{stem}.test.ts",
            f"{parent}/{stem}.spec.ts",
        )

    @staticmethod
    def _normalize(path: str) -> str:
        return path.replace("\\", "/")
