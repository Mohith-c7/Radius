# SSO / OIDC design (PRD-26)

Status: **design only, 2026-11-03. No auth code was changed.** Nothing here is implemented or tested. SCIM is out of scope.

## 1. Where we start (read from the code)

All of this lives in `apps/api/src/app/` (`routes_auth.py`, `auth.py`, `models.py`, `config.py`):

- Sessions: an HS256 JWT (`type=session`, `sub`=user id, `sid`=`auth_sessions.id`) in the HTTP-only cookie `radius_session` (SameSite=Lax, `Secure` from `SESSION_COOKIE_SECURE`), 14 days or 30 with "remember". Server-side row `auth_sessions` with `revoked_at`, so a session can be revoked. `current_user` checks signature, row, expiry and revocation.
- Users: `auth_users` (unique email, `password_hash` nullable, `email_verified`, `role`, `organization_id`), `auth_accounts` (`provider`, `provider_account_id`), and `provision_domain_user_and_org` which mirrors the user into the shared schema (`users`, `organizations`) and creates a personal workspace organization when none exists.
- Existing OAuth for Google and GitHub (`/auth/oauth/{provider}` and `/callback`): state is a signed JWT plus a nonce cookie. Gaps relevant to SSO that a reviewer should know:
  1. no PKCE (the code is bound only by `client_secret`);
  2. Google identity is read from the userinfo endpoint; the ID token is never validated (`iss`, `aud`, `exp`, `nonce`, signature) and `email_verified` is not checked;
  3. `user_from_provider` links a new provider account to an existing local user **by email** without requiring a verified email from the provider. That is an account-takeover vector for any provider that lets users assert an unverified email;
  4. a bare `except Exception` redirects to `/login?error=oauth`, so failures are indistinguishable in logs;
  5. a provider's role or group claims are ignored.
- API keys (`docs/security/API_KEYS.md`) authenticate machines to `/api/v1/*` per organization. SSO affects the dashboard sign-in path only; API keys are unchanged.

## 2. Goals and non-goals

Goals: generic OIDC login (authorization code + PKCE, confidential client) for a workforce IdP (Okta, Entra ID, Keycloak, Google Workspace); map IdP identity to an existing Radius organization and role; just-in-time (JIT) provisioning; reuse the current session cookie and revocation; fix gaps 1 to 4 above for the new path (and, as part of the same change, for the Google/GitHub path).

