"""Map intent domain objects to API views (IN-08)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from radius_intent.application import BuildReport, SnapshotDiffResult
from radius_intent.domain import Criterion, IntentSnapshot, IntentSource, SourceRef

from radius_api.intent_management import (
    BuildOutcome,
    CriterionHistoryEntry,
    CriterionOutcome,
    SnapshotBundle,
)
from radius_api.schemas.intent import (
    BuildReportView,
    BuildResultView,
    CarryEventView,
    CriterionChangeView,
    CriterionResultView,
    CriterionView,
    DiagnosticView,
    HintsView,
    OriginView,
    SanitizationView,
    SnapshotDiffView,
    SnapshotSummaryView,
    SnapshotView,
    SourceDetailView,
    SourceSummaryView,
    SpanView,
)


def criterion_view(criterion: Criterion) -> CriterionView:
    """Return the API view of a criterion."""

    origin = criterion.origin
    return CriterionView(
        id=criterion.id,
        text=criterion.text,
        origin=OriginView(
            method=origin.extraction_method.value,
            extractor_version=origin.extractor_version,
            source_kind=origin.source.kind.value,
            source_id=origin.source.source_id,
            source_hash=origin.source.raw_text_hash,
            retrieved_at=origin.retrieved_at,
        ),
        span=SpanView(
            source_id=criterion.span.source_id,
            start=criterion.span.start,
            end=criterion.span.end,
        ),
        weight=criterion.weight,
        testability=criterion.testability.value,
        testability_rationale=criterion.testability_rationale,
        state=criterion.state.value,
        hints=HintsView(
            paths=list(criterion.hints.paths),
            tests=list(criterion.hints.tests),
            label=criterion.hints.label,
        ),
    )


def _summary_fields(snapshot: IntentSnapshot) -> dict[str, object]:
    counts = Counter(c.state.value for c in snapshot.criteria)
    return {
        "id": snapshot.snapshot_id,
        "analysis_id": snapshot.analysis_id,
        "version": snapshot.version,
        "parent_snapshot_id": snapshot.parent_snapshot_id,
        "created_at": snapshot.created_at,
        "criteria_count": len(snapshot.criteria),
        "state_counts": dict(sorted(counts.items())),
        "source_count": len(snapshot.sources),
    }


def snapshot_summary(snapshot: IntentSnapshot) -> SnapshotSummaryView:
    """Return a history-list entry."""

    return SnapshotSummaryView(**_summary_fields(snapshot))


def _source_summary(ref: SourceRef, bundle: SnapshotBundle) -> SourceSummaryView:
    stored = bundle.sources.get((ref.kind.value, ref.source_id, ref.raw_text_hash))
    return SourceSummaryView(
        kind=ref.kind.value,
        source_id=ref.source_id,
        raw_text_hash=ref.raw_text_hash,
        length=None if stored is None else len(stored.text),
        truncated=bool(stored and stored.truncated),
        suspicious_content_removed=bool(stored and stored.suspicious_content_removed),
        fetched_at=None if stored is None else stored.fetched_at,
    )


def snapshot_view(bundle: SnapshotBundle) -> SnapshotView:
    """Return a full snapshot with source summaries."""

    snapshot = bundle.snapshot
    return SnapshotView(
        **_summary_fields(snapshot),
        etag=bundle.etag,
        criteria=[criterion_view(c) for c in snapshot.criteria],
        sources=[_source_summary(ref, bundle) for ref in snapshot.sources],
    )


def source_details(sources: Iterable[IntentSource]) -> list[SourceDetailView]:
    """Return current sources including their sanitized text."""

    return [
        SourceDetailView(
            kind=s.kind.value,
            source_id=s.source_id,
            raw_text_hash=s.raw_text_hash,
            length=len(s.text),
            truncated=s.truncated,
            suspicious_content_removed=s.suspicious_content_removed,
            fetched_at=s.fetched_at,
            text=s.text,
        )
        for s in sources
    ]


def report_view(report: BuildReport) -> BuildReportView:
    """Return the API view of a build report."""

    return BuildReportView(
        diagnostics=[
            DiagnosticView(code=d.code, source=d.source, detail=d.detail)
            for d in report.diagnostics
        ],
        carry_events=[
            CarryEventView(
                action=e.action,
                criterion_id=e.criterion_id,
                previous_id=e.previous_id,
                state=e.state.value,
            )
            for e in report.carry_events
        ],
        absent_sources=list(report.absent_sources),
    )


def build_result_view(outcome: BuildOutcome) -> BuildResultView:
    """Return the outcome of a rebuilding write."""

    return BuildResultView(
        snapshot=snapshot_view(outcome.bundle),
        created=outcome.created,
        report=report_view(outcome.report),
        sanitization=SanitizationView(
            removed=list(outcome.sanitization.removed),
            flagged=list(outcome.sanitization.flagged),
        ),
    )


def criterion_result_view(outcome: CriterionOutcome) -> CriterionResultView:
    """Return the outcome of a criterion write."""

    snapshot = outcome.bundle.snapshot
    return CriterionResultView(
        criterion=criterion_view(outcome.criterion),
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.version,
        etag=outcome.bundle.etag,
        created=outcome.created,
    )


def history_view(entry: CriterionHistoryEntry) -> CriterionChangeView:
    """Return one audit row."""

    change = entry.change
    return CriterionChangeView(
        snapshot_id=change.snapshot_id,
        snapshot_version=entry.snapshot_version,
        criterion_id=change.criterion_id,
        old_state=change.old_state.value,
        new_state=change.new_state.value,
        actor=change.actor,
        changed_at=change.changed_at,
        old_text=change.old_text,
        new_text=change.new_text,
        reason=change.reason,
    )


def diff_view(diff: SnapshotDiffResult) -> SnapshotDiffView:
    """Return the API view of a snapshot diff."""

    return SnapshotDiffView(**diff.to_dict())
