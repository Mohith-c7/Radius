"""OIDC policy rejects identity and context mismatches before evidence upload."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from radius_api import provenance_auth


def _token(monkeypatch, overrides=None):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(
        provenance_auth,
        "_JWKS",
        SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)
        ),
    )
    now = datetime.now(UTC)
    claims = {
        "iss": provenance_auth.GITHUB_OIDC_ISSUER,
        "aud": provenance_auth.EVIDENCE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "repository_id": "1234",
        "repository_owner_id": "4321",
        "run_id": "777",
        "run_attempt": "2",
        "event_name": "pull_request",
        "workflow_ref": "acme/project/.github/workflows/radius.yml@refs/heads/main",
        "workflow_sha": "a" * 40,
        "job_workflow_ref": "radius-org/actions/.github/workflows/evidence.yml@" + "b" * 40,
        "job_workflow_sha": "b" * 40,
        "sha": "c" * 40,
    }
    claims.update(overrides or {})
    return jwt.encode(claims, private_key, algorithm="RS256")


def _verify(token):
    return provenance_auth.verify_evidence_oidc(
        token,
        reusable_workflow_ref="radius-org/actions/.github/workflows/evidence.yml@" + "b" * 40,
        reusable_workflow_sha="b" * 40,
        caller_workflow_path=".github/workflows/radius.yml",
        caller_workflow_sha="a" * 40,
    )


def test_oidc_accepts_only_configured_workflow_and_pull_request(monkeypatch):
    identity = _verify(_token(monkeypatch))
    assert (identity.repository_id, identity.owner_id) == (1234, 4321)
    assert (identity.run_id, identity.run_attempt) == ("777", 2)


def test_oidc_rejects_forged_or_unapproved_workflow_claims(monkeypatch):
    for claim, value in (
        ("job_workflow_sha", "d" * 40),
        ("workflow_sha", "e" * 40),
        ("event_name", "workflow_dispatch"),
    ):
        try:
            _verify(_token(monkeypatch, {claim: value}))
        except provenance_auth.OidcAuthenticationError:
            pass
        else:
            raise AssertionError(f"OIDC policy accepted invalid {claim}")


def test_oidc_default_denies_missing_policy(monkeypatch):
    token = _token(monkeypatch)
    try:
        provenance_auth.verify_evidence_oidc(
            token,
            reusable_workflow_ref="",
            reusable_workflow_sha="",
            caller_workflow_path="",
            caller_workflow_sha="",
        )
    except provenance_auth.OidcAuthenticationError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("unconfigured policy was accepted")
