"""Tests for canonical server-authoritative test manifests."""

from uuid import uuid4

from radius_testing.domain.entities import (
    ReportedTestCase as RadiusReportedTestCase,
)
from radius_testing.domain.entities import (
    SelectedTest as RadiusSelectedTest,
)
from radius_testing.domain.entities import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain.entities import (
    TestSelection as RadiusTestSelection,
)
from radius_testing.domain.enums import (
    TestFramework as RadiusTestFramework,
)
from radius_testing.domain.enums import (
    TestSelectionReason as RadiusTestSelectionReason,
)
from radius_testing.domain.enums import (
    TestType as RadiusTestType,
)
from radius_testing.domain.value_objects import (
    TestName as RadiusTestName,
)
from radius_testing.domain.value_objects import (
    TestPath as RadiusTestPath,
)
from radius_testing.provenance import build_manifest, validate_cases_for_slot


def test_manifest_digest_and_report_slots_are_deterministic() -> None:
    analysis_id, repository_id = uuid4(), uuid4()
    test = RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName("test_validates_user"),
        path=RadiusTestPath("tests/test_users.py"),
        framework=RadiusTestFramework.PYTEST,
        test_type=RadiusTestType.UNIT,
    )
    selection = RadiusTestSelection(
        analysis_id=analysis_id,
        selected_tests=(
            RadiusSelectedTest(test, RadiusTestSelectionReason.AFFECTED_FILE),
        ),
    )

    first, first_digest = build_manifest(
        analysis_id, repository_id, "a" * 40, selection
    )
    second, second_digest = build_manifest(
        analysis_id, repository_id, "a" * 40, selection
    )

    assert first == second
    assert first_digest == second_digest
    assert first["schema_version"] == 1
    assert len(first["slots"]) == 1
    assert first["slots"][0]["test_paths"] == ["tests/test_users.py"]
    slot_id = first["slots"][0]["slot_id"]
    assert validate_cases_for_slot(
        (RadiusReportedTestCase("tests/test_users.py", None, "test_validates_user"),),
        first,
        slot_id,
    )
    assert not validate_cases_for_slot(
        (RadiusReportedTestCase("tests/test_other.py", None, "test_forged"),),
        first,
        slot_id,
    )
    assert not validate_cases_for_slot((), first, slot_id)
