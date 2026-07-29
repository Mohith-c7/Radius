"""Testing domain tests."""

from uuid import uuid4

import pytest
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
    TestType as RadiusTestType,
)


def test_value_objects_reject_empty_or_absolute_paths() -> None:
    with pytest.raises(ValueError, match="Test path cannot be empty"):
        RadiusTestPath("")

    with pytest.raises(ValueError, match="repository-relative"):
        RadiusTestPath("/tests/test_app.py")

    with pytest.raises(ValueError, match="Test name cannot be empty"):
        RadiusTestName(" ")


def test_test_case_accepts_valid_values() -> None:
    test_case = RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName("test_app"),
        path=RadiusTestPath("tests/test_app.py"),
        framework=RadiusTestFramework.PYTEST,
        test_type=RadiusTestType.UNIT,
    )

    assert test_case.path.value == "tests/test_app.py"
