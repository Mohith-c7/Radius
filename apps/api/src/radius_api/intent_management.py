"""Intent management use cases behind the intent API (IN-08).

Thin orchestration over :class:`~radius_intent.application.IntentSnapshotService`
and the intent repository. All methods are scoped to one organization (the
repository filters by it) and raise :class:`~radius_shared.errors.RadiusError`
subclasses so the API error envelope applies. Intent text is untrusted: it is
sanitized before storage, size bounded, and never logged (hash and length
only).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from radius_intent.application import (
    BuildReport,
    IntentSnapshotService,
    SnapshotBuildConflictError,
    SnapshotDiffResult,
)
from radius_intent.domain import (
    Criterion,
    CriterionState,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    SourceRef,
)
from radius_intent.domain.errors import (
    IntentDomainError,
    InvalidStateTransitionError,
)
from radius_intent.domain.identity import criterion_id, normalize_text
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    Severity,
)
from radius_intent.infrastructure.manual import manual_source_id
from radius_intent.interfaces import (
    MAX_SOURCE_TEXT_BYTES,
    AnalysisNotFoundError,
    CriterionNotFoundError,
    CriterionStateChange,
    IntentPersistenceError,
    IntentRepository,
    SnapshotNotFoundError,
    SourceTooLargeError,
)
from radius_shared.errors import ConflictError, NotFoundError, ValidationError
from radius_shared.llm_guard import sanitize_untrusted
from radius_shared.logging import get_logger

LOGGER = get_logger(__name__)

#: Kinds a client may submit. ``comment`` is reserved for manual criteria.
SUBMITTABLE_KINDS = (
    IntentSourceKind.AGENT_PROMPT,
    IntentSourceKind.SPEC_FILE,
    IntentSourceKind.PR_BODY,
    IntentSourceKind.PR_TITLE,
    IntentSourceKind.ISSUE,
)
DEFAULT_SOURCE_IDS = {
    IntentSourceKind.AGENT_PROMPT: "agent-prompt",
    IntentSourceKind.SPEC_FILE: "intent.yml",
    IntentSourceKind.PR_BODY: "pr-body",
    IntentSourceKind.PR_TITLE: "pr-title",
    IntentSourceKind.ISSUE: "issue",
}
MAX_CRITERION_CHARS = 2000
MAX_REASON_CHARS = 500
MAX_SOURCES_PER_ANALYSIS = 50
MAX_SPEC_ERRORS_SHOWN = 10
SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
ACTOR_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.@:+\-]{1,128}$")

#: Sanitizer findings that mean hidden or non-visible content was removed.
_HIDDEN_CONTENT_CODES = frozenset(
    {
        "null_byte",
        "ansi_escape",
        "zero_width",
        "bidi_control",
        "unicode_tag",
        "control_char",
        "html_comment",
    }
)

Action = Literal["confirm", "reject", "edit", "reopen"]
_ACTION_STATE = {
    "confirm": CriterionState.CONFIRMED,
    "reject": CriterionState.REJECTED,
    "edit": CriterionState.EDITED,
    "reopen": CriterionState.PROPOSED,
}


@dataclass(frozen=True)
class SnapshotBundle:
    """A snapshot with the stored sources its refs point to."""

    snapshot: IntentSnapshot
    sources: dict[tuple[str, str, str], IntentSource]

    @property
    def etag(self) -> str:
        """Strong validator covering version, criteria text and states."""
        return snapshot_etag(self.snapshot)


@dataclass(frozen=True)
class Sanitization:
    """What the sanitizer removed (``removed``) or flagged (``flagged``)."""

    removed: tuple[str, ...] = ()
    flagged: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildOutcome:
    """Result of a write that (re)built a snapshot."""

    bundle: SnapshotBundle
    created: bool
    report: BuildReport
    sanitization: Sanitization = Sanitization()


@dataclass(frozen=True)
class CriterionOutcome:
    """Result of a criterion write."""

    bundle: SnapshotBundle
    criterion: Criterion
    created: bool = False


@dataclass(frozen=True)
class CriterionHistoryEntry:
    """One audit row with the snapshot version it was recorded in."""

    snapshot_version: int
    change: CriterionStateChange


def snapshot_etag(snapshot: IntentSnapshot) -> str:
    """Return a strong ETag that changes on any state, text or version change."""

    digest = hashlib.sha256()
    digest.update(snapshot.snapshot_id.encode())
    for criterion in snapshot.criteria:
        digest.update(
            f"\0{criterion.id}\0{criterion.state.value}\0{criterion.text}".encode()
        )
    return f'"{digest.hexdigest()[:24]}"'


def text_fingerprint(text: str) -> dict[str, object]:
    """Return log-safe facts about ``text`` (never the text itself)."""

    return {
        "text_length": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[
            :16
        ],
    }


class IntentManagementService:
    """Read and manage the intent of an analysis."""

    def __init__(
        self,
        repository: IntentRepository,
        snapshots: IntentSnapshotService,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repo = repository
        self._snapshots = snapshots
        self._clock = clock

    # -- reads -----------------------------------------------------------
    def latest(self, org: UUID, analysis_id: UUID) -> SnapshotBundle:
        """Return the latest snapshot or raise ``INTENT_NOT_FOUND``."""

        snapshot = self._snapshots.latest(org, str(analysis_id))
        if snapshot is None:
            msg = "No intent has been recorded for this analysis yet."
            raise NotFoundError(msg, code="INTENT_NOT_FOUND")
        return self._bundle(org, analysis_id, snapshot)

    def history(
        self, org: UUID, analysis_id: UUID, *, limit: int, before_version: int | None
    ) -> tuple[list[IntentSnapshot], int | None]:
        """Return snapshots newest first plus the cursor of the next page."""

        snapshots = sorted(
            self._snapshots.history(org, str(analysis_id)),
            key=lambda s: s.version,
            reverse=True,
        )
        if before_version is not None:
            snapshots = [s for s in snapshots if s.version < before_version]
        page = snapshots[:limit]
        next_cursor = page[-1].version if len(snapshots) > limit else None
        return page, next_cursor

    def snapshot(
        self, org: UUID, analysis_id: UUID, snapshot_id: UUID
    ) -> SnapshotBundle:
        """Return one snapshot of this analysis."""

        found = self._repo.get_snapshot(org, str(snapshot_id))
        if found is None or found.analysis_id != str(analysis_id):
            raise _snapshot_missing()
        return self._bundle(org, analysis_id, found)

    def diff(
        self, org: UUID, analysis_id: UUID, from_ref: str, to_ref: str
    ) -> SnapshotDiffResult:
        """Diff two snapshots given as version numbers or snapshot ids."""

        older = self._resolve_snapshot(org, analysis_id, from_ref)
        newer = self._resolve_snapshot(org, analysis_id, to_ref)
        return self._snapshots.diff_snapshots(
            org, older.snapshot_id, newer.snapshot_id
        )

    def current_sources(
        self, org: UUID, analysis_id: UUID
    ) -> tuple[IntentSource, ...]:
        """Return the stored sources the latest snapshot is built from."""

        latest = self._snapshots.latest(org, str(analysis_id))
        if latest is None:
            return ()
        stored = self._stored_by_ref(org, analysis_id)
        return tuple(
            stored[_ref_key(ref)] for ref in latest.sources if _ref_key(ref) in stored
        )

    def criterion_history(
        self, org: UUID, analysis_id: UUID, criterion_id_: str
    ) -> list[CriterionHistoryEntry]:
        """Return the audit trail of a criterion across all snapshots."""

        entries: list[CriterionHistoryEntry] = []
        known = False
        for snapshot in self._snapshots.history(org, str(analysis_id)):
            if snapshot.get(criterion_id_) is None:
                continue
            known = True
            entries.extend(
                CriterionHistoryEntry(snapshot.version, change)
                for change in self._repo.list_state_changes(
                    org, snapshot.snapshot_id, criterion_id_
                )
            )
        if not known:
            raise _criterion_missing()
        entries.sort(key=lambda e: (e.change.changed_at, e.snapshot_version))
        return entries

    # -- writes ----------------------------------------------------------
    def submit_source(
        self,
        org: UUID,
        analysis_id: UUID,
        *,
        kind: IntentSourceKind,
        text: str,
        source_id: str | None,
        if_match: str | None,
    ) -> BuildOutcome:
        """Store (or replace) one intent source and rebuild the snapshot."""

        self._check_precondition(org, analysis_id, if_match)
        if kind not in SUBMITTABLE_KINDS:
            msg = f"Source kind {kind.value} cannot be submitted through the API."
            raise ValidationError(msg, code="INTENT_SOURCE_KIND_NOT_ALLOWED")
        sid = DEFAULT_SOURCE_IDS[kind] if source_id is None else source_id
        if not SOURCE_ID_PATTERN.match(sid):
            msg = "sourceId must match [A-Za-z0-9_.:-]{1,64}."
            raise ValidationError(msg, code="INTENT_SOURCE_ID_INVALID")
        if len(text.encode("utf-8", "replace")) > MAX_SOURCE_TEXT_BYTES:
            msg = f"Source text exceeds {MAX_SOURCE_TEXT_BYTES} bytes."
            raise ValidationError(msg, code="INTENT_SOURCE_TOO_LARGE")
        now = self._clock()
        if kind is IntentSourceKind.SPEC_FILE:
            _validate_spec(sid, text, now)  # line numbers refer to what was sent
        cleaned = sanitize_untrusted(
            text, source_id=sid, kind=kind.value, max_length=MAX_SOURCE_TEXT_BYTES
        )
        body = cleaned.text
        if not body.strip():
            msg = "Source text is empty."
            raise ValidationError(msg, code="INTENT_SOURCE_EMPTY")
        removed = tuple(f.code for f in cleaned.findings if f.severity == "strip")
        flagged = tuple(f.code for f in cleaned.findings if f.severity == "flag")
        source = IntentSource(
            source_id=sid,
            kind=kind,
            text=body,
            raw_text_hash=cleaned.original_sha256,
            fetched_at=now,
            truncated=False,
            suspicious_content_removed=bool(_HIDDEN_CONTENT_CODES & set(removed)),
        )
        if kind is IntentSourceKind.SPEC_FILE and body != text:
            _validate_spec(sid, body, now)
        sources = self._merge_sources(org, analysis_id, source)
        outcome = self._build(
            org, analysis_id, sources, "api.sources_submitted", Sanitization(removed, flagged)
        )
        LOGGER.info(
            "Intent source submitted",
            extra={
                "analysis_id": str(analysis_id),
                "source_kind": kind.value,
                "source_id": sid,
                "snapshot_created": outcome.created,
                "snapshot_version": outcome.bundle.snapshot.version,
                **text_fingerprint(text),
            },
        )
        return outcome

    def rebuild(
        self, org: UUID, analysis_id: UUID, *, if_match: str | None
    ) -> BuildOutcome:
        """Re-run extraction from the stored sources (idempotent)."""

        self._check_precondition(org, analysis_id, if_match)
        sources = self.current_sources(org, analysis_id)
        if not sources:
            msg = "No intent sources are stored for this analysis."
            raise ConflictError(msg, code="INTENT_NO_SOURCES")
        outcome = self._build(org, analysis_id, list(sources), "api.rebuild")
        LOGGER.info(
            "Intent rebuilt",
            extra={
                "analysis_id": str(analysis_id),
                "snapshot_created": outcome.created,
                "snapshot_version": outcome.bundle.snapshot.version,
            },
        )
        return outcome

    def add_criterion(
        self,
        org: UUID,
        analysis_id: UUID,
        *,
        text: str,
        actor: str,
        reason: str | None,
        if_match: str | None,
    ) -> CriterionOutcome:
        """Add a human-authored criterion and confirm it."""

        latest = self._check_precondition(org, analysis_id, if_match)
        statement = _clean_statement(text, "text")
        reason = _clean_reason(reason)
        normalized = normalize_text(statement)
        if latest is not None:
            for existing in latest.criteria:
                if (
                    existing.normalized_text == normalized
                    and existing.origin.source.kind is IntentSourceKind.SPEC_FILE
                ):
                    msg = (
                        "An identical criterion is already defined by the spec "
                        f"file ({existing.id})."
                    )
                    raise ConflictError(msg, code="DUPLICATE_CRITERION")
        now = self._clock()
        source = IntentSource.from_text(
            manual_source_id(statement),
            IntentSourceKind.COMMENT,
            statement,
            now,
        )
        sources = self._merge_sources(org, analysis_id, source)
        outcome = self._build(org, analysis_id, sources, "api.manual_criterion")
        snapshot = outcome.bundle.snapshot
        new_id = criterion_id(normalized, source.ref.key)
        criterion = snapshot.get(new_id)
        if criterion is None:  # pragma: no cover - guarded by the checks above
            msg = "The criterion was merged into an equivalent one."
            raise ConflictError(msg, code="DUPLICATE_CRITERION")
        created = latest is None or latest.get(new_id) is None
        if criterion.state is CriterionState.PROPOSED:
            criterion = self._record(
                org,
                snapshot.snapshot_id,
                new_id,
                CriterionState.CONFIRMED,
                actor=actor,
                new_text=None,
                reason=reason or "added manually",
            )
        LOGGER.info(
            "Intent criterion added",
            extra={
                "analysis_id": str(analysis_id),
                "criterion_id": new_id,
                "criterion_created": created,
                **text_fingerprint(statement),
            },
        )
        return CriterionOutcome(
            self.latest(org, analysis_id), criterion, created=created
        )

    def apply_action(
        self,
        org: UUID,
        analysis_id: UUID,
        criterion_id_: str,
        action: Action,
        *,
        text: str | None,
        reason: str | None,
        actor: str,
        if_match: str | None,
    ) -> CriterionOutcome:
        """Confirm, reject, reopen or edit one criterion of the latest snapshot."""

        latest = self._check_precondition(org, analysis_id, if_match)
        if latest is None:
            raise NotFoundError(
                "No intent has been recorded for this analysis yet.",
                code="INTENT_NOT_FOUND",
            )
        current = latest.get(criterion_id_)
        if current is None:
            raise _criterion_missing()
        new_text = _clean_statement(text, "text") if action == "edit" else None
        updated = self._record(
            org,
            latest.snapshot_id,
            criterion_id_,
            _ACTION_STATE[action],
            actor=actor,
            new_text=new_text,
            reason=_clean_reason(reason),
        )
        LOGGER.info(
            "Intent criterion updated",
            extra={
                "analysis_id": str(analysis_id),
                "criterion_id": criterion_id_,
                "action": action,
                "state_before": current.state.value,
                "state_after": updated.state.value,
                **(text_fingerprint(new_text) if new_text is not None else {}),
            },
        )
        return CriterionOutcome(self.latest(org, analysis_id), updated)

    # -- internals -------------------------------------------------------
    def _bundle(
        self, org: UUID, analysis_id: UUID, snapshot: IntentSnapshot
    ) -> SnapshotBundle:
        return SnapshotBundle(snapshot, self._stored_by_ref(org, analysis_id))

    def _stored_by_ref(
        self, org: UUID, analysis_id: UUID
    ) -> dict[tuple[str, str, str], IntentSource]:
        return {
            (s.kind.value, s.source_id, s.raw_text_hash): s
            for s in self._repo.get_sources(org, str(analysis_id))
        }

    def _resolve_snapshot(
        self, org: UUID, analysis_id: UUID, ref: str
    ) -> IntentSnapshot:
        snapshots = self._snapshots.history(org, str(analysis_id))
        if ref.isdecimal():
            for snapshot in snapshots:
                if snapshot.version == int(ref):
                    return snapshot
        else:
            try:
                wanted = str(UUID(ref))
            except ValueError:
                msg = "Snapshot references must be a version number or a snapshot id."
                raise ValidationError(msg, code="INTENT_SNAPSHOT_REF_INVALID") from None
            for snapshot in snapshots:
                if snapshot.snapshot_id == wanted:
                    return snapshot
        raise _snapshot_missing()

    def _check_precondition(
        self, org: UUID, analysis_id: UUID, if_match: str | None
    ) -> IntentSnapshot | None:
        latest = self._snapshots.latest(org, str(analysis_id))
        if if_match is not None and not _etag_matches(if_match, latest):
            msg = (
                "The intent changed since it was read (If-Match does not match "
                "the current ETag). Re-read it and retry."
            )
            raise ConflictError(msg, code="INTENT_STALE")
        return latest

    def _merge_sources(
        self, org: UUID, analysis_id: UUID, new: IntentSource
    ) -> list[IntentSource]:
        merged = {s.ref.key: s for s in self.current_sources(org, analysis_id)}
        merged[new.ref.key] = new
        if len(merged) > MAX_SOURCES_PER_ANALYSIS:
            msg = f"At most {MAX_SOURCES_PER_ANALYSIS} intent sources per analysis."
            raise ValidationError(msg, code="INTENT_TOO_MANY_SOURCES")
        return list(merged.values())

    def _build(
        self,
        org: UUID,
        analysis_id: UUID,
        sources: Sequence[IntentSource],
        trigger: str,
        sanitization: Sanitization = Sanitization(),
    ) -> BuildOutcome:
        try:
            result = self._snapshots.on_sources_changed(
                str(analysis_id), org, sources, self._clock(), trigger=trigger
            )
        except SnapshotBuildConflictError as exc:
            raise ConflictError(str(exc), code="INTENT_BUILD_CONFLICT") from exc
        except IntentPersistenceError as exc:
            raise _translate(exc) from exc
        return BuildOutcome(
            self._bundle(org, analysis_id, result.snapshot),
            result.created,
            result.report,
            sanitization,
        )

    def _record(
        self,
        org: UUID,
        snapshot_id: str,
        criterion_id_: str,
        state: CriterionState,
        *,
        actor: str,
        new_text: str | None,
        reason: str | None,
    ) -> Criterion:
        try:
            return self._repo.record_state_change(
                org,
                snapshot_id,
                criterion_id_,
                state,
                actor=actor,
                changed_at=self._clock(),
                new_text=new_text,
                reason=reason,
            )
        except InvalidStateTransitionError as exc:
            raise ConflictError(
                str(exc), code="ILLEGAL_STATE_TRANSITION"
            ) from exc
        except IntentDomainError as exc:
            raise ValidationError(str(exc), code="INTENT_INVALID") from exc
        except IntentPersistenceError as exc:
            raise _translate(exc) from exc


def _ref_key(ref: SourceRef) -> tuple[str, str, str]:
    return (ref.kind.value, ref.source_id, ref.raw_text_hash)


def _snapshot_missing() -> NotFoundError:
    return NotFoundError("Intent snapshot not found.", code="INTENT_SNAPSHOT_NOT_FOUND")


def _criterion_missing() -> NotFoundError:
    return NotFoundError(
        "Criterion not found in this analysis.", code="CRITERION_NOT_FOUND"
    )


def _translate(exc: IntentPersistenceError) -> Exception:
    if isinstance(exc, AnalysisNotFoundError):
        return NotFoundError("Analysis not found.", code="ANALYSIS_NOT_FOUND")
    if isinstance(exc, SnapshotNotFoundError):
        return _snapshot_missing()
    if isinstance(exc, CriterionNotFoundError):
        return _criterion_missing()
    if isinstance(exc, SourceTooLargeError):
        return ValidationError(str(exc), code="INTENT_SOURCE_TOO_LARGE")
    if isinstance(exc, ValueError):
        return ValidationError(str(exc), code="INTENT_INVALID")
    return ConflictError(str(exc), code="INTENT_CONFLICT")


def _etag_matches(header: str, latest: IntentSnapshot | None) -> bool:
    if latest is None:
        return False
    current = snapshot_etag(latest)
    for token in header.split(","):
        candidate = token.strip()
        candidate = candidate.removeprefix("W/")
        if candidate in ("*", current):
            return True
    return False


def _clean_statement(text: str | None, field: str) -> str:
    cleaned = sanitize_untrusted(
        text or "", source_id="criterion", kind="criterion_text", max_length=10_000
    ).text
    statement = " ".join(cleaned.split())
    if not statement:
        msg = f"{field} must not be empty."
        raise ValidationError(msg, code="INTENT_TEXT_EMPTY")
    if len(statement) > MAX_CRITERION_CHARS:
        msg = f"{field} must be at most {MAX_CRITERION_CHARS} characters."
        raise ValidationError(msg, code="INTENT_TEXT_TOO_LONG")
    return statement


def _clean_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    cleaned = " ".join(
        sanitize_untrusted(
            reason, source_id="reason", kind="reason", max_length=MAX_REASON_CHARS * 4
        ).text.split()
    )
    return cleaned[:MAX_REASON_CHARS] or None


def _validate_spec(source_id: str, text: str, now: datetime) -> None:
    """Reject a ``.radius/intent.yml`` with syntax or schema errors (line numbers)."""

    probe = IntentSource.from_text(source_id, IntentSourceKind.SPEC_FILE, text, now)
    report = DeterministicCriterionExtractor().extract_report(probe)
    errors = [d for d in report.diagnostics if d.severity is Severity.ERROR]
    if not errors:
        return
    shown = [
        (f"line {d.line}: " if d.line else "") + f"{d.message} [{d.code}]"
        for d in errors[:MAX_SPEC_ERRORS_SHOWN]
    ]
    more = len(errors) - len(shown)
    suffix = f" (+{more} more)" if more > 0 else ""
    msg = "Invalid .radius/intent.yml: " + "; ".join(shown) + suffix
    raise ValidationError(msg, code="INTENT_SPEC_INVALID")
