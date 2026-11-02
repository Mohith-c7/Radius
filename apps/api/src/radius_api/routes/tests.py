"""Test selection API routes."""

from dataclasses import replace
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import AnalysisListQuery
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import ImpactEvidence
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import success_response
from radius_shared.errors import ConflictError, NotFoundError, ValidationError
from radius_testing.application import TestingApplicationService
from radius_testing.domain.flakiness import FlakinessConfig

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_confidence_service,
    get_repository_service,
    get_testing_service,
)

router = APIRouter(prefix="/analyses/{analysis_id}/tests", tags=["tests"])


@router.get("")
def get_selected_tests(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    format: str | None = Query(None),
):
    """Return selected tests for an analysis."""

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    selection = service.get_selection(analysis_id)
    if format == "cli":
        return PlainTextResponse(selection.cli_args)
    return success_response(selection)


@router.post("/results")
async def ingest_test_results(
    analysis_id: UUID,
    request: Request,
    service: Annotated[TestingApplicationService, Depends(get_testing_service)],
    confidence_service: Annotated[ConfidenceApplicationService, Depends(get_confidence_service)],
    analysis_service: Annotated[AnalysisApplicationService, Depends(get_analysis_service)],
    repository_service: Annotated[RepositoryApplicationService, Depends(get_repository_service)],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    commit_sha: str | None = Query(
        None,
        description=(
            "Required. Commit the results were produced from; it must equal the "
            "analysed head commit, so results from another commit cannot verify it."
        ),
    ),
):
    """Ingest one CI test report and re-score the analysis.

    Evidence binding (any violation leaves the verdict untouched):

    * ``commit_sha`` is required (422) and must equal the analysed head (409).
    * The analysis must be completed (pending/running/failed/cancelled → 409)
      and must be the latest analysis
      of its pull request; results for a superseded head are stale (409).
    * A malformed or empty report is rejected (422) before anything is stored.

    Uploads accumulate: every distinct report for the analysis is kept, a
    failure in any upload is sticky, executed cases are unioned when matching
    selected tests, and replaying an identical body is idempotent. Selected
    test files absent from (or only skipped in) the results keep the verdict at
    ``insufficient_evidence``.
    """

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    if commit_sha is None or not commit_sha.strip():
        msg = (
            "commit_sha query parameter is required: pass the head commit the tests "
            "ran on (e.g. ?commit_sha=$GITHUB_SHA) so results are bound to a revision."
        )
        raise ValidationError(msg)
    status = str(getattr(analysis.status, "value", analysis.status))
    if status in _CLOSED_ANALYSIS_STATUSES:
        msg = (
            f"Analysis {analysis_id} is {status}; results cannot be ingested. "
            "Re-run the analysis and upload to the new analysis id."
        )
        raise ConflictError(msg)
    if status != "completed":
        # The worker writes the analysis' own confidence report when it
        # completes; accepting uploads earlier would let that report silently
        # drop CI evidence (including a sticky failure). Clients poll instead.
        msg = (
            f"Analysis {analysis_id} is still {status}; wait until it is completed "
            "before uploading results (radius_ci.py resolve polls for this)."
        )
        raise ConflictError(msg)
    if commit_sha.strip().lower() != analysis.commit_sha.lower():
        msg = (
            f"Results are for commit {commit_sha.strip()[:12]}, but analysis {analysis_id} "
            f"analysed {analysis.commit_sha[:12]}."
        )
        raise ConflictError(msg)
    _ensure_latest_for_pull_request(analysis_service, analysis)

    body = await _read_bounded_body(request)
    if service.count_result_uploads(analysis_id) >= MAX_UPLOADS_PER_ANALYSIS:
        msg = (
            f"Analysis {analysis_id} already has {MAX_UPLOADS_PER_ANALYSIS} result "
            "uploads; merge shard reports before uploading."
        )
        raise ConflictError(msg)
    ingestion = service.ingest_test_report(analysis_id, body, commit_sha)
    attribution = ingestion.selected_tests
    if attribution is None:
        missing: tuple[str, ...] = ()
        selected_count = 0
        executed: tuple[str, ...] = ()
        failed: tuple[str, ...] = ()
        skipped: tuple[str, ...] = ()
    else:
        missing = (*attribution.skipped, *attribution.not_reported)
        selected_count = attribution.selected_count
        executed = attribution.executed
        failed = attribution.failed
        skipped = attribution.skipped
    report = confidence_service.recalculate_from_test_results(
        analysis_id,
        ingestion,
        impact=_stored_impact(analysis_service, analysis_id, ingestion.total_tests),
        missing_selected_tests=missing,
        selected_test_files=selected_count,
        executed_selected_tests=executed,
        failed_selected_tests=failed,
        skipped_selected_tests=skipped,
        contradictory_tests=ingestion.contradictory_cases,
    )
    return success_response(
        replace(ingestion, verification_status=report.verification_status)
    )


