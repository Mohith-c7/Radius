"""Test selection API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from radius_shared.dto import success_response
from radius_testing.application import TestingApplicationService

from radius_api.dependencies import get_testing_service

router = APIRouter(prefix="/analyses/{analysis_id}/tests", tags=["tests"])


@router.get("")
def get_selected_tests(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
):
    """Return selected tests for an analysis."""

    return success_response(service.get_selection(analysis_id))
