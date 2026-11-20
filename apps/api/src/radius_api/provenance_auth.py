"""GitHub Actions OIDC authentication for the test-evidence API surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
EVIDENCE_AUDIENCE = "api://radius/evidence-upload"
_JWKS = jwt.PyJWKClient(f"{GITHUB_OIDC_ISSUER}/.well-known/jwks", cache_keys=True)


class OidcAuthenticationError(ValueError):
    """OIDC credentials are invalid, incomplete, or outside the approved policy."""


@dataclass(frozen=True, slots=True)
class EvidenceWorkflowIdentity:
    repository_id: int
    owner_id: int
    run_id: str
    run_attempt: int
    event_name: str
    sha: str
    workflow_ref: str
    workflow_sha: str
    job_workflow_ref: str
    job_workflow_sha: str
    pull_request_number: int | None


def verify_evidence_oidc(
    bearer: str,
    *,
    reusable_workflow_ref: str,
    reusable_workflow_sha: str,
    caller_workflow_path: str,
    caller_workflow_sha: str,
) -> EvidenceWorkflowIdentity:
    """Verify an Actions token and enforce the configured immutable reusable job."""

    if not all((reusable_workflow_ref, reusable_workflow_sha, caller_workflow_path, caller_workflow_sha)):
        raise OidcAuthenticationError("Evidence workflow policy is not configured.")
    try:
        key = _JWKS.get_signing_key_from_jwt(bearer).key
        claims: dict[str, Any] = jwt.decode(
            bearer,
            key,
            algorithms=["RS256"],
            issuer=GITHUB_OIDC_ISSUER,
            audience=EVIDENCE_AUDIENCE,
            options={
                "require": [
                    "exp",
                    "iat",
                    "repository_id",
                    "repository_owner_id",
                    "run_id",
                    "run_attempt",
                    "event_name",
                    "workflow_ref",
                    "workflow_sha",
                    "job_workflow_ref",
                    "job_workflow_sha",
                    "sha",
                ]
            },
        )
    except Exception as exc:
        raise OidcAuthenticationError("GitHub Actions OIDC token is invalid.") from exc

    if claims.get("job_workflow_ref") != reusable_workflow_ref:
        raise OidcAuthenticationError("Reusable workflow identity is not approved.")
    if str(claims.get("job_workflow_sha", "")).lower() != reusable_workflow_sha.lower():
        raise OidcAuthenticationError("Reusable workflow revision is not approved.")
    if not str(claims.get("workflow_sha", "")).strip():
        raise OidcAuthenticationError("Caller workflow revision claim is missing.")
    caller_ref_path = str(claims["workflow_ref"]).split("@", 1)[0]
    caller_path = "/".join(caller_ref_path.split("/")[2:])
    if caller_path != caller_workflow_path:
        raise OidcAuthenticationError("Caller workflow path is not approved.")
    if str(claims["workflow_sha"]).lower() != caller_workflow_sha.lower():
        raise OidcAuthenticationError("Caller workflow revision is not approved.")
    try:
        repo_id = int(claims["repository_id"])
        owner_id = int(claims["repository_owner_id"])
        run_id = str(claims["run_id"])
        attempt = int(claims["run_attempt"])
    except (TypeError, ValueError, KeyError) as exc:
        raise OidcAuthenticationError("Required GitHub identity claims are invalid.") from exc
    if repo_id < 1 or owner_id < 1 or not run_id.isdigit() or attempt < 1:
        raise OidcAuthenticationError("Required GitHub identity claims are invalid.")
    event = str(claims["event_name"])
    if event != "pull_request":
        raise OidcAuthenticationError("Only pull_request evidence uploads are allowed.")
    pr = claims.get("pull_request_number") or claims.get("pull_request", {}).get("number")
    try:
        pr_number = int(pr) if pr is not None else None
    except (TypeError, ValueError):
        pr_number = None
    return EvidenceWorkflowIdentity(
        repository_id=repo_id,
        owner_id=owner_id,
        run_id=run_id,
        run_attempt=attempt,
        event_name=event,
        sha=str(claims["sha"]).lower(),
        workflow_ref=str(claims["workflow_ref"]),
        workflow_sha=str(claims["workflow_sha"]).lower(),
        job_workflow_ref=str(claims["job_workflow_ref"]),
        job_workflow_sha=str(claims["job_workflow_sha"]).lower(),
        pull_request_number=pr_number,
    )
