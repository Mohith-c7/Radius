# HTTP hardening (PRD-11)

Covers the API (`apps/api/src/radius_api/middleware/`) and the dashboard
(`apps/dashboard/middleware.ts`, `next.config.mjs`, `lib/security-headers.mjs`).
Maps to OWASP API Top 10 2023 API4 (unrestricted resource consumption) and
API8 (security misconfiguration). Tests: `apps/api/tests/test_http_hardening.py`,
`apps/dashboard/tests/security-headers.test.mjs`.

## Middleware order (API)

Outermost first: `SecurityHeaders` -> `Correlation` (X-Request-ID) -> `CORS` ->
`RequestLimits` (413/415) -> `RateLimit` (429) -> routes. Consequences:
every reply, including 413/415/429, carries security headers; preflights are
answered by CORS before any limiter, so they never consume tokens; 413/429
carry CORS headers so a browser client can read them.

## API headers

| Header | Value | Why |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | no MIME sniffing |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` | API returns data, never documents. `/docs` and `/redoc` get a relaxed policy (jsdelivr CDN only) |
| `X-Frame-Options` | `DENY` | legacy clickjacking defence |
| `Referrer-Policy` | `no-referrer` | |
| `Permissions-Policy` | camera, microphone, geolocation, payment, usb, ... all `()` | |
| `Cross-Origin-Opener-Policy` | `same-origin` | |
| `Cross-Origin-Resource-Policy` | `same-site` | does not affect CORS-mode fetches |
| `Cache-Control` | `no-store` | default for every response; a handler-set value (for example intent) wins |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | only when `RADIUS_HSTS_ENABLED=true` (never over plain HTTP) |

## CORS

* Allow-list from `CORS_ORIGINS` (exact origins). Outside production the four
  localhost dashboard origins are added; in production they are not.
* `RADIUS_ENV=production` rejects `*`, wildcard hosts and non-`https://` origins
  at startup (config validation fails, the process does not boot).
* Methods: `GET, POST, PATCH, DELETE, OPTIONS`. Headers (explicit, never `*`):
  `Authorization, Content-Type, Accept, If-Match, Idempotency-Key, X-Request-ID,
  X-Radius-Organization-Id, X-Radius-API-Key, X-Radius-Actor, X-Analysis-Id`.
  Add a new header to `CORS_ALLOW_HEADERS` in `middleware/hardening.py` when a
  route starts reading one.
* Exposed: `ETag, X-Request-ID, Retry-After, RateLimit-*`.
* Credentials: `Access-Control-Allow-Credentials: true` by default because the
  dashboard authenticates with an HTTP-only session cookie. It is dropped
  automatically if `*` is configured (development only), and can be turned off
  with `RADIUS_CORS_ALLOW_CREDENTIALS=false`. CORS is not CSRF protection; CSRF
  defences belong to PRD-26.

## Body limits, content types, timeouts