Non-goals: SCIM or any directory sync; SAML; IdP-initiated login; back-channel logout in v1; per-user MFA policy (the IdP's job); changing API-key auth; multi-IdP per organization (v1: one IdP per deployment, optionally per organization in v2).

## 3. Flow (authorization code + PKCE)

1. `GET /api/v1/auth/oidc/login?org=<slug>&next=<path>`: the API loads the provider config, fetches discovery once (cached, TTL 1 h, from the configured issuer only), generates `state` (random 32 bytes), `nonce`, and `code_verifier` (random 64 bytes). It stores `{state_hash, nonce, code_verifier, org, next, expires=10 min}` server-side in a new `auth_oidc_flows` table (single use) and sets only an opaque HTTP-only SameSite=Lax cookie `radius_oidc_flow` containing the flow id (not the verifier). Redirect (302) to `authorization_endpoint` with `response_type=code`, `scope=openid email profile` (plus groups scope when configured), `code_challenge=S256(verifier)`, `code_challenge_method=S256`, `state`, `nonce`, `redirect_uri`.
2. `GET /api/v1/auth/oidc/callback?code&state`: load and **delete** the flow row (single use) by cookie id; constant-time compare `state`; reject if expired. If the IdP returned `error`, log it by class and redirect to `/login?error=sso_denied`.
3. Back-channel `POST token_endpoint` (timeout 10 s, TLS verified, no redirects followed) with `code`, `code_verifier`, `redirect_uri`, client authentication (`client_secret_basic`).
4. Validate the ID token: signature against the issuer's JWKS (RS256/ES256 only, `alg=none` and HS* refused, JWKS refetched at most once per minute on unknown `kid`), `iss` equals the configured issuer exactly, `aud` contains the client id (and `azp` matches when multiple), `exp`/`iat` with 60 s skew, `nonce` equals the stored nonce. Library: PyJWT is already a dependency (`PyJWKClient`); no new dependency is needed for validation.
5. Require `email_verified is True` (configurable per IdP only to `allow_unverified_email=false` in v1, no override) and a non-empty `sub`. Identity key is `(issuer, sub)`; email is an attribute, never the key.
6. Resolve or provision the user (section 5), compute role (section 4), call `create_session` and `set_session`, redirect to the validated `next` (relative path allow-list, same-origin only, else `/`).

## 4. Organization and role mapping

- Tenancy: `OIDC_ORG_MODE=single` (v1 default) maps every login from this IdP to one configured organization id (`OIDC_ORGANIZATION_ID`). `by_domain` (v2) maps verified email domain to organization through an `auth_sso_domains` table whose rows are created by an organization admin and must be proven by DNS TXT record before use (to prevent a tenant claiming another tenant's domain).
- Roles: `OIDC_ROLE_CLAIM` (default `groups`) is read from the ID token (or userinfo when absent). `OIDC_ROLE_MAP` is a JSON object `{"<idp group>": "admin"|"developer"|"viewer"}`; the highest mapped role wins; no match gives `OIDC_DEFAULT_ROLE` (default `viewer`, or "deny" to refuse login). Roles are re-evaluated on every login, so a demotion at the IdP takes effect at next login (and within the session TTL at worst; see failure modes). `UserRole` values must be checked against `radius_shared.database.enums` during implementation; any role missing there needs a migration, which is part of the estimate.
- A user can never be elevated above what the map says by editing their own profile attributes; only IdP-asserted claims in a validated token count.

## 5. JIT provisioning and account linking

- Lookup by `auth_accounts(provider='oidc:<issuer-hash>', provider_account_id=sub)`. Found: update name and role, create session.
- Not found, JIT enabled (`OIDC_JIT=true`): create `auth_users` (verified email, no password), the `auth_accounts` link and the domain user in the configured organization (not a personal workspace, unlike today's `provision_domain_user_and_org`, which needs an `organization_id` parameter).
- Existing local user with the same email: **do not auto-link** by default. Linking requires either (a) the user is signed in locally and completes an OIDC flow from the profile page, or (b) `OIDC_LINK_EXISTING_BY_EMAIL=true` set by an operator who trusts the IdP to own the email namespace. Default false closes the takeover vector described in section 1.3.
- JIT off and no account: refuse with `/login?error=sso_not_provisioned`.
- Deprovisioning: v1 has no push from the IdP. Offboarding is by disabling the user at the IdP (no new logins) plus an admin "revoke all sessions" action that sets `revoked_at` on the user's `auth_sessions`. Session TTL for SSO sessions is capped at `OIDC_SESSION_MAX_HOURS` (default 8) so a removed user loses access within that window even without revocation.

## 6. Configuration variables (proposed; to be added to `Settings` and the generated config reference)

| Variable | Default | Meaning |
|---|---|---|
| `OIDC_ENABLED` | `false` | Master switch; routes return 404 when off |
| `OIDC_ISSUER` | none | Issuer URL (https required outside `RADIUS_ENV=development`) |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | none | Confidential client; secret never logged |
| `OIDC_REDIRECT_URI` | none | Must exactly match the IdP registration; https in production |
| `OIDC_SCOPES` | `openid email profile` | Add `groups` if the IdP needs it |
| `OIDC_ORG_MODE`, `OIDC_ORGANIZATION_ID` | `single`, none | Tenancy mapping |
| `OIDC_ROLE_CLAIM`, `OIDC_ROLE_MAP`, `OIDC_DEFAULT_ROLE` | `groups`, `{}`, `viewer` | Role mapping |
| `OIDC_JIT`, `OIDC_LINK_EXISTING_BY_EMAIL` | `true`, `false` | Provisioning and linking |
| `OIDC_SESSION_MAX_HOURS` | `8` | Cap on SSO session lifetime |
| `OIDC_ALLOWED_EMAIL_DOMAINS` | empty | Optional allow-list |

Startup validation (like the existing `_production_guards`): refuse to start with `OIDC_ENABLED=true` and a missing issuer/client/secret/redirect, a non-https issuer in production, or a role map that is not valid JSON.

## 7. Threat model (STRIDE-style, short)

| Threat | Mitigation in this design | Residual |
|---|---|---|
| Authorization-code interception | PKCE S256, single-use flow row, exact redirect URI | none known beyond IdP bugs |
| Login CSRF / session fixation | `state` bound to a server-side flow and an HTTP-only cookie; new session id created on every login; old cookie replaced | none known |
| Token substitution / replay | `nonce`, `aud`, `iss`, `exp` checks; code single use | IdP clock errors (60 s skew) |
| Algorithm confusion, forged ID token | allow-list RS256/ES256, key from issuer JWKS only | compromised IdP signing key |
| Account takeover by unverified or reassigned email | identity key is `(iss, sub)`; `email_verified` required; no auto-link by email by default | operators who enable email linking accept the IdP's email integrity |
| Cross-tenant login via domain claim | `by_domain` needs DNS-verified domains (v2) | none known |
| Open redirect after login | `next` accepted only as a same-origin relative path | none known |
| SSRF through discovery/JWKS | only the configured issuer host; no redirects; private-address blocking in the HTTP helper; discovery document's `issuer` must equal config | an IdP that is itself hostile |
| Stale privileges after IdP change | role re-evaluated at each login; SSO sessions capped at 8 h; admin revoke-all | up to the cap |
| Secret leakage | secret only in env/secret store, never in logs or errors; verifier never in a cookie | host compromise |
| Cookie theft | existing HTTP-only, Secure, SameSite=Lax; no tokens in localStorage; IdP tokens are discarded after validation (not stored) | XSS is mitigated by CSP (`HTTP_HARDENING.md`), not eliminated |
| Dashboard state-changing calls (CSRF) | SameSite=Lax is the only defence today; PRD-26 separately requires an explicit CSRF token or Origin check on state-changing dashboard calls | open until that item is built |

## 8. Failure modes

| Situation | Behaviour |
|---|---|
| IdP down / discovery or token call times out | `/login?error=sso_unavailable`, logged with error class; local password login still works |
| JWKS rotation | unknown `kid` triggers one refetch (rate limited); then reject |
| Expired or reused flow, state mismatch | `/login?error=sso_failed`; flow row deleted; no detail to the user |
| Token valid but `email_verified` false or email missing | reject (`sso_unverified_email`) |
| No role matches and default is deny | reject (`sso_no_role`) |
| Clock skew > 60 s | reject; operator doc says to run NTP |
| Misconfiguration | API refuses to start (validation above), never silently falls back to a weaker mode |
| Database error while provisioning | transaction rolled back, no half-created user; 503-style redirect |

Logging: one structured line per outcome with `issuer`, `sub` hash, outcome class; never tokens, codes, secrets, verifier.

## 9. Migration plan

1. Alembic migration (expand only): `auth_oidc_flows` (id, state_hash, nonce, code_verifier, org, next, expires_at), optional `auth_sso_domains` later, and a nullable `auth_accounts.issuer` column (existing rows keep working with `provider` google/github).
2. Ship behind `OIDC_ENABLED=false`; no behaviour change for existing users.
3. Fix the existing Google path in the same PR series: add PKCE, validate the ID token, require `email_verified`, stop auto-linking by email. This changes behaviour for existing Google users who relied on email linking; release notes must say so.
4. Dashboard: sign-in page shows an "SSO" button only when `/auth/providers` (new, unauthenticated, returns booleans only) reports OIDC enabled. The existing OAuth buttons stay. Cookie and middleware (`apps/dashboard/middleware.ts`) need no change because the session cookie is the same.
5. Rollback: set `OIDC_ENABLED=false`; the tables are additive, so no down-migration is required for rollback.

## 10. Test plan

- Unit: PKCE challenge, state/nonce handling, ID-token validation matrix (bad signature, wrong `iss`, wrong `aud`, expired, wrong nonce, `alg=none`, HS256 with the public key as secret, missing `email_verified`), role mapping (highest wins, default, deny), `next` sanitising, settings validation.
- Integration: an in-process fake IdP (a small FastAPI app that serves discovery, JWKS from a test RSA key, token endpoint) driven through `TestClient`: happy path with JIT, repeat login, role demotion, existing-email-no-link, IdP error, replayed callback, expired flow, JWKS rotation. No external network in CI.
- Security regression: callback replay returns failure; cookie flags; session revoked after revoke-all; the SSRF guard blocks a discovery URL that resolves to loopback.
- E2E (PRD-22 harness): sign in through the fake IdP and reach the dashboard. A conformance run against a real IdP (Keycloak container) is a manual pre-release check, not a CI gate in v1.
- Not tested by this plan: IdP-specific quirks (Entra v1 tokens, Okta custom claims); they need a tenant of each.

## 11. Estimate

Roughly 8 to 12 engineer-days for v1 (single org, JIT, role map, fake-IdP tests, fixes to the Google path, docs), plus 3 to 5 days for `by_domain` with DNS proof, plus about 2 days for a CSRF token/Origin check on dashboard mutations if it is built with this work. These are planning estimates, not measurements.

## 12. Open questions for the owner

1. Is one IdP per deployment enough for the first release? (assumed yes)
2. Should password login be disable-able per organization once SSO is on? (not in v1)
3. Which IdP will be used for the first real test (Keycloak assumed for the manual check)?
4. Is auto-linking by email ever acceptable for existing Google users, or do we require re-linking from the profile page? (design says re-link)
