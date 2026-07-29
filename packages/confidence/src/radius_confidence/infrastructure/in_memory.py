"""In-memory confidence infrastructure."""

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
        saved = ConfidenceReport(
            id=report.id or uuid4(),
            analysis_id=report.analysis_id,
            confidence_score=report.confidence_score,
            risk_level=report.risk_level,
            summary=report.summary,
            evidence=report.evidence,
            recommendations=report.recommendations,
            generated_at=report.generated_at,
        )
        self._reports[report.analysis_id] = saved
        return saved

    def get_by_analysis_id(self, analysis_id: UUID) -> ConfidenceReport | None:
        """Return confidence report by analysis id."""

        return self._reports.get(analysis_id)
