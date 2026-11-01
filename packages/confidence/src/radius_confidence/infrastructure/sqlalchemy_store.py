"""SQLAlchemy confidence report store."""

from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.errors import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from radius_confidence.domain.entities import (
    ConfidenceEvidence,
    ConfidenceReport,
)
from radius_confidence.domain.enums import EvidenceCategory, EvidenceImpact, RiskLevel
from radius_confidence.domain.value_objects import ConfidenceScore


class SqlAlchemyConfidenceStore:
    """Persist confidence reports and evidence in SQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Persist or replace confidence report by analysis id."""

        row = self._session.scalar(
            select(db_models.ConfidenceReport).where(
                db_models.ConfidenceReport.analysis_id == report.analysis_id
            )
        )
        if row is None:
            row = db_models.ConfidenceReport(
                analysis_id=report.analysis_id,
                confidence_score=report.confidence_score.value,
                risk_level=db_enums.RiskLevel(report.risk_level.value),
                change_risk=report.change_risk,
                verification_status=report.verification_status,
                analysis_completeness=report.analysis_completeness,
                summary=report.summary,
                recommendations=list(report.recommendations),
                generated_at=report.generated_at,
            )
            self._session.add(row)
        else:
            self._session.execute(
                delete(db_models.ConfidenceEvidence).where(
                    db_models.ConfidenceEvidence.report_id == row.id
                )
            )
        row.confidence_score = report.confidence_score.value
        row.risk_level = db_enums.RiskLevel(report.risk_level.value)
        row.change_risk = report.change_risk
        row.verification_status = report.verification_status
        row.analysis_completeness = report.analysis_completeness
        row.summary = report.summary
        row.recommendations = list(report.recommendations)
        row.generated_at = report.generated_at
        self._session.flush()
        self._session.add_all(
            [
                db_models.ConfidenceEvidence(
                    report_id=row.id,
                    category=evidence.category.value,
                    label=evidence.label,
                    message=evidence.message,
                    impact=evidence.impact.value,
                    value=evidence.value,
                )
                for evidence in report.evidence
            ]
        )
        self._session.flush()
        saved = self.get_by_analysis_id(report.analysis_id)
        if saved is None:
            msg = "Confidence report could not be saved."
            raise ValidationError(msg)
        return saved

    def replace_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Replace the report for an analysis (``save_report`` already upserts)."""

        return self.save_report(report)

    def get_by_analysis_id(self, analysis_id: UUID) -> ConfidenceReport | None:
        """Return confidence report by analysis id."""

        row = self._session.scalar(
            select(db_models.ConfidenceReport)
            .where(db_models.ConfidenceReport.analysis_id == analysis_id)
            .options(selectinload(db_models.ConfidenceReport.evidence_items))
        )
        if row is None:
            return None
        return ConfidenceReport(
            id=row.id,
            analysis_id=row.analysis_id,
            confidence_score=ConfidenceScore(float(row.confidence_score)),
            risk_level=RiskLevel(row.risk_level.value),
            summary=row.summary,
            evidence=tuple(
                ConfidenceEvidence(
                    category=EvidenceCategory(evidence.category),
                    label=evidence.label,
                    message=evidence.message,
                    impact=EvidenceImpact(evidence.impact),
                    value=(
                        float(evidence.value)
                        if evidence.value is not None
                        else None
                    ),
                )
                for evidence in sorted(
                    row.evidence_items,
                    key=lambda item: (item.category, item.label, item.message),
                )
            ),
            recommendations=tuple(row.recommendations),
            generated_at=row.generated_at,
            change_risk=row.change_risk,
            verification_status=row.verification_status,
            analysis_completeness=float(row.analysis_completeness) if row.analysis_completeness is not None else None,
        )
