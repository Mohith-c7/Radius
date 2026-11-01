"""Test selection interfaces."""

from typing import Protocol

from radius_testing.domain.entities import TestCase, TestSelection


class TestSelector(Protocol):
    """Contract for deterministic test selection."""

    def select(
        self,
        analysis_id,
        tests: tuple[TestCase, ...],
        changed_file_paths: tuple[str, ...],
        affected_file_paths: tuple[str, ...] = (),
        full_suite_reasons: tuple[str, ...] = (),
    ) -> TestSelection:
        """Return selected tests."""