_CLOSED_ANALYSIS_STATUSES = frozenset({"failed", "cancelled"})

# Every distinct upload is stored, so both the body size and the number of
# uploads per analysis are bounded to keep one client from filling storage.
MAX_REPORT_BYTES = 20 * 1024 * 1024
MAX_UPLOADS_PER_ANALYSIS = 256


async def _read_bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="Test report exceeds 20 MiB.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REPORT_BYTES:
            raise HTTPException(status_code=413, detail="Test report exceeds 20 MiB.")
        chunks.append(chunk)
    return b"".join(chunks)


def _ensure_latest_for_pull_request(
    analysis_service: AnalysisApplicationService,
    analysis,
) -> None:
    """Reject results for an analysis whose pull request head has moved on."""

    siblings = analysis_service.list_analyses(
        AnalysisListQuery(
            repository_id=analysis.repository_id,
            pull_request_id=analysis.pull_request_id,
        )
    )
    if not siblings:
        return
    latest = max(siblings, key=lambda item: item.created_at)
    if latest.id != analysis.id and latest.commit_sha.lower() != analysis.commit_sha.lower():
        msg = (
            f"Analysis {analysis.id} is stale: the pull request head moved to "
            f"{latest.commit_sha[:12]} (analysis {latest.id}). Upload results for the "
            "latest analysis instead."
        )
        raise ConflictError(msg)


def _stored_impact(
    analysis_service: AnalysisApplicationService,
    analysis_id: UUID,
    total_tests: int,
) -> ImpactEvidence | None:
    """Reuse the analysis' measured blast radius instead of a fabricated default."""

    try:
        blast = analysis_service.get_blast_radius(analysis_id)
    except NotFoundError:
        return None
    return ImpactEvidence(
        affected_files=blast.affected_files,
        affected_symbols=blast.affected_symbols,
        affected_modules=blast.affected_modules,
        affected_tests=blast.affected_tests or total_tests,
        dependency_depth=blast.dependency_depth,
    )


@router.get("/results")
def get_test_run_result(
    analysis_id: UUID,
    service: Annotated[TestingApplicationService, Depends(get_testing_service)],
    analysis_service: Annotated[AnalysisApplicationService, Depends(get_analysis_service)],
    repository_service: Annotated[RepositoryApplicationService, Depends(get_repository_service)],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return saved test run result for an analysis."""

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(service.get_run_result(analysis_id))


@router.get("/history", summary="Get test execution history")
def get_test_history(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
) -> Any:
    """Return test execution history for an analysis."""
    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    history = service.get_test_history(analysis_id)
    return success_response(history)


@router.get("/statistics", summary="Get test execution statistics")
def get_test_statistics(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
) -> Any:
    """Return test execution statistics for an analysis."""
    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    stats = service.get_test_statistics(analysis_id)
    return success_response(stats)


@router.get("/recent", summary="Get recent test executions across analyses")
def get_recent_executions(
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    repository_id: Annotated[UUID, Query(alias="repositoryId")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    """Return recent test executions of one repository in the caller's organization.

    Authenticated and tenant-scoped: an unscoped listing would expose every
    organization's test runs.
    """
    repository = repository_service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    executions = service.get_recent_executions(repository_id, limit)
    return success_response(executions)


@router.get("/flaky", summary="List quarantined (flaky) tests of the analysis' repository")
def get_flaky_tests(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    window: Annotated[int, Query(ge=2, le=200)] = 20,
    min_comparable: Annotated[int, Query(alias="minComparable", ge=1, le=200)] = 3,
    threshold: Annotated[float, Query(gt=0.0, le=1.0)] = 0.2,
) -> Any:
    """Return tests whose flakiness score (F-11) is at or above the threshold.

    Tenant-scoped through the analysis' repository. Deterministic for a given
    history; see ``docs/FLAKY_TESTS.md`` for the score definition.
    """
    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    config = FlakinessConfig(window=window, min_comparable=min_comparable, threshold=threshold)
    return success_response(service.list_flaky_tests(analysis.repository_id, config))
