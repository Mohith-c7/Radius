"""Analysis pipeline interfaces."""

from typing import Protocol
from uuid import UUID


class AnalysisPipeline(Protocol):
    """Contract for asynchronous analysis execution."""

    def enqueue(self, analysis_id: UUID) -> None:
        """Queue an analysis for background processing."""
