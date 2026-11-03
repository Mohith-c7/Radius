"""Coverage ingestion and retrieval API routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_confidence.application import CoverageApplicationService
from radius_confidence.dto.commands import (
    GetCoverageForAnalysisCommand,
    GetCoverageForArtifactCommand,
    GetTestsForSymbolCommand,
    IngestCoverageCommand,
)
from radius_confidence.interfaces.store import CoverageStore
from radius_repository.application import RepositoryApplicationService

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_coverage_service,
    get_coverage_store,
    get_repository_service,
)
from radius_api.tenancy import OwnedAnalysisId, resolve_owned_analysis

router = APIRouter(prefix="/coverage", tags=["coverage"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest_coverage(
    http_request: Request,
    service: CoverageApplicationService = Depends(get_coverage_service),
    store: CoverageStore = Depends(get_coverage_store),
    principal: ApiPrincipal = Depends(get_api_principal),
    analysis_service: AnalysisApplicationService = Depends(get_analysis_service),
    repository_service: RepositoryApplicationService = Depends(get_repository_service),
    analysis_id: UUID = Header(..., alias="X-Analysis-Id"),
    organization_id: UUID | None = Header(None, alias="X-Radius-Organization-Id"),
    payload: dict[str, Any] = None,
):
    """Ingest normalized coverage artifacts produced by CI.

    The analysis must belong to the caller's organization (unknown and foreign
    analyses are both 404). ``X-Radius-Organization-Id`` is optional and, when
    sent, must be the caller's own organization.
    """

    if organization_id is not None:
        ensure_same_organization(principal, organization_id)
    analysis_id_uuid = resolve_owned_analysis(
        analysis_id, principal, analysis_service, repository_service
    )

    files = payload.get("files", []) if payload else []
    symbols = payload.get("symbols", []) if payload else []

    service.ingest_coverage(
        IngestCoverageCommand(
            analysis_id=analysis_id_uuid,
            framework=payload.get("framework", "unknown") if payload else "unknown",
            coverage_percent=(
                float(payload["coverage_percent"])
                if payload and payload.get("coverage_percent") is not None
                else None
            ),
            files=files,
            symbols=symbols,
        )
    )

    summary = service.get_coverage_summary(
        GetCoverageForAnalysisCommand(analysis_id=analysis_id_uuid)
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "success": True,
            "data": {
                "analysis_id": str(analysis_id_uuid),
                "coverage_percent": summary["coverage_percent"] if summary else None,
                "artifact_count": summary["artifact_count"] if summary else 0,
            },
        },
    )


@router.get(
    "/analysis/{analysis_id}",
    response_model=None,
)
def get_coverage_for_analysis(
    analysis_id: OwnedAnalysisId,
    service: CoverageApplicationService = Depends(get_coverage_service),
    principal: ApiPrincipal = Depends(get_api_principal),
) -> JSONResponse:
    """Return aggregate coverage for one analysis."""

    summary = service.get_coverage_summary(
        GetCoverageForAnalysisCommand(analysis_id=str(analysis_id))
    )
    if summary is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "NOT_FOUND", "message": "Coverage not found."}},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": jsonable_encoder(summary)},
    )


@router.get(
    "/analysis/{analysis_id}/report",
    response_model=None,
)
def get_coverage_report(
    analysis_id: OwnedAnalysisId,
    service: CoverageApplicationService = Depends(get_coverage_service),
    principal: ApiPrincipal = Depends(get_api_principal),
) -> JSONResponse:
    """Return the full normalized coverage report for one analysis."""

    report = service.get_coverage_report(
        GetCoverageForAnalysisCommand(analysis_id=str(analysis_id))
    )
    if report is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "NOT_FOUND", "message": "Coverage report not found."}},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": jsonable_encoder(report)},
    )


@router.get(
    "/artifact",
    response_model=None,
)
def get_coverage_for_artifact(
    file_path: str,
    service: CoverageApplicationService = Depends(get_coverage_service),
    principal: ApiPrincipal = Depends(get_api_principal),
) -> JSONResponse:
    """Return coverage lines for a specific source file."""

    # The route accepts the file path as a query parameter for usability.
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": service.get_coverage_for_artifact(
                GetCoverageForArtifactCommand(analysis_id="00000000-0000-0000-0000-000000000000", path=file_path)
            )
        },
    )


@router.get(
    "/symbol",
    response_model=None,
)
def get_tests_for_symbol(
    file_path: str,
    symbol: str,
    service: CoverageApplicationService = Depends(get_coverage_service),
    principal: ApiPrincipal = Depends(get_api_principal),
) -> JSONResponse:
    """Return tests that executed a specific symbol."""

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": service.get_tests_for_symbol(
                GetTestsForSymbolCommand(
                    analysis_id="00000000-0000-0000-0000-000000000000",
                    file_path=file_path,
                    symbol=symbol,
                )
            )
        },
    )
