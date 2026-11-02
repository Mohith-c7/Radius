# API key lifecycle (PRD-12)

Managed API keys replace the static `API_KEYS` environment variable (AUDIT: static, unscoped, unhashed).

## Key format and storage

- Token: `rdk_<prefix>_<secret>`. `prefix` is 8 random hex characters (public, shown in lists and audit entries); `secret` is 256 bits from `secrets.token_urlsafe(32)`.
- Stored: a keyed fingerprint, HMAC-SHA256 over the whole token with a server-side pepper (`RADIUS_API_KEY_PEPPER`). Never the token. Because tokens are 256-bit random values, a slow password KDF would add no protection; the pepper means a leaked database cannot be used to verify or forge tokens.
- Code: all hashing lives in `apps/api/src/radius_api/token_fingerprint.py` (`token_fingerprint`, constant-time `fingerprints_match`). CodeQL may flag hashing of secret-looking values (`py/weak-sensitive-data-hashing`): HMAC-SHA256 of a high-entropy token is the intended design here, not password storage; if the alert fires, dismiss it with this explanation rather than weakening the scheme.
- Authentication always computes and compares a fingerprint (against a dummy when the prefix is unknown) and returns one identical 403 for unknown, wrong-organization, expired and revoked keys.
- The plaintext is returned once by create and rotate, and is never persisted or logged (tests assert both). `last_used_at` is written at most every `RADIUS_API_KEY_LAST_USED_INTERVAL` seconds (default 300).
- Changing the pepper invalidates every managed key. Without a pepper managed keys are disabled (insecure dev mode falls back to a fixed dev pepper).

## Lifecycle

| Action | Endpoint | Notes |
|---|---|---|
| Create | `POST /api/v1/api-keys` | Bound to the caller's organization; optional `expires_at`. |
| List | `GET /api/v1/api-keys` | Prefix only. |
| Rotate | `POST /api/v1/api-keys/{id}/rotate` | New token with same name/scopes/expiry; old key expires after `overlap_seconds` (default 24 h, 0 = immediate, max 30 days) and never has its own earlier expiry extended. Deploy the new token during the overlap. |
| Revoke | `DELETE /api/v1/api-keys/{id}` | Immediate. |
| Audit | `GET /api/v1/api-keys/audit` | Table `api_key_audit_events`: action, actor, details (no secrets). |

## Scopes

| Scope | Allows | Implies |
|---|---|---|
| `read` | All GET/HEAD requests on organization data | - |
| `write` | Other mutations (connect repositories, start/rerun analyses, intent edits, ...) | `read`, `ci-upload` |
| `ci-upload` | Only `POST /analyses/{id}/tests/results` and `POST /coverage` | - |
| `admin` | `/api/v1/api-keys` management | everything |

The mapping lives in `required_scope()` in `apps/api/src/radius_api/auth.py`. A CI job should hold a `ci-upload` key only. The GitHub webhook is authenticated separately by its HMAC secret and is not covered by API keys.

## Migrating from `API_KEYS`

Legacy `org_id:key` entries keep working (full access, all scopes) but log a startup deprecation warning.

1. Set `RADIUS_API_KEY_PEPPER` (random, 48+ characters, from your secret store).
2. Using the legacy key, `POST /api/v1/api-keys` with `{"name": "bootstrap-admin", "scopes": ["admin"]}`; save the token.
3. Create least-privilege keys: the dashboard server key (`read`, `write`), CI (`ci-upload`).
4. Update the dashboard proxy and CI secrets, confirm `last_used_at` moves on the new keys.
5. Remove `API_KEYS` and restart. The warning disappears.

Legacy keys must not start with `rdk_` (that prefix routes to managed validation).
