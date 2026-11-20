"""Non-interactive backend verification for GitHub Artifact Attestations."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from radius_testing.provenance import PREDICATE_TYPE

VERIFIER_VERSION = "gh-attestation-cli-v1"


@dataclass(frozen=True, slots=True)
class AttestationResult:
    status: str
    reason_code: str | None
    details: dict[str, Any]


class GitHubAttestationVerifier:
    """Verify a supplied Sigstore bundle with the supported GitHub CLI verifier.

    The CLI runs as a non-interactive subprocess over locally supplied report
    and bundle files. It is not allowed to fetch or select attestations; the API
    retrieves those first using the connected GitHub App installation.
    """

    def __init__(
        self,
        *,
        executable: str = "gh",
        trusted_root: str = "",
        runner: Callable[..., Any] = subprocess.run,
        timeout_seconds: int = 30,
    ) -> None:
        self.executable = executable
        self.trusted_root = trusted_root
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def verify(
        self,
        *,
        artifact: bytes,
        bundle: bytes,
        repository: str,
        signer_workflow: str,
        signer_digest: str,
        expected_predicate: dict[str, Any],
        repository_id: int,
        owner_id: int,
    ) -> AttestationResult:
        if not artifact or not bundle:
            return AttestationResult("rejected", "ATTESTATION_BUNDLE_MISSING", {})
        if not signer_workflow or not signer_digest:
            return AttestationResult("unverifiable", "POLICY_INCOMPLETE", {})
        try:
            with tempfile.TemporaryDirectory(prefix="radius-attest-") as temp:
                root = Path(temp)
                artifact_path = root / "report.bin"
                bundle_path = root / "bundle.jsonl"
                artifact_path.write_bytes(artifact)
                bundle_path.write_bytes(bundle)
                command = [
                    self.executable,
                    "attestation",
                    "verify",
                    str(artifact_path),
                    "--bundle",
                    str(bundle_path),
                    "--repo",
                    repository,
                    "--signer-workflow",
                    signer_workflow,
                    "--signer-digest",
                    signer_digest,
                    "--predicate-type",
                    PREDICATE_TYPE,
                    "--format",
                    "json",
                ]
                if self.trusted_root:
                    command.extend(("--custom-trusted-root", self.trusted_root))
                completed = self.runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                    shell=False,
                )
        except FileNotFoundError:
            return AttestationResult("unverifiable", "VERIFIER_UNAVAILABLE", {})
        except subprocess.TimeoutExpired:
            return AttestationResult("unverifiable", "VERIFIER_TIMEOUT", {})
        except OSError:
            return AttestationResult("unverifiable", "VERIFIER_UNAVAILABLE", {})

        if completed.returncode != 0:
            output = f"{completed.stderr}\n{completed.stdout}".lower()
            if any(token in output for token in ("trusted root", "tuf", "network", "timeout")):
                return AttestationResult("unverifiable", "TRUST_ROOT_UNAVAILABLE", {})
            return AttestationResult("rejected", "ATTESTATION_SIGNATURE_INVALID", {})
        try:
            result = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            return AttestationResult("unverifiable", "VERIFIER_OUTPUT_INVALID", {})
        entries = result if isinstance(result, list) else [result]
        for entry in entries:
            verified = entry.get("verificationResult", {}) if isinstance(entry, dict) else {}
            statement = verified.get("statement", {})
            certificate = verified.get("signature", {}).get("certificate", {})
            predicate = statement.get("predicate", {})
            if not isinstance(predicate, dict) or not isinstance(certificate, dict):
                continue
            expected_digest = hashlib.sha256(artifact).hexdigest()
            subjects = statement.get("subject", ())
            if not any(
                isinstance(subject, dict)
                and (subject.get("digest") or {}).get("sha256") == expected_digest
                for subject in subjects
            ):
                return AttestationResult("rejected", "ARTIFACT_DIGEST_MISMATCH", {})
            if statement.get("predicateType") != PREDICATE_TYPE:
                return AttestationResult("rejected", "PREDICATE_TYPE_MISMATCH", {})
            source_repo_id = _int_claim(certificate, "sourceRepositoryIdentifier")
            source_owner_id = _int_claim(certificate, "sourceRepositoryOwnerIdentifier")
            if source_repo_id is None or source_owner_id is None:
                return AttestationResult("unverifiable", "IDENTITY_CLAIMS_MISSING", {})
            if source_repo_id != repository_id or source_owner_id != owner_id:
                return AttestationResult("rejected", "REPOSITORY_ID_MISMATCH", {})
            if any(predicate.get(key) != value for key, value in expected_predicate.items()):
                return AttestationResult("rejected", "PROVENANCE_BINDING_MISMATCH", {})
            verified_timestamps = verified.get("verifiedTimestamps")
            if not verified_timestamps:
                return AttestationResult("unverifiable", "TIMESTAMP_UNVERIFIABLE", {})
            return AttestationResult(
                "verified_provenance",
                None,
                {
                    "predicate_type": statement.get("predicateType"),
                    "certificate_identity": certificate.get("subjectAlternativeName"),
                    "verified_timestamp_count": len(verified_timestamps),
                },
            )
        return AttestationResult("rejected", "PREDICATE_NOT_FOUND", {})


def _int_claim(claims: dict[str, Any], name: str) -> int | None:
    value = claims.get(name)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
