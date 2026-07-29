"""Test discovery interfaces."""

from pathlib import Path
from typing import Protocol

from radius_testing.domain.entities import TestCase


class TestDiscoverer(Protocol):
    """Contract for deterministic test discovery."""

    def discover(self, repository_path: Path) -> tuple[TestCase, ...]:
        """Return discovered tests."""
