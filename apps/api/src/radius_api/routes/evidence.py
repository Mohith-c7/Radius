"""Provenance-aware test evidence endpoints (disabled by default)."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from radius_analysis.application import AnalysisApplicationService
from radius_confidence.application import ConfidenceApplicationService
from radius_github import GitHubAppClient
from radius_repository.application import RepositoryApplicationService
from radius_shared.database import models as db_models
from radius_shared.dto import success_response
from radius_shared.errors import ConflictError, NotFoundError, ValidationError
from radius_shared.verdict_v2_repository import VerdictV2Repository
from radius_testing.application import TestingApplicationService
from radius_testing.provenance import validate_cases_for_slot

from radius_api.attestations import VERIFIER_VERSION, GitHubAttestationVerifier
from radius_api.config import ApiSettings
from radius_api.dependencies import (
    get_analysis_service,
    get_confidence_service,
    get_github_client,
    get_repository_service,
    get_testing_service,
    get_verdict_v2_repository,
)
from radius_api.provenance_auth import (
    EvidenceWorkflowIdentity,
    OidcAuthenticationError,
    verify_evidence_oidc,
)
from radius_api.routes.tests import (
    MAX_REPORT_BYTES,
    _ensure_latest_for_pull_request,
    _request_verdict_v2_republish,
    rescore_confidence,
)

router = APIRouter(prefix="/analyses/{analysis_id}/tests", tags=["test-evidence"])
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def _enabled(request: Request) -> None:
    if not _settings(request).trusted_evidence_enabled:
        raise NotFoundError("Trusted evidence is disabled.", code="disabled")


def _identity(request: Request, authorization: str | None) -> EvidenceWorkflowIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="GitHub Actions OIDC token required.")
    settings = _settings(request)
    try:
        return verify_evidence_oidc(
            authorization[7:],
            reusable_workflow_ref=settings.attestation_reusable_workflow,
            reusable_workflow_sha=settings.attestation_reusable_workflow_sha,
            caller_workflow_path=settings.attestation_caller_workflow_path,
            caller_workflow_sha=settings.attestation_caller_workflow_sha,
        )
    except OidcAuthenticationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/manifest")
def get_evidence_manifest(
    analysis_id: UUID,
    request: Request,
    service: Annotated[TestingApplicationService, Depends(get_testing_service)],
    analysis_service: Annotated[
        AnalysisApplicationService, Depends(get_analysis_service)
    ],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
    github: Annotated[GitHubAppClient, Depends(get_github_client)],
    authorization: Annotated[str | None, Header()] = None,
):
    """Return the persisted server-authoritative manifest for a PR analysis."""

    _enabled(request)
    identity = _identity(request, authorization)
    analysis, repository, pr, _, _, reason = _authoritative_context(
        request, analysis_id, identity, analysis_service, repository_service, github
    )
    if reason:
        if reason == "FORK_DIAGNOSTIC_ONLY":
            raise HTTPException(status_code=403, detail=reason)
        raise HTTPException(status_code=409, detail=reason)
    if pr is None:
        raise ConflictError("Manual analyses cannot create trusted PR manifests.")
    try:
        manifest = service.create_evidence_manifest(
            analysis_id,
            repository.id,
            analysis.commit_sha,
        )
    except ValueError as exc:
        raise ConflictError("The selected-test manifest is immutable.") from exc
    return success_response(manifest)


@router.post("/verified-results")
async def ingest_verified_test_report(
    analysis_id: UUID,
    request: Request,
    artifact: Annotated[UploadFile, File()],
    report_slot_id: Annotated[str, Form()],
    pull_request_number: Annotated[int, Form(gt=0)],
    service: Annotated[TestingApplicationService, Depends(get_testing_service)],
    confidence_service: Annotated[
        ConfidenceApplicationService, Depends(get_confidence_service)
    ],
    analysis_service: Annotated[
        AnalysisApplicationService, Depends(get_analysis_service)
    ],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
    github: Annotated[GitHubAppClient, Depends(get_github_client)],
    verdicts: Annotated[VerdictV2Repository, Depends(get_verdict_v2_repository)],
    authorization: Annotated[str | None, Header()] = None,
):
    """Verify and ingest one report slot; all failures remain non-trusted."""

    _enabled(request)
    identity = _identity(request, authorization)
    analysis, repository, pr, installation_id, run, reason = _authoritative_context(
        request, analysis_id, identity, analysis_service, repository_service, github,
        expected_pr_number=pull_request_number,
    )
    if reason == "FORK_DIAGNOSTIC_ONLY":
        return await _record_unverifiable(
            request,
            service,
            analysis_id,
            repository,
            analysis.commit_sha,
            report_slot_id,
            identity,
            artifact,
            reason,
            status="untrusted",
        )
    if reason in {
        "GITHUB_INSTALLATION_UNAVAILABLE",
        "GITHUB_VERIFICATION_UNAVAILABLE",
        "RUN_PR_UNVERIFIABLE",
        "RUN_CONTEXT_UNVERIFIABLE",
    }:
        return await _record_unverifiable(
            request,
            service,
            analysis_id,
            repository,
            analysis.commit_sha,
            report_slot_id,
            identity,
            artifact,
            reason,
            status="unverifiable",
        )
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    if pr is None or analysis.pull_request_id is None:
        raise ConflictError("Manual analyses cannot accept verified PR evidence.")
    if analysis.status != "completed":
        raise ConflictError("Analysis must be completed before evidence upload.")
    _ensure_latest_for_pull_request(analysis_service, analysis)
    if installation_id is None:
        return await _record_unverifiable(
            request, service, analysis_id, repository, analysis.commit_sha,
            report_slot_id, identity, artifact, "GITHUB_INSTALLATION_UNAVAILABLE",
        )

    body = await artifact.read(MAX_REPORT_BYTES + 1)
    if not body:
        raise ValidationError("Report artifact is empty.")
    if len(body) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="Test report exceeds 20 MiB.")
    manifest = service.create_evidence_manifest(
        analysis_id, repository.id, analysis.commit_sha
    )
    manifest_value = manifest["manifest"]
    if not any(slot.get("slot_id") == report_slot_id for slot in manifest_value["slots"]):
        return await _record_unverifiable(
            request, service, analysis_id, repository, analysis.commit_sha,
            report_slot_id, identity, artifact, "REPORT_SLOT_UNAUTHORIZED",
            manifest=manifest,
            body=body,
            status="rejected",
        )

    bundle_set: tuple[bytes, ...] = ()
    selected_bundle: bytes | None = None
    result = None
    body_digest = hashlib.sha256(body).hexdigest()
    try:
        app_token = github.create_installation_token(
            installation_id,
            permissions={"attestations": "read", "actions": "read", "pull_requests": "read"},
        )
        bundle_set = github.get_attestation_bundles(
            token=app_token.token,
            owner=repository.owner,
            repo=repository.name,
            subject_digest=f"sha256:{body_digest}",
        )
        settings = _settings(request)
        verifier = GitHubAttestationVerifier(
            executable=settings.attestation_verifier_path,
            trusted_root=settings.attestation_trusted_root_path,
        )
        expected = {
            "schema_version": 1,
            "analysis_id": str(analysis_id),
            "repository_id": str(repository.github_repository_id),
            "owner_id": str(identity.owner_id),
            "head_sha": analysis.commit_sha.lower(),
            "manifest_digest": manifest["digest_sha256"],
            "report_slot_id": report_slot_id,
            "run_id": identity.run_id,
            "run_attempt": identity.run_attempt,
            "event_name": identity.event_name,
            "caller_workflow_path": settings.attestation_caller_workflow_path,
            "caller_workflow_sha": identity.workflow_sha,
            "reusable_workflow_sha": identity.job_workflow_sha,
            "artifact_digest": f"sha256:{body_digest}",
        }
        selected_bundle = bundle_set[0] if bundle_set else None
        for bundle in bundle_set:
            candidate = verifier.verify(
                artifact=body,
                bundle=bundle,
                repository=f"{repository.owner}/{repository.name}",
                signer_workflow=settings.attestation_reusable_workflow.split("@", 1)[0],
                signer_digest=settings.attestation_reusable_workflow_sha,
                expected_predicate=expected,
                repository_id=repository.github_repository_id,
                owner_id=identity.owner_id,
            )
            if candidate.status == "verified_provenance":
                result = candidate
                selected_bundle = bundle
                break
            if result is None or candidate.status == "unverifiable":
                result = candidate
    except Exception:
        result = None

    if result is None:
        result = type("VerificationFailure", (), {
            "status": "unverifiable",
            "reason_code": "ATTESTATION_UNAVAILABLE" if not bundle_set else "VERIFIER_UNAVAILABLE",
            "details": {},
        })()
    digest = hashlib.sha256(body).hexdigest()
    attestation_digest = (
        hashlib.sha256(selected_bundle).hexdigest()
        if selected_bundle is not None
        else None
    )

    from radius_testing.infrastructure.result_matching import report_cases

    cases = report_cases(body)
    if result.status == "verified_provenance" and not validate_cases_for_slot(
        cases, manifest_value, report_slot_id
    ):
        result = type("VerificationFailure", (), {
            "status": "rejected", "reason_code": "TEST_IDENTITIES_MISMATCH", "details": {}
        })()
    try:
        ingestion = service.ingest_test_report(
            analysis_id,
            body,
            analysis.commit_sha,
            upload_metadata={
                "repository_id": repository.id,
                "report_slot_id": report_slot_id,
                "run_id": identity.run_id,
                "run_attempt": identity.run_attempt,
                "manifest_id": UUID(manifest["id"]),
                "manifest_digest": manifest["digest_sha256"],
                "attestation_digest": attestation_digest,
                "attestation_bundle": selected_bundle,
                "provenance_status": result.status,
                "provenance_reason_code": result.reason_code,
            },
        )
    except ValueError as exc:
        if str(exc) == "UPLOAD_LIMIT_REACHED":
            raise ConflictError("The analysis already has the maximum number of uploads.") from exc
        raise ConflictError("Evidence slot was already used by different bytes.") from exc
    upload_id = ingestion.upload.id
    service.append_provenance_event(
        upload_id,
        result.status,
        result.reason_code,
        VERIFIER_VERSION,
        _settings(request).attestation_policy_version,
        {
            **result.details,
            "run_id": identity.run_id,
            "run_attempt": identity.run_attempt,
            "manifest_digest": manifest["digest_sha256"],
            "artifact_digest": digest,
        },
        attestation_digest=attestation_digest,
        attestation_bundle=selected_bundle,
    )
    if result.status == "verified_provenance":
        rescore_confidence(confidence_service, analysis_service, analysis_id, ingestion)
        _request_verdict_v2_republish(
            request, verdicts, repository.organization_id, analysis_id
        )
    return success_response(ingestion)


async def _record_unverifiable(
    request: Request,
    service: TestingApplicationService,
    analysis_id: UUID,
    repository: Any,
    head_sha: str,
    report_slot_id: str,
    identity: EvidenceWorkflowIdentity,
    artifact: UploadFile,
    reason_code: str,
    *,
    manifest: dict | None = None,
    body: bytes | None = None,
    status: str = "unverifiable",
):
    """Retain a parseable diagnostic upload when cryptographic verification is unavailable."""

    body = body if body is not None else await artifact.read(MAX_REPORT_BYTES + 1)
    if not body or len(body) > MAX_REPORT_BYTES:
        raise ValidationError("Diagnostic report is empty or exceeds 20 MiB.")
    if manifest is None:
        try:
            manifest = service.create_evidence_manifest(
                analysis_id, repository.id, head_sha
            )
        except Exception:
            manifest = None
    metadata = {
        "repository_id": repository.id,
        "report_slot_id": report_slot_id,
        "run_id": identity.run_id,
        "run_attempt": identity.run_attempt,
        "provenance_status": status,
        "provenance_reason_code": reason_code,
    }
    if manifest:
        metadata.update(
            manifest_id=UUID(manifest["id"]),
            manifest_digest=manifest["digest_sha256"],
        )
    ingestion = service.ingest_test_report(
        analysis_id, body, head_sha, upload_metadata=metadata
    )
    service.append_provenance_event(
        ingestion.upload.id,
        status,
        reason_code,
        VERIFIER_VERSION,
        _settings(request).attestation_policy_version,
        {"run_id": identity.run_id, "run_attempt": identity.run_attempt},
    )
    return success_response(ingestion)


def _authoritative_context(
    request: Request,
    analysis_id: UUID,
    identity: EvidenceWorkflowIdentity,
    analysis_service: AnalysisApplicationService,
    repository_service: RepositoryApplicationService,
    github: GitHubAppClient,
    *,
    expected_pr_number: int | None = None,
):
    """Bind OIDC workflow, database tenant, GitHub run and PR to one analysis."""

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    if int(repository.github_repository_id) != identity.repository_id:
        raise HTTPException(status_code=403, detail="REPOSITORY_ID_MISMATCH")
    if analysis.pull_request_id is None:
        return analysis, repository, None, None, None, "MANUAL_ANALYSIS_DIAGNOSTIC_ONLY"
    settings = _settings(request)
    session_factory = request.app.state.container.session_factory
    if session_factory is None:
        return analysis, repository, None, None, None, "DATABASE_UNAVAILABLE"
    with session_factory() as session:
        pull = session.get(db_models.PullRequest, analysis.pull_request_id)
        repo_row = session.get(db_models.Repository, analysis.repository_id)
        org_row = session.get(db_models.Organization, repo_row.organization_id) if repo_row else None
        installation_id = getattr(org_row, "github_installation_id", None)
        if pull is None or repo_row is None:
            raise NotFoundError("Pull request or repository not found.")
        pr_number = pull.github_pr_number
    if expected_pr_number is not None and expected_pr_number != pr_number:
        raise HTTPException(status_code=403, detail="PULL_REQUEST_MISMATCH")
    if installation_id is None:
        return analysis, repository, None, None, None, "GITHUB_INSTALLATION_UNAVAILABLE"
    try:
        token = github.create_installation_token(
            installation_id,
            permissions={"actions": "read", "pull_requests": "read"},
        ).token
        repo_info = github.get_repository(
            token=token, owner=repository.owner, repo=repository.name
        )
        if int(repo_info.get("id", -1)) != identity.repository_id:
            raise HTTPException(status_code=403, detail="REPOSITORY_ID_MISMATCH")
        owner = repo_info.get("owner") or {}
        if int(owner.get("id", -1)) != identity.owner_id:
            raise HTTPException(status_code=403, detail="OWNER_ID_MISMATCH")
        run = github.get_workflow_run(
            token=token, owner=repository.owner, repo=repository.name, run_id=identity.run_id
        )
        run_repo = run.get("repository") or {}
        if (
            int(run_repo.get("id", -1)) != identity.repository_id
            or int(run.get("run_attempt", -1)) != identity.run_attempt
            or run.get("event") != identity.event_name
            or str(run.get("head_sha", "")).lower() != identity.sha
        ):
            raise HTTPException(status_code=403, detail="WORKFLOW_RUN_MISMATCH")
        configured_path = settings.attestation_caller_workflow_path
        run_path = str(run.get("path", ""))
        if configured_path and run_path.removeprefix(".github/workflows/") != configured_path.removeprefix(".github/workflows/"):
            raise HTTPException(status_code=403, detail="CALLER_WORKFLOW_MISMATCH")
        pr = github.get_pull_request(
            token=token,
            owner=repository.owner,
            repo=repository.name,
            number=pr_number,
        )
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        base_repo = base.get("repo") or {}
        if str(head.get("sha", "")).lower() != analysis.commit_sha.lower():
            raise HTTPException(status_code=409, detail="HEAD_SHA_MISMATCH")
        if int(base_repo.get("id", -1)) != identity.repository_id:
            raise HTTPException(status_code=403, detail="PULL_REQUEST_REPOSITORY_MISMATCH")
        if int((head.get("repo") or {}).get("id", -1)) != identity.repository_id:
            return analysis, repository, pr, installation_id, run, "FORK_DIAGNOSTIC_ONLY"
        run_prs = run.get("pull_requests") or []
        matching_run_pr = next(
            (item for item in run_prs if int(item.get("number", -1)) == pr_number),
            None,
        )
        if matching_run_pr is None:
            return analysis, repository, pr, installation_id, run, "RUN_PR_UNVERIFIABLE"
        if str((matching_run_pr.get("head") or {}).get("sha", "")).lower() != analysis.commit_sha.lower():
            raise HTTPException(status_code=409, detail="WORKFLOW_PR_HEAD_MISMATCH")
        if run.get("head_branch") is None:
            return analysis, repository, pr, installation_id, run, "RUN_CONTEXT_UNVERIFIABLE"
        if expected_pr_number is not None and expected_pr_number != pr_number:
            raise HTTPException(status_code=403, detail="PULL_REQUEST_MISMATCH")
        return analysis, repository, pr, installation_id, run, None
    except HTTPException:
        raise
    except Exception:
        return analysis, repository, None, installation_id, None, "GITHUB_VERIFICATION_UNAVAILABLE"
