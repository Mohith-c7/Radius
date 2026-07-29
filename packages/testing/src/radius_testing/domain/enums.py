"""Testing domain enum values."""

from enum import StrEnum


class TestFramework(StrEnum):
    """Supported test framework labels."""

    PYTEST = "pytest"
    JEST = "jest"
    VITEST = "vitest"
    MOCHA = "mocha"
    UNKNOWN = "unknown"


class TestType(StrEnum):
    """Test type labels."""

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    UNKNOWN = "unknown"


class TestSelectionReason(StrEnum):
    """Why a test was selected."""

    CHANGED_FILE = "changed_file"
    AFFECTED_FILE = "affected_file"
    SAME_DIRECTORY = "same_directory"
    CONVENTION = "convention"
    FALLBACK = "fallback"


class TestRunStatus(StrEnum):
    """Planned or executed test run status."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
