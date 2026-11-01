"""In-memory confidence infrastructure."""

from dataclasses import replace
from uuid import UUID, uuid4

from radius_shared.errors import ValidationError

from radius_confidence.domain.entities import ConfidenceReport


class InMemoryConfidenceStore:
    """Store confidence reports in memory."""

    def __init__(self) -> None:
        self._reports: dict[UUID, ConfidenceReport] = {}

    def save_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Persist a confidence report immutably by analysis id."""

        if report.analysis_id in self._reports:
            msg = f"Confidence report for analysis {report.analysis_id} already exists."
            raise ValidationError(msg)
        return self.replace_report(report)

    def replace_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Store a report, replacing any previous report for the analysis.

        Uses ``dataclasses.replace`` so that every field (including the
        verification verdict and completeness metrics) is preserved.
        """

        saved = replace(report, id=report.id or uuid4())
        self._reports[report.analysis_id] = saved
        return saved

    def get_by_analysis_id(self, analysis_id: UUID) -> ConfidenceReport | None:
        """Return confidence report by analysis id."""

        return self._reports.get(analysis_id)
