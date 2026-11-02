"""Verdict v2 alpha API route skeleton (VS-00 stub; VS-09 owns the behaviour).

``GET /api/v1/analyses/{analysis_id}/verdict`` always answers 404 for now:
``meta.reason = "disabled"`` while ``RADIUS_FEATURE_VERDICT_V2`` is off and
``"not_computed"`` otherwise. It touches no store and changes no v1 route.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from radius_shared.dto import error_response
from radius_shared.verdict_v2_flag import VerdictV2Mode

from radius_api.auth import ApiPrincipal, get_api_principal

router = APIRouter(prefix="/analyses/{analysis_id}/verdict", tags=["verdict-v2"])


@router.get("", include_in_schema=False)
def get_verdict(
    analysis_id: UUID,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
) -> JSONResponse:
    """Return the stored v2 verdict (stub: always 404 with a machine reason)."""

    mode = getattr(request.app.state.settings, "verdict_v2_mode", VerdictV2Mode.OFF)
    reason = "disabled" if mode == VerdictV2Mode.OFF else "not_computed"
    return JSONResponse(
        status_code=404,
        content=error_response(
            "NOT_FOUND",
            "Verdict v2 is not available for this analysis.",
            meta={"reason": reason},
        ).model_dump(),
    )
