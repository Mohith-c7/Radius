"""Verdict v2 persistence orchestration (VS-06/VS-07): ``VerdictStore`` over SQL.

The table models and the repository live in ``radius_shared``. This adapter
opens its own short session per call (like ``ingest_intent_best_effort``), so a
v2 failure can never roll back or fail the v1 analysis transaction.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from radius_evidence.domain.inputs import StageAInput
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_repository import SaveOutcome, SqlVerdictV2Repository
from sqlalchemy.orm import Session, sessionmaker


class SqlVerdictStore:
    """Implements ``ports.VerdictStore`` against ``verdict_v2``."""

    def __init__(
        self, session_factory: sessionmaker[Session], mode: VerdictV2Mode
    ) -> None:
        if mode == VerdictV2Mode.OFF:
            msg = "the verdict v2 store is not used while the flag is off"
            raise ValueError(msg)
        self._session_factory = session_factory
        self._mode = mode

    def save_outcome(
        self, organization_id: UUID, analysis_id: UUID, bundle: dict[str, Any]
    ) -> SaveOutcome:
        with self._session_factory() as session:
            outcome = SqlVerdictV2Repository(session).save(
                organization_id, analysis_id, bundle, mode=self._mode.value
            )
            session.commit()
            return outcome

    def save(
        self, organization_id: UUID, analysis_id: UUID, bundle: dict[str, Any]
    ) -> bool:
        """Persist ``bundle``; True when the newest revision changed.

        Identical inputs are a no-op (False). A bundle equal to an older run
        moves that run back to the top and also returns True.
        """

        return self.save_outcome(organization_id, analysis_id, bundle).changed

    def latest_stage_a(
        self, organization_id: UUID, analysis_id: UUID
    ) -> StageAInput | None:
        with self._session_factory() as session:
            raw = SqlVerdictV2Repository(session).latest_stage_a(
                organization_id, analysis_id
            )
        if raw is None:
            return None
        return StageAInput.from_dict(raw)
