"""Tests for test selection enrichment and metrics."""

from pathlib import Path
from uuid import uuid4

from radius_testing.domain import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain import (
    TestFramework as RadiusTestFramework,
)
from radius_testing.domain import (
    TestName as RadiusTestName,
)
from radius_testing.domain import (
    TestPath as RadiusTestPath,
)
from radius_testing.domain import (
    TestSelection as RadiusTestSelection,
)
from radius_testing.dto import TestSelectionResponse as RadiusTestSelectionResponse
from radius_testing.infrastructure import PathBasedTestSelector


def _make_test(path: str) -> RadiusTestCase:
    return RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName(Path(path).name),
        path=RadiusTestPath(path),
        framework=RadiusTestFramework.PYTEST,
    )


def test_selection_enrichment_with_five_tests_and_two_selected() -> None:
    analysis_id = uuid4()
    t1 = _make_test("path1")
    t2 = _make_test("path2")
    t3 = _make_test("path3")
    t4 = _make_test("path4")
    t5 = _make_test("path5")
    tests = (t1, t2, t3, t4, t5)

    selector = PathBasedTestSelector()
    selection = selector.select(
        analysis_id=analysis_id,
        tests=tests,
        changed_file_paths=("path1", "path2"),
    )

    # Verify domain entity properties
    assert selection.selected_count == 2
    assert selection.skipped_count == 3
    assert selection.total_discovered_count == 5
    assert selection.time_saved_percent == 60.0
    assert selection.cli_args == "path1 path2"
    assert selection.skipped_tests == (t3, t4, t5)
    assert [t.path.value for t in selection.skipped_tests] == [
        "path3",
        "path4",
        "path5",
    ]

    # Verify DTO mapping
    response = RadiusTestSelectionResponse.from_entity(selection)
    assert response.selected_count == 2
    assert response.skipped_count == 3
    assert response.total_count == 5
    assert response.time_saved_percent == 60.0
    assert response.cli_args == "path1 path2"
    assert len(response.skipped_tests) == 3
    assert [t.path for t in response.skipped_tests] == [
        "path3",
        "path4",
        "path5",
    ]


def test_time_saved_percent_when_zero_discovered() -> None:
    selection = RadiusTestSelection(
        analysis_id=uuid4(),
        selected_tests=(),
        skipped_tests=(),
        total_discovered_count=0,
    )
    assert selection.time_saved_percent == 0.0


def test_candidate_patterns_expanded() -> None:
    candidates = PathBasedTestSelector._candidate_tests("src/components/button.tsx")
    assert "tests/test_button.py" in candidates
    assert "tests/src/components/test_button.py" in candidates
    assert "src/components/test_button.py" in candidates
    assert "src/components/button_test.py" in candidates
    assert "test_button.py" in candidates
    assert "button_test.py" in candidates
    assert "tests/button.test.ts" in candidates
    assert "tests/button.spec.ts" in candidates
    assert "src/components/button.test.ts" in candidates
    assert "src/components/button.spec.ts" in candidates
    assert "src/components/button.test.tsx" in candidates
    assert "src/components/__tests__/button.test.ts" in candidates