* Default 1 MiB (`RADIUS_MAX_BODY_BYTES`); GitHub webhook 5 MiB (was 25 MiB, GitHub's own maximum; lowered because the body is buffered before the signature is verified, raise `RADIUS_WEBHOOK_MAX_BODY_BYTES` if a legitimate delivery gets 413; a delivery without a signature header is refused before its body is read);
  test-report upload `.../tests/results` 20 MiB (the route's own
  existing cap). `Content-Length` is checked first; chunked or lying clients are
  counted while streamed and answered `413` (FastAPI would otherwise turn the
  read error into a 400).
* Composition with the intent routes: their 256 KiB `Content-Length` check
  (`422 PAYLOAD_TOO_LARGE`, unchanged) is stricter and runs first; the global
  cap only catches chunked intent bodies between 256 KiB and 1 MiB.
* `415` for POST/PUT/PATCH bodies that are not JSON. Not applied to the webhook
  (HMAC over the raw bytes decides) or test-report upload (raw XML/JSON).
* Slowloris and idle connections are not handled in the app. Run uvicorn behind a
  reverse proxy that enforces header/body read timeouts (nginx
  `client_header_timeout`, `client_body_timeout`, `send_timeout`; or Envoy
  `request_headers_timeout`) and set `--timeout-keep-alive` (default 5 s) and
  `--limit-concurrency`. A per-request application timeout is a follow-up.

## Rate limiting

Token bucket per key: capacity = requests, refill = requests/window. Burst equals
capacity.

| Bucket | Matches | Keyed by | Default |
|---|---|---|---|
| `auth` | `POST /api/v1/auth/*` except logout (refresh is limited too, A-15), `GET /api/v1/auth/oauth/*` | client IP | 10 / 60 s |
| `webhook` | `POST /api/v1/webhooks/github` | client IP | 600 / 60 s |
| `expensive` | `POST` analyses, rerun, intent rebuild/sources, tests/results, coverage, sync-pull-requests | API key and IP | 20 / 60 s |
| `general` | everything else | API key and IP | 600 / 60 s |

* Never limited: `/health`, `/ready` (both prefixed and bare), `/metrics`, `OPTIONS`.
* Key-identified buckets consume both a per-key bucket (`X-Radius-API-Key`,
  stored only as a SHA-256 prefix) and a per-IP bucket (`RADIUS_RATE_LIMIT_IP_MULTIPLIER` x
  the per-key limit), so rotating invalid keys cannot bypass the limit.
* The dashboard proxy uses one server-side API key from one IP, so all
  dashboard users share one `general`/`expensive` bucket. Size
  `RADIUS_RATE_LIMIT_GENERAL` for your user count.
* Headers on limited routes: `RateLimit-Limit`, `RateLimit-Remaining`,
  `RateLimit-Reset` (seconds until full), `RateLimit-Policy` (`N;w=window`);
  `Retry-After` (whole seconds, at least 1) on 429. Names follow
  draft-ietf-httpapi-ratelimit-headers-07; the draft is not final.
* Webhook "by installation": the installation id is only available after the
  signature is verified, which happens in the IN-02 route. Until that route calls
  `app.state.rate_limiter.store.consume("webhook:installation:<id>", ...)` the
  bucket is per source IP (GitHub egress IPs are shared, hence the generous default).
* Failure policy: if the store raises, the request is allowed (fail open) and the
  error is logged. Availability beats throttling for this API; the 429 path also
  stays behind authentication and signature checks.
* Metric: `radius_http_rate_limited_total{bucket}` (Prometheus, F-10 module,
  enabled with `RADIUS_METRICS_ENABLED`).
* Store: `InMemoryRateLimitStore` (LRU, 100k keys). It implements the small
  `RateLimitStore` protocol, so a shared store can be plugged in via
  `install_http_hardening(..., rate_limit_store=...)`.

### Known limits

* The account login throttle (`routes_auth._login_failures`: 10 failures per account per 15 minutes, then 429) is also per process and is not behind the `RateLimitStore` seam. With several API replicas either run one replica for the auth endpoints or rate-limit `/api/v1/auth/*` per IP and per account at the reverse proxy; do not rely on the in-process counter for replicated deployments (DEC-040).
* In-memory state is per process: with N replicas the effective limit is up to
  N x configured, and a restart resets buckets. Multi-replica deployments need a
  shared store (follow-up: Redis-compatible or PostgreSQL-backed adapter), or
  rate limiting at the edge proxy.
* Evicting least recently used keys under memory pressure resets those clients to a full bucket.
* Without `RADIUS_TRUSTED_PROXIES` behind a proxy, all clients share the proxy's
  IP and its IP bucket. With it set, `X-Forwarded-For` is walked right to left and
  the first non-trusted hop is the client. Only list proxies you control.

## Dashboard

Per-request CSP is built in `middleware.ts` with a fresh nonce:

    default-src 'self'; script-src 'self' 'nonce-<n>' 'strict-dynamic';
    style-src 'self' 'unsafe-inline';
    font-src 'self'; img-src 'self' data: blob:;
    connect-src 'self' <NEXT_PUBLIC_RADIUS_API_BASE_URL origin>; object-src 'none';
    base-uri 'self'; form-action 'self'; frame-ancestors 'none'

`next.config.mjs` adds static headers to every path including `/_next/*`:
`X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`,
COOP/CORP, and HSTS when `RADIUS_HSTS_ENABLED=true`. `X-Powered-By` is removed.

Trade-offs:

* The root layout reads `headers()`, which makes every page dynamically
  rendered. That is required for the nonce to reach Next.js's inline scripts;
  static prerendering cannot carry a per-request nonce. The app is an
  authenticated client-rendered dashboard, so little is lost.
* `style-src 'unsafe-inline'` remains because React renders `style=""`
  attributes widely. Script execution is unaffected. The dashboard
  uses a system font stack (`--font-sans`, `--font-mono` in `globals.css`); it fetches no web fonts and
  no external host appears in `style-src` or `font-src`. Manrope and DM Mono are named first in the stack
  but are only used if installed on the viewer's machine. Self-hosting them with `next/font/local` needs the
  OFL font files committed to the repo, which was not possible offline.
* Development mode adds `'unsafe-eval'` and `ws:` for React refresh only.
* `connect-src` includes the API origin because the sign-in forms call the API
  directly with cookies (`lib/auth.ts`); the `/api/radius` proxy is same-origin.

## Verifying

    # API (default dev port)
    curl -si http://localhost:8000/api/v1/health | grep -iE "nosniff|content-security|cache-control|frame|referrer"
    curl -si -X OPTIONS http://localhost:8000/api/v1/repositories \
      -H "Origin: https://evil.test" -H "Access-Control-Request-Method: GET" | head -1   # 400
    curl -si -X POST http://localhost:8000/api/v1/repositories -H "Content-Type: text/plain" -d x   # 415
    for i in 1 2 3 4 5 6 7 8 9 10 11; do curl -s -o /dev/null -w "%{http_code} " \
      -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{}'; done  # ...429
    # Dashboard (after next build && next start)
    curl -sI http://localhost:3000/login | grep -iE "content-security|x-frame|nosniff"
    curl -s http://localhost:3000/login | grep -o '<script[^>]*>' | grep -vc nonce   # 0

## Dashboard session validation and tenancy (C-01)

* The dashboard never trusts the mere presence of a `radius_session` cookie. Its middleware **and** the
  `/api/radius/*` proxy route call `GET /api/v1/auth/me` on the API with the cookie (server side) and accept the
  request only on a clear "signed in" answer. The answer is cached in memory for 15 s (a rejection for 5 s;
  errors are never cached), keyed by a per-process keyed digest of the cookie. Any other outcome (API down,
  timeout of 5 s, 5xx, malformed answer) is **fail closed**: the proxy answers 503 `AUTH_UNAVAILABLE`, pages redirect to `/login`.
  A revoked or expired session therefore stops working within the cache time. `next dev` (NODE_ENV=development)
  keeps the old no-auth behaviour for local work only.
* Destructive proxied calls (`DELETE`) additionally need the validated user's role to be `admin` (403 otherwise).
  The audit actor (`X-Radius-Actor`) of intent writes is the validated user's e-mail, not a client header.
* **A deployment is single-tenant.** The proxy talks to the API with ONE configured key and organization
  (`RADIUS_API_KEY`, `RADIUS_ORGANIZATION_ID`). Every authenticated dashboard user shares that organization and its
  data, whatever workspace was created for them at sign-up. Do not enable open sign-up on a shared deployment
  (see A-07 in the security review); per-user organization routing is not implemented.
* Cookie scope: the session cookie is host-only by default, which needs the dashboard and the API on one origin
  (or both on `localhost`, where ports are ignored). For separate hosts such as `app.example.com` and
  `api.example.com`, set `SESSION_COOKIE_DOMAIN=example.com` on the API (and `SESSION_COOKIE_SECURE=true` over TLS).
* Published ports: Compose binds api (8000) and dashboard (3000) to `127.0.0.1` by default. The production
  binding is a deliberate choice: a TLS reverse proxy in front (recommended), or
  `RADIUS_API_BIND_ADDRESS` / `RADIUS_DASHBOARD_BIND_ADDRESS` set to `0.0.0.0`.
* List endpoints (`/repositories`, `/repositories/{id}/pull-requests`, `/analyses`) take `limit` (default 100,
  maximum 500) and `offset` and return `meta.pagination` (`limit`, `offset`, `total`, `returned`).

## Not verified here

No browser was available: CSP violations at runtime (console reports) are
unverified. Static review of the built HTML for `/login`, `/signup`,
`/forgot-password` found every `<script>` carrying the nonce and no inline event
handlers. Run the PRD-22 browser e2e (or open each page with devtools) before relying on it.

## Follow-ups

* Shared rate-limit store (Redis-compatible or PostgreSQL) and per-installation
  webhook bucket after signature verification (IN-02 files).
* CSP `report-to`/report-only rollout; drop style `'unsafe-inline'`.
* Application-level request timeout; align intent `422 PAYLOAD_TOO_LARGE` with 413 in a
  contract-versioned change.
* Disable `/docs` in production or put it behind auth.
* Dashboard CI header scan against a running build (curl snippet above).
