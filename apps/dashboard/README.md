# Radius Dashboard

Next.js application for repository management, analysis history, blast radius visualization, test execution reports, and explainable confidence reports.

The dashboard presents Radius intelligence. It must not contain domain business logic.

## Backend connection

Set these public runtime variables before running the dashboard:

- `NEXT_PUBLIC_RADIUS_API_BASE_URL` defaults to `http://localhost:8000`.
- `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID` is required, must be a valid UUID, and is sent as `X-Radius-Organization-Id`.
- `RADIUS_API_KEY` is a server-only secret (never prefix it with `NEXT_PUBLIC_`). The same-origin proxy at `/api/radius/*` attaches it as `X-Radius-API-Key`; the browser never sees it. Leave empty only for insecure local dev.
- `RADIUS_API_BASE_URL` (optional, server-only) overrides the upstream API URL used by the proxy.
- `RADIUS_DASHBOARD_INTERNAL_URL` (optional) is the dashboard origin used for server-side rendering fetches (default `http://localhost:3000`).

For local development, copy the root `.env.example` to `.env` and keep the
default local organization id unless you have a real organization id to test:

```env
NEXT_PUBLIC_RADIUS_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_RADIUS_ORGANIZATION_ID=00000000-0000-4000-8000-000000000001
RADIUS_API_KEY=
```

Run the API and dashboard together:

```powershell
pnpm --filter @radius/api dev
pnpm --filter @radius/dashboard dev
```

The API allows browser requests from the local dashboard origins
`http://localhost:3000` and `http://localhost:3001`.

## Intent panel (IN-11)

The analysis detail page (`/analyses/{id}#intent`) includes the Intent panel: criteria
extracted from the PR, issues, specs and agent prompts, with provenance and testability, which a
reviewer can confirm, reject, edit, add to, rebuild and compare across versions.

- Code: `components/intent-panel.tsx` (UI), `lib/intent.ts` (API client), `lib/intent-model.ts`
  (pure logic: state machine, span highlighting, validation, error mapping), `components/intent-panel.css`.
- All calls go through the server proxy `app/api/radius/[...path]`. `lib/proxy.ts` allowlists only the
  intent routes and methods and forwards `If-Match` and `X-Radius-Actor` (the signed-in user as `user:<id>`)
  on intent writes only, after validating them. The API key never reaches the browser.
- Intent text is untrusted: it is rendered as plain text only, never as HTML or markdown.
- Tests: `npm test` covers the client (ETag/If-Match, error mapping), proxy allowlist and header rules,
  and the pure model (span highlighting incl. emoji/RTL/XSS payloads, state legality, formatting).
- To see it locally: start the API with the in-memory backend, create an analysis, submit a source
  (`POST /api/v1/analyses/{id}/intent/sources` with `{"kind":"spec_file","text":"version: 1
criteria:
  - text: \"Users can log in\"
"}`),
  then open the analysis in the dashboard. With no intent yet the panel shows the empty state, where
  "Add intent / spec" does the same from the UI.
