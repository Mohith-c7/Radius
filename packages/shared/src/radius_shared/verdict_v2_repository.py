"""Verdict v2 repository: bundle store and request outbox (VS-07).

Two implementations of one protocol: ``SqlVerdictV2Repository`` (tables
``verdict_v2`` and ``verdict_v2_requests``) and ``InMemoryVerdictV2Repository``
(API memory backend and tests). Every method that touches tenant data takes
``organization_id`` first and filters by it; another organization's row behaves
like a missing row. The only global operation is ``claim_request`` (the worker
outbox consumer), which returns the organization it found.

Idempotency
-----------
* ``save`` is keyed by ``(analysis_id, inputs_digest)``: identical inputs never
  write a second row. If the digest already exists but is not the newest
  revision (results went A -> B -> A) the old row is moved to a new top
  revision and its publish state is cleared so GitHub is refreshed.
* ``enqueue_request`` is keyed by ``analysis_id`` (replays collapse).

Outbox semantics
----------------
``enqueue_request`` upserts: ``requested_at = now``, ``available_at = now``,
claim cleared, ``attempts = 0``. ``claim_request`` takes the oldest row that is
available, not under a live claim (a claim older than ``lease_seconds`` is
reclaimable) and below ``max_attempts``, using ``FOR UPDATE SKIP LOCKED`` on
PostgreSQL. ``complete_request`` deletes the row only when the claim token and
``requested_at`` are unchanged since the claim, so a request that arrived while
the worker worked is kept. ``fail_request`` releases the claim, stores a
redacted error and delays the next attempt with exponential backoff.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radius_shared.database.verdict_v2 import VerdictV2RequestRow, VerdictV2Row
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_payload import STATES, StoredVerdict

MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_ERROR_CHARS = 2000
VALID_STATUS = ("ok", "error", "skipped")
VALID_MODES = ("shadow", "on")
REQUEST_REASONS = ("ci_results", "manual", "intent_changed")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$|^sha256:[0-9a-f]{64}$")

#: Backoff after a failed outbox attempt: 2, 4, 8 ... seconds, capped.
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 300.0


def backoff_seconds(attempts: int) -> float:
    """Delay before attempt ``attempts + 1`` (``attempts`` already made, >= 1)."""

    return min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)))


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    row_id: UUID
    revision: int
    created: bool  # a new row was written
    changed: bool  # the newest revision changed (new row or an old digest moved up)


@dataclass(frozen=True, slots=True)
class RequestClaim:
    request_id: UUID
    organization_id: UUID
    analysis_id: UUID
    reason: str
    requested_at: datetime
    claim_token: str
    attempts: int


@dataclass(frozen=True, slots=True)
class PendingRequest:
    analysis_id: UUID
    reason: str
    attempts: int
    claimed: bool
    last_error: str | None
    available_at: datetime


class VerdictV2Repository(Protocol):
    def save(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        bundle: dict[str, Any],
        *,
        mode: str,
        now: datetime | None = None,
    ) -> SaveOutcome: ...

    def latest(self, organization_id: UUID, analysis_id: UUID) -> StoredVerdict | None: ...

    def latest_stage_a(
        self, organization_id: UUID, analysis_id: UUID
    ) -> dict[str, Any] | None: ...

    def mark_published(
        self, organization_id: UUID, row_id: UUID, digest: str, *, now: datetime | None = None
    ) -> bool: ...

    def record_publish_error(
        self, organization_id: UUID, row_id: UUID, error: object
    ) -> bool: ...

    def enqueue_request(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        reason: str = "ci_results",
        *,
        now: datetime | None = None,
        delay_seconds: float = 0.0,
    ) -> None: ...

    def get_request(
        self, organization_id: UUID, analysis_id: UUID
    ) -> PendingRequest | None: ...

    def claim_request(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: float = 300.0,
        max_attempts: int = 5,
    ) -> RequestClaim | None: ...

    def complete_request(self, claim: RequestClaim) -> bool: ...

    def fail_request(
        self, claim: RequestClaim, error: object, *, now: datetime | None = None
    ) -> None: ...


# --------------------------------------------------------------------------
# bundle -> columns
# --------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


#: Stage A is what Stage B (CI results) is re-scored from, so it is never cut in pieces
#: (B-04). It is kept whole up to this size; above it the whole of Stage A is dropped and
#: ``stage_a_dropped`` is set, which makes a later recompute fail visibly (see
#: ``StageAUnavailableError``) instead of raising on a half-empty dict.
MAX_STAGE_A_BYTES = 8 * 1024 * 1024


class StageAUnavailableError(RuntimeError):
    """The newest stored bundle had its Stage A dropped by the size cap."""


def cap_bundle(bundle: dict[str, Any], max_bytes: int = MAX_BUNDLE_BYTES) -> dict[str, Any]:
    """Return ``bundle`` or a copy with heavy lists dropped and ``truncated`` set.

    Drop order: ``evidence_items``, ``stage_b`` (both are rebuilt from the uploads on a
    recompute), then ``stage_a`` as a whole and only when it alone exceeds
    ``MAX_STAGE_A_BYTES`` (``stage_a_dropped`` is set). Stage A is never cut in pieces.
    The verdict itself and the justification are never dropped.
    """

    if len(_canonical(bundle).encode("utf-8")) <= max_bytes:
        return bundle
    capped = copy.deepcopy(bundle)
    capped["truncated"] = True
    for key in ("evidence_items", "stage_b"):
        if key in capped:
            del capped[key]
            if len(_canonical(capped).encode("utf-8")) <= max_bytes:
                return capped
    stage_a = capped.get("stage_a")
    if isinstance(stage_a, dict) and len(_canonical(stage_a).encode("utf-8")) <= MAX_STAGE_A_BYTES:
        return capped  # re-scoring stays possible; only the stored size is above the soft cap
    if "stage_a" in capped:
        del capped["stage_a"]
        capped["stage_a_dropped"] = True
    return capped


@dataclass(frozen=True, slots=True)
class _Columns:
    head_sha: str
    inputs_digest: str
    status: str
    verdict: str | None
    pending: bool
    reason_code: str | None
    algo_version: str
    profile: str
    config_digest: str
    counts: dict[str, int]
    total: int
    uim: float | None
    intent_coverage: float | None
    justification: dict[str, Any] | None
    error_detail: str | None
    fallback: str | None


def extract_columns(bundle: dict[str, Any]) -> _Columns:
    """Validate a bundle and derive the summary columns (raises ``ValueError``)."""

    if not isinstance(bundle, dict):
        msg = "bundle must be a dict"
        raise ValueError(msg)  # noqa: TRY004
    head = bundle.get("head_sha")
    if not isinstance(head, str) or not _SHA.match(head):
        msg = "bundle.head_sha must be 40 lowercase hex characters"
        raise ValueError(msg)
    status = bundle.get("status", "ok")
    if status not in VALID_STATUS:
        msg = f"bundle.status must be one of {VALID_STATUS}"
        raise ValueError(msg)
    verdict_dict = bundle.get("verdict") if isinstance(bundle.get("verdict"), dict) else None
    if status == "ok" and verdict_dict is None:
        msg = "an ok bundle needs bundle.verdict"
        raise ValueError(msg)
    digest = bundle.get("inputs_digest") or (verdict_dict or {}).get("inputs_digest")
    if not isinstance(digest, str) or not _DIGEST.match(digest):
        msg = "bundle.inputs_digest must be a sha256 hex digest"
        raise ValueError(msg)
    digest = digest.removeprefix("sha256:")
    counts = dict.fromkeys(STATES, 0)
    total = 0
    uim = coverage = None
    verdict = None
    pending = False
    reason_code = bundle.get("reason_code") if isinstance(bundle.get("reason_code"), str) else None
    justification = None
    if status == "ok" and verdict_dict is not None:
        for criterion in verdict_dict.get("criteria") or []:
            total += 1
            state = criterion.get("state") if isinstance(criterion, dict) else None
            if state in counts:
                counts[state] += 1
        verdict = verdict_dict.get("verdict")
        pending = verdict_dict.get("pending") is True
        uim = verdict_dict.get("uim")
        coverage = verdict_dict.get("intent_coverage")
        justification = (
            verdict_dict.get("justification")
            if isinstance(verdict_dict.get("justification"), dict)
            else None
        )
        reasons = verdict_dict.get("reasons") or []
        if reason_code is None and reasons and isinstance(reasons[0], dict):
            reason_code = reasons[0].get("code")
    elif reason_code is None:
        reason_code = status
    detail = bundle.get("error_detail")
    return _Columns(
        head_sha=head,
        inputs_digest=digest,
        status=status,
        verdict=verdict if isinstance(verdict, str) else None,
        pending=pending,
        reason_code=(reason_code or None) and str(reason_code)[:48],
        algo_version=str(
            bundle.get("algo_version") or (verdict_dict or {}).get("algo_version") or ""
        )[:48],
        profile=str(bundle.get("profile") or (verdict_dict or {}).get("profile") or "")[:32],
        config_digest=str(
            bundle.get("config_digest") or (verdict_dict or {}).get("config_digest") or ""
        )[:80],
        counts=counts,
        total=total,
        uim=float(uim) if isinstance(uim, (int, float)) and not isinstance(uim, bool) else None,
        intent_coverage=float(coverage)
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool)
        else None,
        justification=justification,
        error_detail=redact_secrets(detail, max_length=MAX_ERROR_CHARS)
        if isinstance(detail, str) and detail
        else None,
        fallback=str(bundle["fallback"])[:8] if bundle.get("fallback") else None,
    )


def _with_revision(bundle: Any, revision: int) -> Any:
    """Copy of ``bundle`` whose ``verdict.revision`` is the row revision (B-18).

    The inputs digest never covers the revision, so this cannot change idempotency."""

    if not isinstance(bundle, dict) or not isinstance(bundle.get("verdict"), dict):
        return bundle
    return {**bundle, "verdict": {**bundle["verdict"], "revision": revision}}


def _check_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        msg = f"mode must be one of {VALID_MODES}, not {mode!r}"
        raise ValueError(msg)


def _check_reason(reason: str) -> None:
    if reason not in REQUEST_REASONS:
        msg = f"reason must be one of {REQUEST_REASONS}"
        raise ValueError(msg)


def _stage_a(stored: StoredVerdict | None) -> dict[str, Any] | None:
    if stored is None:
        return None
    stage_a = stored.bundle.get("stage_a")
    return copy.deepcopy(stage_a) if isinstance(stage_a, dict) and stage_a else None


def _to_stored(row: VerdictV2Row) -> StoredVerdict:
    return StoredVerdict(
        row_id=str(row.id),
        organization_id=str(row.organization_id),
        analysis_id=str(row.analysis_id),
        head_sha=row.head_sha,
        revision=row.revision,
        inputs_digest=row.inputs_digest,
        status=row.status,
        mode=row.mode,
        verdict=row.verdict,
        pending=row.pending,
        reason_code=row.reason_code,
        algo_version=row.algo_version,
        profile=row.profile,
        config_digest=row.config_digest,
        bundle=row.bundle,
        justification=row.justification,
        error_detail=row.error_detail,
        fallback=row.fallback,
        published_at=_aware(row.published_at),
        published_digest=row.published_digest,
        publish_error=row.publish_error,
        computed_at=_aware(row.computed_at) or _now(),
    )


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------


class SqlVerdictV2Repository:
    """SQLAlchemy implementation; the caller owns the transaction (commit)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        bundle: dict[str, Any],
        *,
        mode: str,
        now: datetime | None = None,
    ) -> SaveOutcome:
        _check_mode(mode)
        cols = extract_columns(bundle)
        capped = cap_bundle(bundle)
        now = now or _now()
        existing = self._by_digest(organization_id, analysis_id, cols.inputs_digest)
        top = self._max_revision(organization_id, analysis_id)
        if existing is not None:
            if existing.revision == top:
                if existing.mode != mode:  # B-18: shadow -> on must not keep the old tag
                    existing.mode = mode
                # "inputs last checked": a recompute that found nothing new still counts, so the
                # reconciler (B-09) does not queue the same analysis again
                existing.computed_at = now
                self._session.flush()
                return SaveOutcome(existing.id, existing.revision, False, False)
            existing.revision = top + 1  # same inputs as an older run: newest again
            existing.bundle = _with_revision(existing.bundle, existing.revision)
            existing.mode = mode
            existing.computed_at = now
            existing.published_at = None
            existing.published_digest = None
            existing.publish_error = None
            self._session.flush()
            return SaveOutcome(existing.id, existing.revision, False, True)
        row = VerdictV2Row(
            organization_id=organization_id,
            analysis_id=analysis_id,
            head_sha=cols.head_sha,
            revision=top + 1,
            inputs_digest=cols.inputs_digest,
            status=cols.status,
            mode=mode,
            verdict=cols.verdict,
            pending=cols.pending,
            reason_code=cols.reason_code,
            algo_version=cols.algo_version,
            profile=cols.profile,
            config_digest=cols.config_digest,
            criteria_total=cols.total,
            criteria_proven=cols.counts["proven"],
            criteria_weak=cols.counts["weak"],
            criteria_unevidenced=cols.counts["unevidenced"],
            criteria_contradicted=cols.counts["contradicted"],
            criteria_excluded=cols.counts["excluded"],
            uim=cols.uim,
            intent_coverage=cols.intent_coverage,
            bundle=_with_revision(capped, top + 1),
            justification=cols.justification,
            error_detail=cols.error_detail,
            fallback=cols.fallback,
            computed_at=now,
            created_at=now,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
        except IntegrityError:
            # A concurrent writer won the (analysis, digest) or revision race.
            winner = self._by_digest(organization_id, analysis_id, cols.inputs_digest)
            if winner is None:
                raise
            return SaveOutcome(winner.id, winner.revision, False, False)
        return SaveOutcome(row.id, row.revision, True, True)

    def latest(self, organization_id: UUID, analysis_id: UUID) -> StoredVerdict | None:
        row = self._session.scalars(
            select(VerdictV2Row)
            .where(
                VerdictV2Row.organization_id == organization_id,
                VerdictV2Row.analysis_id == analysis_id,
            )
            .order_by(VerdictV2Row.revision.desc())
            .limit(1)
        ).first()
        return _to_stored(row) if row is not None else None

    def latest_stage_a(
        self, organization_id: UUID, analysis_id: UUID
    ) -> dict[str, Any] | None:
        rows = self._session.scalars(
            select(VerdictV2Row)
            .where(
                VerdictV2Row.organization_id == organization_id,
                VerdictV2Row.analysis_id == analysis_id,
            )
            .order_by(VerdictV2Row.revision.desc())
        )
        for row in rows:
            stored = _to_stored(row)
            stage_a = _stage_a(stored)
            if stage_a is not None:
                return stage_a
            if stored.bundle.get("stage_a_dropped") is True:
                # the newest scored bundle lost its Stage A to the size cap: never fall
                # back to an older revision's (stale) intent, fail visibly instead (B-04)
                msg = "stage_a_dropped"
                raise StageAUnavailableError(msg)
        return None

    def stale_analyses(
        self,
        *,
        now: datetime | None = None,
        grace_seconds: float = 300.0,
        max_age_days: float = 7.0,
        limit: int = 20,
    ) -> list[tuple[UUID, UUID]]:
        """Analyses with a CI upload newer than their newest verdict and no request queued (B-09).

        The API enqueues a recompute when an upload arrives and swallows enqueue failures; this
        is the bounded sweep that catches those. Only recent uploads are considered
        (``max_age_days``), at most ``limit`` analyses are returned, oldest upload first."""

        from radius_shared.database.models import TestResultUpload

        now = now or _now()
        newest = (
            select(
                TestResultUpload.analysis_id.label("analysis_id"),
                func.max(TestResultUpload.created_at).label("last_upload"),
            )
            .where(TestResultUpload.created_at >= now - timedelta(days=max_age_days))
            .group_by(TestResultUpload.analysis_id)
            .subquery()
        )
        top = (
            select(
                VerdictV2Row.analysis_id.label("analysis_id"),
                func.max(VerdictV2Row.revision).label("rev"),
            )
            .group_by(VerdictV2Row.analysis_id)
            .subquery()
        )
        rows = self._session.execute(
            select(VerdictV2Row.organization_id, VerdictV2Row.analysis_id, VerdictV2Row.computed_at,
                   newest.c.last_upload)
            .join(top, (top.c.analysis_id == VerdictV2Row.analysis_id) & (top.c.rev == VerdictV2Row.revision))
            .join(newest, newest.c.analysis_id == VerdictV2Row.analysis_id)
            .order_by(newest.c.last_upload)
            .limit(limit * 5)
        ).all()
        out: list[tuple[UUID, UUID]] = []
        for org, analysis, computed_at, last_upload in rows:
            computed = _aware(computed_at) or now
            uploaded = _aware(last_upload) or now
            if uploaded <= computed + timedelta(seconds=grace_seconds):
                continue
            if self._request_row(org, analysis) is not None:
                continue
            out.append((org, analysis))
            if len(out) >= limit:
                break
        return out

    def mark_published(
        self, organization_id: UUID, row_id: UUID, digest: str, *, now: datetime | None = None
    ) -> bool:
        result = self._session.execute(
            update(VerdictV2Row)
            .where(
                VerdictV2Row.id == row_id,
                VerdictV2Row.organization_id == organization_id,
            )
            .values(published_at=now or _now(), published_digest=digest, publish_error=None)
        )
        return result.rowcount == 1

    def record_publish_error(
        self, organization_id: UUID, row_id: UUID, error: object
    ) -> bool:
        result = self._session.execute(
            update(VerdictV2Row)
            .where(
                VerdictV2Row.id == row_id,
                VerdictV2Row.organization_id == organization_id,
            )
            .values(publish_error=redact_secrets(error, max_length=MAX_ERROR_CHARS))
        )
        return result.rowcount == 1

    # -- outbox -----------------------------------------------------------

    def enqueue_request(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        reason: str = "ci_results",
        *,
        now: datetime | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        _check_reason(reason)
        now = now or _now()
        available = now + timedelta(seconds=max(0.0, delay_seconds))
        # B-16: a claim that is running is KEPT. Clearing it let a second worker start on the
        # same analysis while the first still ran (two comments). The worker that holds the
        # claim notices the newer ``requested_at`` in ``complete_request`` and releases it.
        values = {
            "reason": reason,
            "requested_at": now,
            "available_at": available,
            "attempts": 0,
            "last_error": None,
        }
        row = self._request_row(organization_id, analysis_id)
        if row is None:
            try:
                with self._session.begin_nested():
                    self._session.add(
                        VerdictV2RequestRow(
                            organization_id=organization_id,
                            analysis_id=analysis_id,
                            **values,
                        )
                    )
                return
            except IntegrityError:
                row = self._request_row(organization_id, analysis_id)
                if row is None:
                    raise
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()

    def get_request(
        self, organization_id: UUID, analysis_id: UUID
    ) -> PendingRequest | None:
        row = self._request_row(organization_id, analysis_id)
        if row is None:
            return None
        return PendingRequest(
            row.analysis_id,
            row.reason,
            row.attempts,
            row.claimed_at is not None,
            row.last_error,
            _aware(row.available_at) or _now(),
        )

    def claim_request(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: float = 300.0,
        max_attempts: int = 5,
    ) -> RequestClaim | None:
        now = now or _now()
        stale = now - timedelta(seconds=lease_seconds)
        query = (
            select(VerdictV2RequestRow)
            .where(
                VerdictV2RequestRow.available_at <= now,
                VerdictV2RequestRow.attempts < max_attempts,
                (VerdictV2RequestRow.claimed_at.is_(None))
                | (VerdictV2RequestRow.claimed_at < stale),
            )
            .order_by(VerdictV2RequestRow.requested_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = self._session.scalars(query).first()
        if row is None:
            return None
        token = str(uuid4())
        row.claimed_at = now
        row.claim_token = token
        row.attempts += 1
        self._session.flush()
        return RequestClaim(
            row.id,
            row.organization_id,
            row.analysis_id,
            row.reason,
            _aware(row.requested_at) or now,
            token,
            row.attempts,
        )

    def complete_request(self, claim: RequestClaim) -> bool:
        row = self._session.get(VerdictV2RequestRow, claim.request_id)
        if row is None or row.claim_token != claim.claim_token:
            return False
        if _aware(row.requested_at) != claim.requested_at:
            row.claimed_at = None  # re-requested while running: release it for the next pass
            row.claim_token = None
            self._session.flush()
            return False
        self._session.execute(
            delete(VerdictV2RequestRow).where(
                VerdictV2RequestRow.id == claim.request_id,
                VerdictV2RequestRow.claim_token == claim.claim_token,
            )
        )
        return True

    def fail_request(
        self, claim: RequestClaim, error: object, *, now: datetime | None = None
    ) -> None:
        row = self._session.get(VerdictV2RequestRow, claim.request_id)
        if row is None or row.claim_token != claim.claim_token:
            return
        now = now or _now()
        row.claimed_at = None
        row.claim_token = None
        row.last_error = redact_secrets(error, max_length=MAX_ERROR_CHARS)
        row.available_at = now + timedelta(seconds=backoff_seconds(claim.attempts))
        self._session.flush()

    # -- helpers ----------------------------------------------------------

    def _by_digest(
        self, organization_id: UUID, analysis_id: UUID, digest: str
    ) -> VerdictV2Row | None:
        return self._session.scalars(
            select(VerdictV2Row).where(
                VerdictV2Row.organization_id == organization_id,
                VerdictV2Row.analysis_id == analysis_id,
                VerdictV2Row.inputs_digest == digest,
            )
        ).first()

    def _max_revision(self, organization_id: UUID, analysis_id: UUID) -> int:
        top = self._session.scalar(
            select(func.max(VerdictV2Row.revision)).where(
                VerdictV2Row.organization_id == organization_id,
                VerdictV2Row.analysis_id == analysis_id,
            )
        )
        return int(top or 0)

    def _request_row(
        self, organization_id: UUID, analysis_id: UUID
    ) -> VerdictV2RequestRow | None:
        return self._session.scalars(
            select(VerdictV2RequestRow).where(
                VerdictV2RequestRow.organization_id == organization_id,
                VerdictV2RequestRow.analysis_id == analysis_id,
            )
        ).first()


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _MemRequest:
    request_id: UUID
    organization_id: UUID
    analysis_id: UUID
    reason: str
    requested_at: datetime
    available_at: datetime
    claimed_at: datetime | None = None
    claim_token: str | None = None
    attempts: int = 0
    last_error: str | None = None


class InMemoryVerdictV2Repository:
    """Process-local implementation with the same semantics (API memory backend, tests)."""

    def __init__(self) -> None:
        self._rows: list[StoredVerdict] = []
        self._requests: dict[UUID, _MemRequest] = {}

    def save(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        bundle: dict[str, Any],
        *,
        mode: str,
        now: datetime | None = None,
    ) -> SaveOutcome:
        _check_mode(mode)
        cols = extract_columns(bundle)
        capped = cap_bundle(bundle)
        now = now or _now()
        mine = [
            r
            for r in self._rows
            if r.organization_id == str(organization_id) and r.analysis_id == str(analysis_id)
        ]
        top = max((r.revision for r in mine), default=0)
        for index, row in enumerate(self._rows):
            if row in mine and row.inputs_digest == cols.inputs_digest:
                if row.revision == top:
                    self._rows[index] = replace(row, mode=mode, computed_at=now)
                    return SaveOutcome(UUID(row.row_id), row.revision, False, False)
                self._rows[index] = replace(
                    row,
                    revision=top + 1,
                    bundle=_with_revision(row.bundle, top + 1),
                    mode=mode,
                    computed_at=now,
                    published_at=None,
                    published_digest=None,
                    publish_error=None,
                )
                return SaveOutcome(UUID(row.row_id), top + 1, False, True)
        row_id = uuid4()
        self._rows.append(
            StoredVerdict(
                row_id=str(row_id),
                organization_id=str(organization_id),
                analysis_id=str(analysis_id),
                head_sha=cols.head_sha,
                revision=top + 1,
                inputs_digest=cols.inputs_digest,
                status=cols.status,
                mode=mode,
                verdict=cols.verdict,
                pending=cols.pending,
                reason_code=cols.reason_code,
                algo_version=cols.algo_version,
                profile=cols.profile,
                config_digest=cols.config_digest,
                bundle=_with_revision(copy.deepcopy(capped), top + 1),
                justification=copy.deepcopy(cols.justification),
                error_detail=cols.error_detail,
                fallback=cols.fallback,
                published_at=None,
                published_digest=None,
                publish_error=None,
                computed_at=now,
            )
        )
        return SaveOutcome(row_id, top + 1, True, True)

    def latest(self, organization_id: UUID, analysis_id: UUID) -> StoredVerdict | None:
        mine = [
            r
            for r in self._rows
            if r.organization_id == str(organization_id) and r.analysis_id == str(analysis_id)
        ]
        return max(mine, key=lambda r: r.revision, default=None)

    def latest_stage_a(
        self, organization_id: UUID, analysis_id: UUID
    ) -> dict[str, Any] | None:
        mine = sorted(
            (
                r
                for r in self._rows
                if r.organization_id == str(organization_id)
                and r.analysis_id == str(analysis_id)
            ),
            key=lambda r: r.revision,
            reverse=True,
        )
        for row in mine:
            stage_a = _stage_a(row)
            if stage_a is not None:
                return stage_a
            if row.bundle.get("stage_a_dropped") is True:
                msg = "stage_a_dropped"
                raise StageAUnavailableError(msg)
        return None

    def stale_analyses(self, **_: Any) -> list[tuple[UUID, UUID]]:
        return []  # uploads live in SQL only; the memory backend has nothing to sweep

    def _update(self, organization_id: UUID, row_id: UUID, **changes: Any) -> bool:
        for index, row in enumerate(self._rows):
            if row.row_id == str(row_id) and row.organization_id == str(organization_id):
                self._rows[index] = replace(row, **changes)
                return True
        return False

    def mark_published(
        self, organization_id: UUID, row_id: UUID, digest: str, *, now: datetime | None = None
    ) -> bool:
        return self._update(
            organization_id,
            row_id,
            published_at=now or _now(),
            published_digest=digest,
            publish_error=None,
        )

    def record_publish_error(
        self, organization_id: UUID, row_id: UUID, error: object
    ) -> bool:
        return self._update(
            organization_id,
            row_id,
            publish_error=redact_secrets(error, max_length=MAX_ERROR_CHARS),
        )

    def enqueue_request(
        self,
        organization_id: UUID,
        analysis_id: UUID,
        reason: str = "ci_results",
        *,
        now: datetime | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        _check_reason(reason)
        now = now or _now()
        for request in self._requests.values():
            if request.organization_id == organization_id and request.analysis_id == analysis_id:
                request.reason = reason
                request.requested_at = now
                request.available_at = now + timedelta(seconds=max(0.0, delay_seconds))
                request.attempts = 0  # B-16: a running claim is kept (see the SQL version)
                request.last_error = None
                return
        request_id = uuid4()
        self._requests[request_id] = _MemRequest(
            request_id,
            organization_id,
            analysis_id,
            reason,
            now,
            now + timedelta(seconds=max(0.0, delay_seconds)),
        )

    def get_request(
        self, organization_id: UUID, analysis_id: UUID
    ) -> PendingRequest | None:
        for r in self._requests.values():
            if r.organization_id == organization_id and r.analysis_id == analysis_id:
                return PendingRequest(
                    r.analysis_id,
                    r.reason,
                    r.attempts,
                    r.claimed_at is not None,
                    r.last_error,
                    r.available_at,
                )
        return None

    def claim_request(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: float = 300.0,
        max_attempts: int = 5,
    ) -> RequestClaim | None:
        now = now or _now()
        stale = now - timedelta(seconds=lease_seconds)
        candidates = sorted(
            (
                r
                for r in self._requests.values()
                if r.available_at <= now
                and r.attempts < max_attempts
                and (r.claimed_at is None or r.claimed_at < stale)
            ),
            key=lambda r: r.requested_at,
        )
        if not candidates:
            return None
        request = candidates[0]
        request.claimed_at = now
        request.claim_token = str(uuid4())
        request.attempts += 1
        return RequestClaim(
            request.request_id,
            request.organization_id,
            request.analysis_id,
            request.reason,
            request.requested_at,
            request.claim_token,
            request.attempts,
        )

    def complete_request(self, claim: RequestClaim) -> bool:
        request = self._requests.get(claim.request_id)
        if request is None or request.claim_token != claim.claim_token:
            return False
        if request.requested_at != claim.requested_at:
            request.claimed_at = None  # re-requested while running: release for the next pass
            request.claim_token = None
            return False
        del self._requests[claim.request_id]
        return True

    def fail_request(
        self, claim: RequestClaim, error: object, *, now: datetime | None = None
    ) -> None:
        request = self._requests.get(claim.request_id)
        if request is None or request.claim_token != claim.claim_token:
            return
        now = now or _now()
        request.claimed_at = None
        request.claim_token = None
        request.last_error = redact_secrets(error, max_length=MAX_ERROR_CHARS)
        request.available_at = now + timedelta(seconds=backoff_seconds(claim.attempts))
