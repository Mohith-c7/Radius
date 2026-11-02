"""IntentSnapshotService: fetched sources + extracted criteria -> versioned snapshots."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from radius_intent.application.diffing import diff_snapshot_pair
from radius_intent.application.merge import (
    Candidate,
    MergePlan,
    plan_merge,
    select_criteria,
    signature,
)
from radius_intent.application.models import (
    BuildReport,
    BuildResult,
    Diagnostic,
    SnapshotBuildConflictError,
    SnapshotDiffResult,
    SourceRequest,
)
from radius_intent.domain import (
    Criterion,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    SourceRef,
)
from radius_intent.interfaces import (
    CriterionExtractor,
    IntentRepository,
    IntentSourceFetcher,
    SnapshotConflictError,
    SnapshotNotFoundError,
)

#: Actor recorded on audit rows written by the service itself.
SYSTEM_ACTOR = "system:intent-snapshots"

_KIND_ORDER = {kind: index for index, kind in enumerate(IntentSourceKind)}
_MAX_DETAIL = 300


def _source_order(source: IntentSource) -> tuple[int, str]:
    return (_KIND_ORDER[source.kind], source.source_id)


def _ref_order(ref: SourceRef) -> tuple[int, str]:
    return (_KIND_ORDER[ref.kind], ref.source_id)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:_MAX_DETAIL]


class IntentSnapshotService:
    """Build, edit-carry-over, diff and read intent snapshots.

    Depends only on the domain and ports. ``now`` is always passed in; ids come
    from ``id_factory`` (default ``uuid4``, as the repository requires UUIDs).
    """

    def __init__(
        self,
        repository: IntentRepository,
        extractors: Sequence[CriterionExtractor],
        fetcher: IntentSourceFetcher | None = None,
        *,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
        max_attempts: int = 5,
    ) -> None:
        self._repo = repository
        self._extractors = tuple(extractors)
        self._fetcher = fetcher
        self._new_id = id_factory
        self._max_attempts = max(1, max_attempts)

    # -- reads -------------------------------------------------------------
    def latest(self, organization_id: UUID, analysis_id: str) -> IntentSnapshot | None:
        """Return the highest-version snapshot, or ``None``."""
        return self._repo.get_latest_snapshot(organization_id, analysis_id)

    def history(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSnapshot, ...]:
        """Return all snapshots, oldest version first."""
        return self._repo.list_snapshots(organization_id, analysis_id)

    def diff_snapshots(
        self, organization_id: UUID, older_id: str, newer_id: str
    ) -> SnapshotDiffResult:
        """Diff two stored snapshots (``SnapshotNotFoundError`` if either is missing)."""
        older = self._repo.get_snapshot(organization_id, older_id)
        newer = self._repo.get_snapshot(organization_id, newer_id)
        if older is None or newer is None:
            msg = "Snapshot not found."
            raise SnapshotNotFoundError(msg)
        return diff_snapshot_pair(older, newer)

    # -- writes ------------------------------------------------------------
    def build_snapshot(
        self,
        analysis_id: str,
        organization_id: UUID,
        sources: Sequence[IntentSource | SourceRequest],
        now: datetime,
    ) -> BuildResult:
        """Build the next snapshot (or return the existing one when unchanged)."""
        return self._build(analysis_id, organization_id, sources, now, "build")

    def on_sources_changed(
        self,
        analysis_id: str,
        organization_id: UUID,
        sources: Sequence[IntentSource | SourceRequest],
        now: datetime,
        *,
        trigger: str = "sources_changed",
    ) -> BuildResult:
        """Rebuild after pull_request.edited / issues.edited / new commits.

        ``trigger`` (for example ``"pull_request.edited"``) is written into the
        reason of carry-over audit rows.
        """
        return self._build(analysis_id, organization_id, sources, now, trigger)

    # -- internals ---------------------------------------------------------
    def _build(
        self,
        analysis_id: str,
        org: UUID,
        sources: Sequence[IntentSource | SourceRequest],
        now: datetime,
        trigger: str,
    ) -> BuildResult:
        if now.tzinfo is None:
            msg = "now must be timezone-aware."
            raise ValueError(msg)
        diagnostics: list[Diagnostic] = []
        absent: list[str] = []
        failed_keys: set[str] = set()
        failed_kinds: set[IntentSourceKind] = set()
        resolved = self._resolve(
            analysis_id, sources, diagnostics, absent, failed_kinds
        )
        candidates: list[Candidate] = []
        for source in resolved:
            candidates += self._extract(source, diagnostics, failed_keys)
        live, dedupe_diags = select_criteria(candidates)
        diagnostics += dedupe_diags
        refs = {s.ref.key: s.ref for s in resolved}

        for _ in range(self._max_attempts):
            latest = self._repo.get_latest_snapshot(org, analysis_id)
            plan = plan_merge(
                live,
                latest,
                refs,
                failed_keys=frozenset(failed_keys),
                failed_kinds=frozenset(failed_kinds),
                trigger=trigger,
            )
            final = plan.final
            snapshot_refs = self._snapshot_refs(resolved, final)
            report = BuildReport(tuple(diagnostics), plan.events, tuple(sorted(absent)))
            if latest is not None and self._same_content(latest, final, snapshot_refs):
                return BuildResult(latest, False, report)
            self._repo.save_sources(org, analysis_id, tuple(resolved))
            candidate = IntentSnapshot(
                snapshot_id=self._new_id(),
                analysis_id=analysis_id,
                version=1 if latest is None else latest.version + 1,
                created_at=now,
                criteria=plan.seeds,
                sources=snapshot_refs,
                parent_snapshot_id=None if latest is None else latest.snapshot_id,
            )
            try:
                saved = self._repo.save_snapshot(org, candidate)
            except SnapshotConflictError:
                continue  # another builder took this version: re-read and retry
            if saved.snapshot_id != candidate.snapshot_id:
                # An identical build won the race; it replays the carry-over.
                return BuildResult(saved, False, report)
            return BuildResult(self._replay(org, saved, plan, now), True, report)
        msg = "Could not allocate a snapshot version after repeated conflicts."
        raise SnapshotBuildConflictError(msg)

    def _replay(
        self, org: UUID, saved: IntentSnapshot, plan: MergePlan, now: datetime
    ) -> IntentSnapshot:
        for change in plan.changes:
            self._repo.record_state_change(
                org,
                saved.snapshot_id,
                change.criterion_id,
                change.new_state,
                actor=SYSTEM_ACTOR,
                changed_at=now,
                new_text=change.new_text,
                reason=change.reason,
            )
        final = self._repo.get_snapshot(org, saved.snapshot_id)
        if final is None:  # pragma: no cover - defensive
            raise SnapshotNotFoundError(saved.snapshot_id)
        return final

    @staticmethod
    def _snapshot_refs(
        resolved: list[IntentSource], criteria: tuple[Criterion, ...]
    ) -> tuple[SourceRef, ...]:
        """Current refs plus the old refs that retained criteria still cite."""
        refs = {s.ref.key: s.ref for s in resolved}
        for criterion in criteria:
            refs.setdefault(criterion.origin.source.key, criterion.origin.source)
        return tuple(sorted(refs.values(), key=_ref_order))

    @staticmethod
    def _same_content(
        latest: IntentSnapshot,
        final: tuple[Criterion, ...],
        refs: tuple[SourceRef, ...],
    ) -> bool:
        return latest.sources == refs and [signature(c) for c in latest.criteria] == [
            signature(c) for c in final
        ]

    def _resolve(
        self,
        analysis_id: str,
        sources: Sequence[IntentSource | SourceRequest],
        diagnostics: list[Diagnostic],
        absent: list[str],
        failed_kinds: set[IntentSourceKind],
    ) -> list[IntentSource]:
        found: dict[str, IntentSource] = {}
        for item in sources:
            source = item
            if isinstance(item, SourceRequest):
                label = f"{item.kind.value}:{item.reference}"
                if self._fetcher is None:
                    diagnostics.append(
                        Diagnostic("fetch_failed", "No fetcher configured.", label)
                    )
                    failed_kinds.add(item.kind)
                    continue
                try:
                    source = self._fetcher.fetch(analysis_id, item.kind, item.reference)
                except Exception as exc:  # noqa: BLE001 - isolate fetcher failures
                    diagnostics.append(
                        Diagnostic("fetch_failed", _describe(exc), label)
                    )
                    failed_kinds.add(item.kind)
                    continue
                if source is None:
                    diagnostics.append(
                        Diagnostic("source_absent", "Source not found.", label)
                    )
                    absent.append(label)
                    continue
            key = source.ref.key
            existing = found.get(key)
            if existing is not None:
                if existing.ref != source.ref:
                    diagnostics.append(
                        Diagnostic(
                            "duplicate_source",
                            "Conflicting versions of one source; kept the first.",
                            key,
                        )
                    )
                continue
            found[key] = source
        return sorted(found.values(), key=_source_order)

    def _extract(
        self,
        source: IntentSource,
        diagnostics: list[Diagnostic],
        failed_keys: set[str],
    ) -> list[Candidate]:
        out: list[Candidate] = []
        key = source.ref.key
        for index, extractor in enumerate(self._extractors):
            try:
                criteria = extractor.extract(source)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one extractor must not abort the rest
                name = type(extractor).__name__
                diagnostics.append(
                    Diagnostic("extractor_failed", f"{name}: {_describe(exc)}", key)
                )
                failed_keys.add(key)
                continue
            for criterion in criteria:
                if criterion.origin.source != source.ref or not criterion.span.within(
                    source.text
                ):
                    diagnostics.append(
                        Diagnostic(
                            "invalid_criterion",
                            f"{criterion.id} does not belong to this source text.",
                            key,
                        )
                    )
                    continue
                out.append(Candidate(criterion, index))
        return out


__all__ = ["SYSTEM_ACTOR", "IntentSnapshotService"]
