"""Advisory AI review route (DEC-041).

``GET /api/v1/analyses/{analysis_id}/ai-review`` returns the stored AI merge-readiness
review: AI-generated, advisory, and never part of the verdict, score or check result.

* unknown analysis, or an analysis of another organization: 404 ``ANALYSIS_NOT_FOUND``
  (indistinguishable, no tenant probing);
* nothing stored (feature off, no provider configured, or not generated yet): 404 with
  ``meta.reason = "not_generated"``;
* otherwise 200; ``status`` is ``ok`` (with the review) or ``unavailable`` (with
  ``reason_code``, for example ``provider_rate_limited`` or ``deadline``).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.ai_review import AiReviewRepository
from radius_shared.dto import ApiResponse, error_response, success_response
from radius_shared.errors import NotFoundError

from radius_api.auth import ApiPrincipal, get_api_principal
from radius_api.dependencies import (
    get_ai_review_repository,
    get_analysis_service,
    get_repository_service,
)
from radius_api.schemas.ai_review import AiReviewOut

router = APIRouter(tags=["ai-review"])


@router.get(
    "/analyses/{analysis_id}/ai-review",
    response_model=ApiResponse[AiReviewOut],
    responses={
        403: {"description": "Missing or invalid organization credentials."},
        404: {
            "description": "Analysis not found (also for other organizations), or "
            "meta.reason is not_generated (no AI review stored for this analysis)."
        },
    },
    summary="Get the advisory AI review of an analysis",
)
def get_ai_review(
    analysis_id: UUID,
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    analysis_service: Annotated[AnalysisApplicationService, Depends(get_analysis_service)],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
    reviews: Annotated[AiReviewRepository, Depends(get_ai_review_repository)],
):
    """Return the advisory, AI-generated merge-readiness review (never a verdict)."""

    missing = NotFoundError("Analysis not found.", code="ANALYSIS_NOT_FOUND")
    try:
        analysis = analysis_service.get_analysis(analysis_id)
        repository = repository_service.get_repository(analysis.repository_id)
    except NotFoundError:
        raise missing from None
    if repository.organization_id != principal.organization_id:
        raise missing
    stored = reviews.get(principal.organization_id, analysis_id)
    if stored is None:
        return JSONResponse(
            status_code=404,
            content=error_response(
                "NOT_FOUND",
                "No AI review is available for this analysis.",
                meta={"reason": "not_generated"},
            ).model_dump(),
        )
    payload = AiReviewOut.model_validate(stored.to_payload())
    return JSONResponse(
        content=success_response(payload.model_dump(mode="json")).model_dump(mode="json"),
        headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
    )
