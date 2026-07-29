"""Confidence API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from radius_confidence.application import ConfidenceApplicationService
from radius_shared.dto import success_response

from radius_api.dependencies import get_confidence_service

router = APIRouter(prefix="/analyses/{analysis_id}/confidence", tags=["confidence"])


@router.get("")
def get_confidence(
    analysis_id: UUID,
    service: Annotated[
        ConfidenceApplicationService,
        Depends(get_confidence_service),
    ],
):
    """Return confidence report for an analysis."""

    return success_response(service.get_report(analysis_id))
