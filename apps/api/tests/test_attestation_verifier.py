"""Fail-closed tests for backend GitHub attestation verification."""

import hashlib
import json
from types import SimpleNamespace

from radius_api.attestations import GitHubAttestationVerifier
from radius_testing.provenance import PREDICATE_TYPE


def _verified_output(artifact: bytes, predicate: dict) -> str:
    return json.dumps(
        [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": PREDICATE_TYPE,
                        "subject": [
                            {"name": "report.xml", "digest": {"sha256": hashlib.sha256(artifact).hexdigest()}}
                        ],
                        "predicate": predicate,
                    },
                    "signature": {
                        "certificate": {
                            "sourceRepositoryIdentifier": "1001",
                            "sourceRepositoryOwnerIdentifier": "2002",
                            "subjectAlternativeName": "workflow-identity",
                        }
                    },
                    "verifiedTimestamps": [{"kind": "transparency-log"}],
                }
            }
        ]
    )


def test_backend_verifier_checks_github_signature_identity_and_predicate() -> None:
    artifact = b"<testsuite/>"
    predicate = {"analysis_id": "analysis", "report_slot_id": "slot"}
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=_verified_output(artifact, predicate), stderr="")

    verifier = GitHubAttestationVerifier(
        executable="gh", trusted_root="trusted-root.jsonl", runner=runner
    )
    result = verifier.verify(
        artifact=artifact,
        bundle=b"signed-bundle",
        repository="acme/project",
        signer_workflow="radius/actions/.github/workflows/tests.yml",
        signer_digest="f" * 40,
        expected_predicate=predicate,
        repository_id=1001,
        owner_id=2002,
    )

    assert result.status == "verified_provenance"
    command, kwargs = calls[0]
    assert "--custom-trusted-root" in command
    assert "--signer-digest" in command
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 30


def test_backend_verifier_fails_closed_when_verifier_is_missing() -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError

    result = GitHubAttestationVerifier(runner=missing).verify(
        artifact=b"report",
        bundle=b"bundle",
        repository="acme/project",
        signer_workflow="radius/actions/.github/workflows/tests.yml",
        signer_digest="f" * 40,
        expected_predicate={},
        repository_id=1001,
        owner_id=2002,
    )
    assert (result.status, result.reason_code) == ("unverifiable", "VERIFIER_UNAVAILABLE")


def test_backend_verifier_rejects_digest_mismatch_and_invalid_signature() -> None:
    artifact = b"actual report"
    predicate = {"slot": "one"}
    output = json.loads(_verified_output(artifact, predicate))
    output[0]["verificationResult"]["statement"]["subject"][0]["digest"]["sha256"] = "0" * 64
    verifier = GitHubAttestationVerifier(
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(output), stderr=""
        )
    )
    digest_result = verifier.verify(
        artifact=artifact,
        bundle=b"bundle",
        repository="acme/project",
        signer_workflow="radius/actions/.github/workflows/tests.yml",
        signer_digest="f" * 40,
        expected_predicate=predicate,
        repository_id=1001,
        owner_id=2002,
    )
    assert (digest_result.status, digest_result.reason_code) == (
        "rejected",
        "ARTIFACT_DIGEST_MISMATCH",
    )

    invalid = GitHubAttestationVerifier(
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="signature verification failed"
        )
    ).verify(
        artifact=artifact,
        bundle=b"bundle",
        repository="acme/project",
        signer_workflow="radius/actions/.github/workflows/tests.yml",
        signer_digest="f" * 40,
        expected_predicate=predicate,
        repository_id=1001,
        owner_id=2002,
    )
    assert (invalid.status, invalid.reason_code) == (
        "rejected",
        "ATTESTATION_SIGNATURE_INVALID",
    )
