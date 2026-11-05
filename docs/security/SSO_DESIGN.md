# SSO / OIDC design (PRD-26)

Status (2026-11-03): **the enterprise OIDC/SSO feature in sections 2 to 12 is still design only and not implemented. The security gaps 1 to 4 in section 1 are fixed for the existing Google and GitHub sign-in** (branch `fix/oauth-pkce-oidc-validation`, see "Implementation status" below). SCIM is out of scope.

## Implementation status (Google and GitHub sign-in)

Code: `apps/api/src/app/oauth.py` (primitives), `routes_auth.py` (routes), `auth.py` (`user_from_provider`), `models.py` (`auth_oauth_flows`). Tests: `apps/api/tests/test_oauth_flow.py`, driven against an in-test stub IdP (authorize, token, JWKS, `/user`, `/user/emails`, RSA keys generated at run time, no network).

| Section 1 gap | Status |
|---|---|
| 1. No PKCE | **Fixed.** `code_challenge` (S256) is sent for Google and GitHub; the verifier is generated per flow, kept server-side and sent only to the token endpoint. GitHub's PKCE support for OAuth Apps follows its documentation and could not be verified offline; if GitHub ignored the parameters the flow would degrade to `state` plus client secret, never to something less strict than before. |
| 2. ID token not validated; `email_verified` ignored | **Fixed for Google.** Identity now comes only from the ID token: RS256 only (`none`, HS* and others refused), key chosen by `kid` from the JWKS (cached 1 h, refetched at most once a minute on an unknown `kid`, so rotation works), `iss` in the Google allow-list, `aud` equals the client id (`azp` required when there are several audiences), `exp`/`iat`/`sub` required (60 s skew), `nonce` compared in constant time. `email_verified` must be exactly `true`. The userinfo endpoint is no longer used. |
| 3. Linking by email | **Fixed.** Lookup is by `(provider, sub)` first (`auth_accounts`, unique); email is never the key. An unknown identity needs a provider-verified email. It is linked to an existing local account only when that account's email is also verified; otherwise sign-in fails with `/login?error=oauth_link_refused` (no session, nothing linked). The existence of an account is already revealed by sign-up (HTTP 409), so this adds no new disclosure. |
| 4. Bare `except` | **Fixed.** Failures raise `OAuthError` with a short code; each outcome is logged as `provider`, `outcome`, `reason` (a code or exception class) and never with codes, tokens, secrets, provider bodies or the verifier. The browser sees only `oauth`, `oauth_denied`, `oauth_email_unverified` or `oauth_link_refused`. |
| 5. Role/group claims ignored | Not changed (SSO feature). |

Also in this change: random single-use `state` (32 bytes, stored as SHA-256, deleted before it is judged), bound to the browser by the HTTP-only `radius_oauth_flow` cookie (SameSite=Lax, path `/api/v1/auth/oauth`), 10-minute expiry; `next` accepted only as a same-origin relative path (else `/`); redirect URI read only from settings and required to be exactly `<origin>/api/v1/auth/oauth/<provider>/callback` over https (http only for localhost outside production; production start-up refuses a non-https value); GitHub identity from `/user/emails` only (primary and verified, the public profile email is ignored); the callback is in the existing `auth` rate-limit bucket (10 requests per minute per IP by default); token and JWKS calls have a 10 s timeout, follow no redirects and cap the response size.

Schema: one new table, `auth_oauth_flows`. The auth tables are created by `Base.metadata.create_all` at start-up (they are not in the Alembic history), so a new table needs no migration and `auth_accounts` already stores `(provider, provider_account_id=sub)`. Existing rows keep working. Rollback: deploy the previous version; the extra table is inert.

Behaviour changes for operators: Google and GitHub users whose provider email is unverified can no longer sign in; users whose only local account is unverified are refused instead of silently linked; production refuses to start with a non-https `GOOGLE_REDIRECT_URI` or `GITHUB_REDIRECT_URI`. In-flight sign-ins started before the upgrade fail once and can be retried.

Not implemented (unchanged from this design): the generic enterprise OIDC provider, discovery, organization/role mapping, JIT provisioning settings, the SSO configuration UI, `OIDC_*` variables, `/auth/providers`, session cap for SSO, admin revoke-all, DNS-verified domains, SCIM. There is also no profile-page "link this provider" flow yet, so refused linking has no self-service path today (sign in with the password, or verify the e-mail first).

Not verified offline: the real behaviour of Google's and GitHub's endpoints (claim shapes such as string-valued `email_verified`, which is rejected here by design, GitHub PKCE, GitHub's `/user/emails` scopes). No real provider was called. A manual run against test OAuth clients is needed before release.

Threat notes for this change: authorization-code interception (PKCE plus single-use flow); login CSRF and session fixation (`state` + cookie binding, a new session id on every login); ID-token forgery, algorithm confusion and substitution (RS256 allow-list, JWKS key by `kid`, `iss`/`aud`/`nonce`); pre-hijack and account takeover through unverified emails (verified on both sides before linking); open redirect (relative-path allow-list, also after percent-decoding); secret leakage in logs (code-only reasons, tested); callback abuse (rate limit, flow burned on first use). Residual: a compromised provider signing key or a provider that asserts a wrong `email_verified`; in-memory rate-limit store is per process (see `HTTP_HARDENING.md`); the verifier and nonce sit unencrypted in the database for at most 10 minutes; Dashboard CSRF on state-changing calls is a separate open item.

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
