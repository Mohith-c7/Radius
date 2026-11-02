"""Verdict v2 alpha API route (VS-09).

``GET /api/v1/analyses/{analysis_id}/verdict-v2`` serves the newest stored
verdict. ``/verdict`` is kept as an undocumented alias of the same handler (the
VS-00 contract name). Behaviour:

* flag ``off``: 404 with ``meta.reason = "disabled"`` (also hides the route from
  OpenAPI); nothing is read;
* unknown analysis or an analysis of another organization: 404
  ``ANALYSIS_NOT_FOUND`` (indistinguishable, no tenant probing);
* nothing computed yet: 404 with ``meta.reason = "not_computed"``;
* otherwise 200 with a strong ``ETag`` over the payload (``If-None-Match`` -> 304).

The v1 ``/analyses/{id}/confidence`` route and DTO are not touched; this route
only reads that report to copy a labelled ``v1`` block.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_confidence.application import ConfidenceApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import ApiResponse, error_response, success_response
from radius_shared.errors import NotFoundError
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_payload import build_payload
from radius_shared.verdict_v2_repository import VerdictV2Repository

from radius_api.auth import ApiPrincipal, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_confidence_service,
    get_repository_service,
    get_verdict_v2_repository,
)
from radius_api.schemas.verdict_v2 import VerdictV2Out

_ERRORS = {
    304: {"description": "Not modified (If-None-Match matched)."},
    403: {"description": "Missing or invalid organization credentials."},
    404: {
        "description": "Analysis not found (also for other organizations), or "
        "meta.reason is disabled (flag off) / not_computed (no verdict yet)."
    },
}


def _not_available(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=error_response(
            "NOT_FOUND",
            "Verdict v2 is not available for this analysis.",
            meta={"reason": reason},
        ).model_dump(),
    )


def _v1_block(
    confidence_service: ConfidenceApplicationService, analysis_id: UUID
) -> dict | None:
    try:
        report = confidence_service.get_report(analysis_id)
    except NotFoundError:
        return None
    return {
        "verification_status": report.verification_status,
        "confidence_score": report.confidence_score,
        "score_kind": report.score_kind,
        "risk_level": report.risk_level,
    }


def _etag(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return '"' + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32] + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    tags = [t.strip().removeprefix("W/") for t in if_none_match.split(",")]
    return "*" in tags or etag in tags


def get_verdict_v2(
    analysis_id: UUID,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    analysis_service: Annotated[AnalysisApplicationService, Depends(get_analysis_service)],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
    confidence_service: Annotated[
        ConfidenceApplicationService, Depends(get_confidence_service)
    ],
    verdicts: Annotated[VerdictV2Repository, Depends(get_verdict_v2_repository)],
    if_none_match: Annotated[str | None, Header()] = None,
):
    """Return the stored verdict v2 (per-criterion states, PR verdict, evidence)."""

    mode = getattr(request.app.state.settings, "verdict_v2_mode", VerdictV2Mode.OFF)
    if mode == VerdictV2Mode.OFF:
        return _not_available("disabled")
    missing = NotFoundError("Analysis not found.", code="ANALYSIS_NOT_FOUND")
    try:
        analysis = analysis_service.get_analysis(analysis_id)
        repository = repository_service.get_repository(analysis.repository_id)
    except NotFoundError:
        raise missing from None
    if repository.organization_id != principal.organization_id:
        raise missing
    stored = verdicts.latest(principal.organization_id, analysis_id)
    if stored is None:
        return _not_available("not_computed")
    payload = build_payload(stored, v1=_v1_block(confidence_service, analysis_id))
    etag = _etag(payload)
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    body = success_response(payload).model_dump(mode="json")
    return JSONResponse(content=body, headers=headers)


def create_router(*, documented: bool) -> APIRouter:
    """Build the router; OpenAPI lists the route only when ``documented``."""

    router = APIRouter(tags=["verdict-v2"])
    router.add_api_route(
        "/analyses/{analysis_id}/verdict-v2",
        get_verdict_v2,
        methods=["GET"],
        response_model=ApiResponse[VerdictV2Out],
        responses=_ERRORS,
        include_in_schema=documented,
        summary="Get the Verdict v2 alpha result of an analysis",
    )
    router.add_api_route(
        "/analyses/{analysis_id}/verdict",
        get_verdict_v2,
        methods=["GET"],
        include_in_schema=False,
    )
    return router


router = create_router(documented=False)
