# Verification runs, 2026-11-03

What was actually run on this date, with the result and, just as important, what each run does **not** show.
Nothing here is a benchmark or a research result.

## 1. Load test (`scripts/load_test.py`)

- **Setup:** the local Docker dev stack (API, worker, dashboard, PostgreSQL) on a Windows laptop that was busy with
  other work (build jobs, a browser, several background processes). Loopback only, concurrency 8, 200 requests per
  scenario, API key from the dev `.env`.
- **Result:** 0 errors in every scenario.

| Scenario | p50 (ms) | p95 (ms) | p99 (ms) | req/s |
|---|---|---|---|---|
| `GET /health` | 46 | 77 | 91 | 163 |
| `GET /ready` | 79 | 172 | 285 | 89 |
| `GET` repositories (authenticated) | 87 | 188 | 265 | 79 |
| `GET` analyses (authenticated) | 146 | 268 | 901 | 44 |

- **Not shown:** behaviour under realistic load or real data volumes, the webhook path (the dev stack has no webhook
  secret, so that scenario did not run), a Linux host, or a production-mode deployment. The numbers are only an
  order-of-magnitude sanity check that nothing is badly slow or erroring at low concurrency.

## 2. Release workflow dry run (`release.yml`, `workflow_dispatch`, `dry_run=true`)

- **Run on GitHub Actions, result: success.** Jobs that ran: version consistency check and release notes; build, Trivy
  scan and SBOM for each of the api, worker and dashboard images. The `Publish, sign, attest` job was skipped, as
  designed: nothing was pushed to a registry and nothing was signed.
- **Not shown:** publishing, cosign signing and attestation (they only run on a tag push with the publish variable and
  a digest-pinned cosign image set), arm64 images, or that a published image can be pulled and verified.

## 3. Dynamic scan (`dast.yml`, `workflow_dispatch`)

- **Run on GitHub Actions, result: success** (the gate fails only on High alerts that are not listed in
  `.zap/rules.tsv`). OWASP ZAP baseline against the Compose stack: API 5 URLs, dashboard 52 URLs.
- **Findings:** 0 failures. Warnings: API: "Content Security Policy (CSP) Header Not Set"; dashboard: "CSP: style-src
  unsafe-inline" (x5; the dashboard framework needs inline styles), "Content-Type Header Missing" (x3),
  "Cross-Origin-Embedder-Policy Header Missing or Invalid" (x4), "Non-Storable Content", "Modern Web Application"
  (informational). These are baseline, passive-scan results.
- **Not shown:** anything behind authentication (the scan is unauthenticated), active attacks, business-logic flaws, or
  the production-mode header configuration. It is not a penetration test.

## 3b. Not run

- The webhook path under load, the poller against real GitHub, a real LLM, and a real container sandbox run for
  mutation testing are listed as open in `docs/KNOWN_LIMITATIONS.md` or in their own evaluation notes.
