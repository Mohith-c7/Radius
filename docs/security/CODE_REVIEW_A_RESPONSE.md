# Response to security code review A

Source: [docs/review/CODE_REVIEW_A_SECURITY.md](../review/CODE_REVIEW_A_SECURITY.md) (review of
`origin/develop` at 45a9bcf; read-only copy). Every finding was re-verified against the code before
changing it. Regression tests were written to fail on the unfixed code: the two HTTP-level test files were
run against a detached checkout of 45a9bcf and 73 of their 83 test cases failed there (some for the
simple reason that the new setting or helper does not exist yet); all pass on the fixed branch.

Commits (branch `fix/security-review-a`, local only):

- **C1** `47bf788` `fix(security): clone URL validation, tenant isolation, installation binding (A-01..A-06)` (also A-11, A-13)
- **C2** `587bfd8` `fix(security): auth, session and deployment hardening (A-07..A-10, A-12, A-14..A-17)`
- **C3** `docs(security): response to code review A, installation binding, limits` (this document, regenerated reference files, changelog fragments)

The split is by file, not by finding: a few shared files (for example `radius_api/config.py`, the
regenerated `docs/api/openapi.json`) hold changes for several findings and are in the commit named in the
table, see `git show --stat`.

## Status per finding

| Id | Status | Commit | Main change | Tests |
|---|---|---|---|---|
| A-01 | FIXED | C1 | `radius_repository/domain/clone_url.py` (https, allow-listed host, `owner/repo`, no userinfo/ports/control chars, 300 chars) used at `POST /repositories`, the webhook and `connect-github`, and again in `LocalGitRepositoryClient`; git is run with `--`, `-c protocol.allow=never -c protocol.https.allow=always`, `GIT_ALLOW_PROTOCOL=https`, hooks/fsmonitor/credential helper off, `--no-recurse-submodules`, never a shell; `checkout` accepts only hex 7-64 or a plain ref and uses `--detach <ref> --`; refs and PR numbers validated. Host list: `RADIUS_GIT_ALLOWED_HOSTS` (default `github.com`). | `packages/repository/tests/test_clone_url_security.py` (70 cases incl. `--upload-pack`, `file://`, `ext::`, local paths, scp-like, credentials, a real-git repro of the original primitive and proof that the client and the `--` fallback do not run it), `apps/api/tests/test_security_review_a_routes.py` |
| A-02 | FIXED | C1 | The credential header is only built for an allow-listed host (`_git_environment` raises otherwise, no unscoped fallback); the recorded `origin` of an existing checkout is re-validated before every fetch; the cache path is `cache/<organization id>/<owner>/<name>-<repo id>` and dot-only segments are neutralised. Not done: the clone URL is not forced to equal `owner/name` (see "Decisions"). | `test_clone_url_security.py` (`test_credentials_never_go_to_an_untrusted_host`, poisoned origin, local/file clone refused), worker flow tests |
| A-03 | FIXED (with documented residual) | C1 | `resolve_installation_id`: no adoption of a discovered installation unless `RADIUS_GITHUB_DEV_SINGLE_TENANT` (default on only for `RADIUS_ENV=development`); refused before asking GitHub (no oracle); an installation linked to another organization is never taken; a removed installation counts as unlinked. | `test_security_review_a_routes.py::test_connect_github_*` (SQL), `test_dev_single_tenant_defaults_follow_the_environment`; `docs/security/INSTALLATION_BINDING.md`, `LIVE_GITHUB_DEMO.md` updated |
| A-04 | FIXED | C1 | `radius_api/tenancy.py` (analysis -> repository -> organization, uniform 404) on `GET /coverage/analysis/{id}`, `.../report` and `POST /coverage`; tautological header check replaced (header optional, must be the caller's org); invalid UUIDs are 422. Found and fixed on the way: all three handlers returned 500 on success (UUID / dataclass not JSON serializable). | `test_coverage_routes_enforce_the_tenant_boundary`, `test_coverage_ingest_rejects_malformed_ids_with_4xx` |
| A-05 | FIXED (with documented residual) | C1 | `connect_repository` raises `409 REPOSITORY_ALREADY_CONNECTED` (no ids, org or URL in the body) for another organization's repository id; repository routes return 404 for foreign ids (also A-16 oracle); webhook routing prefers the installation's organization and refuses a delivery whose repository row belongs to another organization, and routes through a repository row only in explicit single-tenant modes; installations are linked by webhook only in those modes. | `test_post_repositories_does_not_return_or_take_over_another_orgs_repository`, `test_webhook_routes_to_the_org_that_owns_the_installation_not_a_squatter`, `test_unknown_installation_cannot_bind_to_a_squatted_repository`, `test_repository_ids_do_not_reveal_other_tenants_repositories` |
| A-06 | FIXED | C1 | `commitSha` must match `^[0-9a-fA-F]{7,40}$` (the domain/DB limit is 40); a `pullRequestId` that exists but belongs to another repository is 404. An id that exists nowhere is still accepted in memory mode (tests use random ids); in SQL mode the foreign key rejects it. | `test_start_analysis_rejects_a_pull_request_of_another_repository`, `test_start_analysis_rejects_malformed_commit_shas` |
| A-07 | FIXED | C2, then P1 (follow-up) | uat/production: no session at signup, sign-in refused until verified, no organization join before verification, verification discards the signup password and revokes sessions. P1: the verify-email page asks for the password in the same step (`POST /auth/verify-email/check` says whether one is required without using the link; `POST /auth/verify-email` takes `password`, answers 400 and keeps the link usable when it is missing), so a genuine self-signup no longer needs "Forgot password". Development/test keep the old flow (session at signup, no password asked). A password sent for an already verified account is ignored. OAuth link rule unchanged. | `test_security_review_a_auth.py::test_production_like_verification_replaces_the_pre_verification_password`, `test_verification_with_a_password_does_not_change_an_already_verified_account`, `test_development_verification_needs_no_password_and_keeps_the_signup_password`, `apps/dashboard/tests/verify-email.test.mjs` |
| A-08 | FIXED | C2 | `html.escape` of the display name in all three HTML mails; log lines no longer carry recipient addresses or SMTP error text. | `test_user_name_is_escaped_in_html_mail` |
| A-09 | FIXED | C2 (and C1 for the API-credentials guard in `radius_api/config.py`) | Compose forwards `RADIUS_API_KEY_PEPPER`; uat/production refuse to start without pepper or `API_KEYS`, and with `SESSION_COOKIE_SECURE=false`; compose defaults the cookie to Secure and the dev override sets it false. | `test_insecure_session_cookies_are_refused_in_production_like_modes`, `test_api_refuses_to_start_without_any_api_credentials`, `test_compose_forwards_the_api_key_pepper_and_secure_cookies` |
| A-10 | FIXED | C2 | Existence check before reading the row (`_load_session`). | `test_missing_session_row_is_401_not_500` |
| A-11 | FIXED (replay part left) | C1 | Signature compared as bytes (non-ASCII is 403); a missing signature header is refused before the body is read; non-integer repository/installation ids are 422; default webhook cap 25 MiB -> 5 MiB. Not changed: delivery id is still recorded after processing (concurrent redeliveries), replay with a new id (inherent). | `test_non_ascii_signature_header_is_403_not_500`, `test_missing_signature_is_refused_before_the_body_matters`, `test_non_integer_repository_id_is_a_client_error`, `test_webhook_body_cap_default_is_five_mebibytes` |
| A-12 | FIXED (one limit documented) | C2, then P1 (follow-up) | Dummy argon2 verification for unknown accounts; per-account throttle (10 failures / 15 min); `Login` no longer applies the signup password policy. P1: in uat/production `POST /auth/signup` answers 201 with the same body shape and no session for a new and a registered address, does the same password-hash work, sends the mail in the background, and tells the owner of a registered verified address by e-mail (an unverified owner gets a fresh verification link); development keeps the clear 409. Not done: the throttle stays in memory per process (no shared store exists: `idempotency_keys` is org-scoped and not a rate-limit store, and adding a table was out of scope), so N replicas get N times the budget and a known email can be locked for 15 minutes; the deployment recommendation (one API replica, or limit `/api/v1/auth/*` at the proxy per IP and per account) is in HTTP_HARDENING and KNOWN_LIMITATIONS. | `test_unknown_account_login_spends_a_password_hash`, `test_login_is_throttled_per_account_after_repeated_failures`, `test_login_does_not_apply_the_signup_password_policy`, `test_production_like_signup_answers_the_same_for_new_and_existing_addresses`, `test_production_like_signup_for_an_unverified_address_sends_a_fresh_link_only`, `test_development_signup_for_an_existing_address_is_a_clear_409` |
| A-13 | FIXED | C1 | `parse_owner_repo` rejects `.`/`..`; the GitHub client percent-encodes owner/repo/ref and raises on dot segments. | `test_parse_owner_repo_rejects_dot_segments`, `packages/github/tests/test_client_path_segments.py` |
| A-14 | FIXED | C2 | `UPDATE ... WHERE used_at IS NULL` and a `rowcount` check. | `test_action_token_is_single_use_even_when_a_concurrent_reader_saw_it_unused` |
| A-15 | FIXED | C2 | `/refresh` revokes the presented session, keeps the "remember" lifetime, and is in the `auth` rate-limit bucket. | `test_refresh_rotates_the_session`, `test_refresh_without_a_session_is_401`, `test_http_hardening.py` bucket table |
| A-16 | FIXED | C2 | `DEV_AUTO_VERIFY_EMAIL` refused at start-up and ignored in uat/production; action links are not logged when `RADIUS_ENV` is unset but a real session secret is configured; `/metrics` needs `RADIUS_METRICS_TOKEN` (off in uat/production without one); recipient and SMTP error text are no longer printed; 403-vs-404 oracle on repository ids closed (A-05 row). | `test_dev_auto_verify_*`, `test_action_links_are_not_logged_*`, `test_metrics_*` |
| A-17 | FIXED / by-design residual documented | C2 | No stdlib XML fallback (import fails without `defusedxml`); the per-run scratch root is created `0700`. The results directory stays `0777` because the sandbox user must write there; it is only reachable inside the `0700` root. The by-design residual (PR-controlled code produces the test outcomes) is in `KNOWN_LIMITATIONS.md`. | `packages/testing/tests/test_xml_hardening.py` (the `0700` assertion is POSIX-only and was skipped on the Windows machine used here) |

No finding was invalid. A-17's third bullet ("results dir mode 0777 on host; any local user can plant
files") is overstated: the directory sits under a `mkdtemp` root that was already `0700`, so other local
users could not traverse to it. The code now asserts that explicitly.

## Decisions taken conservatively (owner may revisit)

1. **Installation linking (A-03/A-05).** No proof-of-control flow exists, so the conservative rule is
   "linked installation only, or explicit single-tenant mode". Multi-tenant deployments need an operator to
   link installations. See [INSTALLATION_BINDING](INSTALLATION_BINDING.md).
2. **Verification replaces the signup password in uat/production (A-07).** Safe against pre-hijacking. The
   verify page now asks for the password (follow-up P1, DEC-040), so a genuine self-signup needs no reset.
3. **Clone URL not required to equal `owner/name`.** On `POST /repositories` the identity itself is
   caller-asserted, so deriving the URL from it adds nothing; the URL is validated and canonicalised, the
   token only goes to allow-listed hosts and caches are per organization. `connect-github` and signed
   webhooks take both from GitHub.
4. **Webhook body cap 5 MiB (A-11).** GitHub allows 25 MiB; raise `RADIUS_WEBHOOK_MAX_BODY_BYTES` if a
   legitimate delivery is refused with 413.
5. **Behaviour changes operators will notice:** repository caches move to a per-organization path (one
   re-clone); `POST /repositories` stores the canonical clone URL; local paths and `file://` clone URLs are
   no longer possible (tests and `scripts/smoke_e2e.py` use a local git double instead); the production
   compose profile needs a pepper or `API_KEYS`; foreign repository ids are 404, not 403.

## Not verified here

- `scripts/smoke_e2e.py` was changed (webhook and GitHub-fake clone URLs are now `https://github.com/...`,
  the worker runtime gets a local-origin git double) but not run: it needs Docker and PostgreSQL, which were
  off limits for this work. The pull-based stage depends on `RADIUS_GITHUB_DEV_SINGLE_TENANT`, which defaults
  to on because the script runs with `RADIUS_ENV` unset (= development); this is covered by the SQL tests
  `test_connect_github_dev_single_tenant_mode_keeps_the_demo_path_working`, not by the smoke itself.
- `scripts/check_compose.py` could not run (no `yaml` module in the available interpreter).
- No real GitHub, Docker sandbox or PostgreSQL was used; SQL tests run on SQLite.
- `lint-imports`: none of the touched packages (`repository`, `github`, `testing`, `shared`) has an
  `.importlinter` contract; the tool is not installed in the available environment.
- Two sandbox runner tests fail on this Windows machine with and without these changes
  (`test_container_argv_contains_every_isolation_flag`, `test_snapshot_is_a_fresh_copy_without_git_and_is_cleaned_up`:
  path separators and a symlink privilege).

## Follow-up P1 (branch `fix/review-partials`, local only)

A-07 and A-12 were finished in a later commit; see DEC-040. The only part left open is the shared login
throttle (documented above). Tests: `apps/api/tests/test_security_review_a_auth.py`,
`apps/dashboard/tests/verify-email.test.mjs`. Not verified: delivery of the real e-mails (the tests use a
fake sender); timing equality is argued from identical work, not measured.
