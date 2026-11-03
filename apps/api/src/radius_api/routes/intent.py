"""Intent API routes (IN-08): criteria, snapshots, confirmation, sources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from radius_analysis.application import AnalysisApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import ApiResponse, success_response
from radius_shared.errors import NotFoundError, ValidationError
from radius_shared.verdict_v2_repository import VerdictV2Repository

from radius_api import intent_presenter as present
from radius_api.auth import ApiPrincipal, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_intent_service,
    get_repository_service,
    get_verdict_v2_repository,
)
from radius_api.intent_management import (
    ACTOR_LABEL_PATTERN,
    IntentManagementService,
)
from radius_api.schemas.intent import (
    AddCriterionRequest,
    BuildResultView,
    CriterionActionRequest,
    CriterionChangeView,
    CriterionResultView,
    SnapshotDiffView,
    SnapshotSummaryView,
    SnapshotView,
    SourceDetailView,
    SubmitIntentSourceRequest,
)
from radius_api.verdict_v2_trigger import request_verdict_v2_recompute

#: Largest accepted request body. Sources are capped at 64 KiB of text; the
#: margin covers JSON escaping.
MAX_BODY_BYTES = 256 * 1024

_ERRORS = {
    403: {"description": "Missing or invalid organization credentials."},
    404: {"description": "Analysis, snapshot or criterion not found (also for "
          "other organizations)."},
}
_WRITE_ERRORS = {
    **_ERRORS,
    409: {"description": "Stale If-Match, illegal state transition or conflict."},
    422: {"description": "Validation failed (size, YAML spec errors with line "
          "numbers, bad request)."},
}


def _limit_body(
    content_length: Annotated[int | None, Header()] = None,
) -> None:
    if content_length is not None and content_length > MAX_BODY_BYTES:
        msg = f"Request body exceeds {MAX_BODY_BYTES} bytes."
        raise ValidationError(msg, code="PAYLOAD_TOO_LARGE")


def _inert(response: Response) -> None:
    """Intent text is data: forbid MIME sniffing and caching of user text."""

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/analyses/{analysis_id}/intent",
    tags=["intent"],
    dependencies=[Depends(_inert)],
)


def get_intent_analysis_id(
    analysis_id: UUID,
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    analysis_service: Annotated[
        AnalysisApplicationService, Depends(get_analysis_service)
    ],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
) -> UUID:
    """Return the analysis id when it belongs to the caller's organization.

    Unknown analyses and analyses of other organizations are indistinguishable
    (both 404), so ids of other tenants cannot be probed.
    """

    missing = NotFoundError("Analysis not found.", code="ANALYSIS_NOT_FOUND")
    try:
        analysis = analysis_service.get_analysis(analysis_id)
        repository = repository_service.get_repository(analysis.repository_id)
    except NotFoundError:
        raise missing from None
    if repository.organization_id != principal.organization_id:
        raise missing
    return analysis_id


AnalysisId = Annotated[UUID, Depends(get_intent_analysis_id)]
Principal = Annotated[ApiPrincipal, Depends(get_api_principal)]
Service = Annotated[IntentManagementService, Depends(get_intent_service)]
IfMatch = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description="ETag from a previous read; a mismatch returns 409 INTENT_STALE.",
    ),
]


def _actor(principal: ApiPrincipal, label: str | None) -> str:
    """Audit actor: the authenticated organization, plus an optional user label."""

    base = f"org:{principal.organization_id}"
    if label is None:
        return base
    if not ACTOR_LABEL_PATTERN.match(label):
        msg = "X-Radius-Actor must match [A-Za-z0-9_.@:+-]{1,128}."
        raise ValidationError(msg, code="INTENT_ACTOR_INVALID")
    return f"{base}/{label}"


ActorLabel = Annotated[
    str | None,
    Header(
        alias="X-Radius-Actor",
        description="Optional label of the human acting (for example a username); "
        "recorded in the audit trail under the authenticated organization. "
        "Not verified by Radius.",
    ),
]


@router.get(
    "",
    response_model=ApiResponse[SnapshotView],
    responses=_ERRORS,
    summary="Latest intent snapshot",
)
def get_intent(
    analysis_id: AnalysisId,
    principal: Principal,
    service: Service,
    response: Response,
):
    """Return the latest snapshot: criteria with provenance, state and sources.

    404 `INTENT_NOT_FOUND` means no intent has been recorded yet.
    """

    bundle = service.latest(principal.organization_id, analysis_id)
    response.headers["ETag"] = bundle.etag
    return success_response(present.snapshot_view(bundle))


@router.get(
    "/snapshots",
    response_model=ApiResponse[list[SnapshotSummaryView]],
    responses=_ERRORS,
    summary="Snapshot history (newest first)",
)
def list_snapshots(
    analysis_id: AnalysisId,
    principal: Principal,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[
        int | None,
        Query(ge=1, description="Return versions below this one (meta.nextCursor)."),
    ] = None,
):
    """Return snapshot summaries, newest first, with cursor pagination."""

    page, next_cursor = service.history(
        principal.organization_id, analysis_id, limit=limit, before_version=cursor
    )
    return success_response(
        [present.snapshot_summary(s) for s in page],
        meta={"nextCursor": next_cursor, "limit": limit},
    )


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=ApiResponse[SnapshotView],
    responses=_ERRORS,
    summary="One snapshot",
)
def get_snapshot(
    analysis_id: AnalysisId,
    snapshot_id: UUID,
    principal: Principal,
    service: Service,
    response: Response,
):
    """Return one snapshot of the analysis."""

    bundle = service.snapshot(principal.organization_id, analysis_id, snapshot_id)
    response.headers["ETag"] = bundle.etag
    return success_response(present.snapshot_view(bundle))


@router.get(
    "/diff",
    response_model=ApiResponse[SnapshotDiffView],
    responses={**_ERRORS, 422: _WRITE_ERRORS[422]},
    summary="Diff two snapshots",
)
def diff_snapshots(
    analysis_id: AnalysisId,
    principal: Principal,
    service: Service,
    from_ref: Annotated[
        str, Query(alias="from", description="Snapshot id or version number.")
    ],
    to_ref: Annotated[
        str, Query(alias="to", description="Snapshot id or version number.")
    ],
):
    """Return what changed between two snapshots (added, removed, changed)."""

    diff = service.diff(principal.organization_id, analysis_id, from_ref, to_ref)
    return success_response(present.diff_view(diff))


@router.get(
    "/sources",
    response_model=ApiResponse[list[SourceDetailView]],
    responses=_ERRORS,
    summary="Current sources with sanitized text",
)
def list_sources(
    analysis_id: AnalysisId,
    principal: Principal,
    service: Service,
):
    """Return the sources the latest snapshot is built from, text included.

    Criterion spans index into this text. The text is untrusted: escape it
    before rendering.
    """

    return success_response(
        present.source_details(
            service.current_sources(principal.organization_id, analysis_id)
        )
    )


@router.post(
    "/sources",
    response_model=ApiResponse[BuildResultView],
    responses=_WRITE_ERRORS,
    dependencies=[Depends(_limit_body)],
    summary="Submit or replace an intent source",
)
def submit_source(
    analysis_id: AnalysisId,
    body: SubmitIntentSourceRequest,
    principal: Principal,
    service: Service,
    response: Response,
    if_match: IfMatch = None,
):
    """Store the text (agent prompt, `.radius/intent.yml`, PR body ...) and rebuild.

    The text is sanitized (hidden characters, comments and secrets removed),
    never executed, and replaces an earlier submission with the same kind and
    `sourceId`. A new snapshot version is created only when the criteria
    change; resubmitting identical text is a no-op (`created: false`).
    `.radius/intent.yml` errors return 422 with line numbers.
    """

    outcome = service.submit_source(
        principal.organization_id,
        analysis_id,
        kind=body.source_kind(),
        text=body.text,
        source_id=body.source_id,
        if_match=if_match,
    )
    response.status_code = (
        status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK
    )
    response.headers["ETag"] = outcome.bundle.etag
    return success_response(present.build_result_view(outcome))


@router.post(
    "/rebuild",
    response_model=ApiResponse[BuildResultView],
    responses=_WRITE_ERRORS,
    summary="Rebuild from stored sources",
)
def rebuild(
    analysis_id: AnalysisId,
    principal: Principal,
    service: Service,
    response: Response,
    if_match: IfMatch = None,
):
    """Re-run extraction over the stored sources. Idempotent.

    409 `INTENT_NO_SOURCES` when nothing has been submitted yet.
    """

    outcome = service.rebuild(
        principal.organization_id, analysis_id, if_match=if_match
    )
    response.headers["ETag"] = outcome.bundle.etag
    return success_response(present.build_result_view(outcome))


@router.patch(
    "/criteria/{criterion_id}",
    response_model=ApiResponse[CriterionResultView],
    responses=_WRITE_ERRORS,
    dependencies=[Depends(_limit_body)],
    summary="Confirm, reject, reopen or edit a criterion",
)
def update_criterion(
    analysis_id: AnalysisId,
    criterion_id: str,
    body: CriterionActionRequest,
    principal: Principal,
    service: Service,
    response: Response,
    request: Request,
    verdicts: Annotated[VerdictV2Repository, Depends(get_verdict_v2_repository)],
    if_match: IfMatch = None,
    actor_label: ActorLabel = None,
):
    """Apply a human decision through the domain state machine (audited).

    Illegal moves (for example confirming a rejected criterion) return 409
    `ILLEGAL_STATE_TRANSITION`. Weight edits are not supported yet. With
    Verdict v2 enabled, a successful change also asks the worker to refresh the
    stored verdict (debounced; a failure to ask never fails this call).
    """

    outcome = service.apply_action(
        principal.organization_id,
        analysis_id,
        criterion_id,
        body.action,
        text=body.text,
        reason=body.reason,
        actor=_actor(principal, actor_label),
        if_match=if_match,
    )
    request_verdict_v2_recompute(
        request, verdicts, principal.organization_id, analysis_id
    )
    response.headers["ETag"] = outcome.bundle.etag
    return success_response(present.criterion_result_view(outcome))


@router.post(
    "/criteria",
    response_model=ApiResponse[CriterionResultView],
    responses=_WRITE_ERRORS,
    dependencies=[Depends(_limit_body)],
    summary="Add a manual criterion",
)
def add_criterion(
    analysis_id: AnalysisId,
    body: AddCriterionRequest,
    principal: Principal,
    service: Service,
    response: Response,
    if_match: IfMatch = None,
    actor_label: ActorLabel = None,
):
    """Add a criterion authored by a human (`origin.method = human`).

    It is confirmed on creation and survives rebuilds. Adding the same text
    again is idempotent (200).
    """

    outcome = service.add_criterion(
        principal.organization_id,
        analysis_id,
        text=body.text,
        actor=_actor(principal, actor_label),
        reason=body.reason,
        if_match=if_match,
    )
    response.status_code = (
        status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK
    )
    response.headers["ETag"] = outcome.bundle.etag
    return success_response(present.criterion_result_view(outcome))


@router.get(
    "/criteria/{criterion_id}/history",
    response_model=ApiResponse[list[CriterionChangeView]],
    responses=_ERRORS,
    summary="Audit trail of a criterion",
)
def criterion_history(
    analysis_id: AnalysisId,
    criterion_id: str,
    principal: Principal,
    service: Service,
):
    """Return every state change of the criterion across snapshots, oldest first."""

    entries = service.criterion_history(
        principal.organization_id, analysis_id, criterion_id
    )
    return success_response([present.history_view(e) for e in entries])


__all__ = ["router"]
