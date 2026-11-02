"""Simple analysis queue adapters."""

from collections import deque
from uuid import UUID


class InMemoryAnalysisQueue:
    """FIFO analysis queue for local worker execution and tests."""

    def __init__(self) -> None:
        self._pending: deque[UUID] = deque()
        self._queued: set[UUID] = set()

    def enqueue(self, analysis_id: UUID) -> None:
        """Queue an analysis once."""

        if analysis_id in self._queued:
            return
        self._pending.append(analysis_id)
        self._queued.add(analysis_id)

    def cancel_queued(self, analysis_id: UUID, reason: str = "") -> bool:
        """Drop a queued analysis; ``False`` if it is no longer queued."""

        if analysis_id not in self._queued:
            return False
        self._pending.remove(analysis_id)
        self._queued.remove(analysis_id)
        return True

    def claim_next(self) -> UUID | None:
        """Claim the next pending analysis id."""

        if not self._pending:
            return None
        analysis_id = self._pending.popleft()
        self._queued.remove(analysis_id)
        return analysis_id

    def __len__(self) -> int:
        return len(self._pending)
