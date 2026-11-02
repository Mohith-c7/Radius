"""Ports between the worker stages (contract file of VS-00).

Implementations: ``collect`` (VS-05), ``scoring`` and ``store`` (VS-06),
``publish`` (VS-08). Tests inject fakes. No behaviour here.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from radius_evidence.domain.inputs import StageAInput, StageBInput


class StageACollector(Protocol):
    """Build the Stage A facts for one analysis (needs the repository checkout)."""

    def collect(self, analysis_id: UUID, command: Any) -> StageAInput: ...


class StageBScorer(Protocol):
    """Pure scoring of a Stage B input into the stored bundle (a plain dict)."""

    def score(self, stage_b: StageBInput) -> dict[str, Any]: ...


class VerdictStore(Protocol):
    """Persist a computed bundle; recomputing identical inputs is a no-op."""

    def save(self, organization_id: UUID, analysis_id: UUID, bundle: dict[str, Any]) -> bool:
        """Return True when a new row was written."""
        ...

    def latest_stage_a(self, organization_id: UUID, analysis_id: UUID) -> StageAInput | None: ...


class VerdictPublishPort(Protocol):
    """Publish the latest stored verdict according to the flag mode."""

    def publish(self, organization_id: UUID, analysis_id: UUID) -> None: ...
