"""Path-based deterministic test selection."""

from pathlib import Path
from uuid import UUID

from radius_testing.domain.entities import (
    SelectedTest, TestCase, TestSelection, TestSelectionDecision,
)
from radius_testing.domain.enums import TestDecision, TestSelectionReason


class PathBasedTestSelector:
    """Select tests using changed and affected paths."""

    def select(
        self,
        analysis_id: UUID,
        tests: tuple[TestCase, ...],
        changed_file_paths: tuple[str, ...],
        affected_file_paths: tuple[str, ...] = (),
        changed_symbols: tuple[str, ...] = (),
        semantic_evidence: dict[str, tuple[str, ...]] | None = None,
        coverage_evidence: dict[str, tuple[str, ...]] | None = None,
        history_evidence: dict[str, tuple[str, ...]] | None = None,
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

        semantic_evidence = semantic_evidence or {}
        coverage_evidence = coverage_evidence or {}
        history_evidence = history_evidence or {}
        decisions: list[TestSelectionDecision] = []
        # Evidence from coverage, history and semantic analysis is additive. A
        # test is never selected merely because an LLM guessed; semantic facts
        # must be supplied by the semantic-analysis integration.
        for test in sorted(tests, key=lambda item: item.path.value):
            path = test.path.value
            sources: list[str] = []
            details: list[str] = []
            if path in selected:
                sources.append("AST_CPG")
                reason = selected[path].reason.value.replace("_", " ")
                details.append(f"Static dependency analysis found a {reason} relationship.")
                if changed_symbols:
                    details.append("Changed symbols: " + ", ".join(changed_symbols))
            for source, evidence in (
                ("GEMINI_SEMANTIC", semantic_evidence.get(path, ())),
                ("RUNTIME_COVERAGE", coverage_evidence.get(path, ())),
                ("TEST_HISTORY", history_evidence.get(path, ())),
            ):
                if evidence:
                    sources.append(source)
                    details.extend(evidence)
            is_selected = bool(sources)
            score = min(100.0, len(sources) * 25.0 + (20.0 if "AST_CPG" in sources else 0.0))
            if is_selected and path not in selected:
                selected[path] = SelectedTest(test, TestSelectionReason.FALLBACK)
            if is_selected:
                decision = TestDecision.SELECTED
                reason = "Selected because " + "; ".join(details)
            else:
                decision = TestDecision.SKIPPED
                score = 0.0
                details = ["No static dependency, runtime coverage, semantic, or historical evidence links this test to the change."]
                reason = "Skipped: " + details[0]
            decisions.append(TestSelectionDecision(
                test_case=test, decision=decision, evidence_sources=tuple(sources),
                evidence_details=tuple(details), relevance_score=score, reason=reason,
            ))

        return TestSelection(
            analysis_id=analysis_id,
            selected_tests=tuple(
                selected[path] for path in sorted(selected)
            ),
            decisions=tuple(decisions),
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
