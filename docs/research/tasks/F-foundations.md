# Phase F: Foundations and Hygiene (Milestone M0)

Goal: make the existing prototype trustworthy enough to build on. Fixes the gaps in `docs/audit/RADIUS_AUDIT.md`. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### F-01 Ratify research direction and record decisions   [ ]
- Owner type: human-required
- Depends on: none
- Branch: `docs/research-ratify`
- Size: S
- Goal: turn this proposal into recorded project decisions.
- Steps:
  1. Review `DESIGN.md` section 11 (open decisions) and answer each.
  2. Add `DEC-005...` entries to `docs/decisions.md` (research core = intent-to-evidence; new packages justified under DEC-003; verdict v2 states; LLM-governance rule "LLM proposes, evidence disposes").
  3. Update `docs/PRODUCT_VISION.md` and `docs/roadmap.md` to point to `docs/research/`.
  4. Update `docs/AI_CONTEXT.md` with: new glossary terms, the LLM-governance rule, branch rule (no direct commits to `dev`/`main`).
- Acceptance: DEC entries merged; vision and roadmap docs link to the plan; `AI_CONTEXT.md` mentions the new rules.
- Tests: none (docs). CI must still pass.
- Research hook: the decision log is cited in the paper's design section.
- Product hook: one consistent story for the README and website.

### F-02 Fix README claims that do not match the code   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `docs/readme-truth`
- Size: S
- Goal: remove or correct claims (Redis queue, Tree-Sitter for JS/TS, "up to 80%", test counts) so the README is accurate.
- Steps: read `README.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/DEPLOYMENT.md`; compare against `apps/worker` (SQL queue), `packages/parser` (stdlib `ast`, regex for JS/TS); fix wording; refresh test counts by actually running the suites.
- Acceptance: every factual claim in README can be traced to code or a benchmark file; counts match a fresh run.
- Tests: add a simple docs check script (optional) that fails if README mentions `Redis` while no Redis dependency exists.
- Research hook: none. Product hook: honest marketing builds trust.

### F-03 Repository hygiene   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `fix/repo-hygiene`
- Size: S
- Goal: remove noise and risk from the repo.
- Steps:
  1. Remove committed `.turbo` logs, `tmp/`, `output/`, `.docker-pip-smoke`, `.docker-smoke` artifacts if they are generated; add to `.gitignore`.
  2. Fix or move `audit_script.py` (hardcoded `d:\Radius` paths, references nonexistent `test_e2e.py`); regenerate or delete `audit_report.md` (its output is a weak signal); keep only if useful and documented.
  3. Decide where `Radius_Capstone_Project_Diary_FALL_2026.docx` lives (consider moving outside the repo or to `docs/capstone/`).
  4. Run a secret scan over history (see F-13) before making the repo public.
- Acceptance: `git status` clean after a full build/test; `.gitignore` covers generated artifacts; no hardcoded personal paths remain.
- Tests: CI passes.

### F-04 Reconcile branch flow and default branch   [ ]
- Owner type: human-required (settings) + agent-ok (docs)
- Depends on: none
- Branch: `docs/branch-flow`
- Size: S
- Goal: one agreed flow: `feature/* -> develop -> dev (UAT) -> main`.
- Steps:
  1. Update `docs/DEVELOPMENT_GUIDE.md` and `docs/github-branch-protection.md` (they say `uat`; the real branch is `dev`).
  2. Owner decides the GitHub default branch (currently `origin/HEAD` -> `dev`). Recommended: `develop` so new PRs target it by default.
  3. Apply branch protection: required CI checks, PR review, no direct push to `dev`/`main`, linear promotion only.
  4. Add a PR template (`.github/pull_request_template.md`) with the Definition of Done checklist.
  5. Note: `dev` currently contains an empty test commit `c2d5db6` that is not on `develop`/`main`. Decide: let it flow, or add a revert via PR. Do not force-push.
- Acceptance: docs match reality; branch protection active; PR template present.
- Product hook: Radius dogfoods its own required check on this repo (see IT-03).

### F-05 Remove the public API key from the dashboard   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `fix/dashboard-api-key`
- Size: M
- Goal: stop exposing `NEXT_PUBLIC_RADIUS_API_KEY` in the browser bundle.
- Steps: add server-side proxy routes (Next.js route handlers) that attach the key; or move to session-based auth already present in `apps/api/src/app/`; remove the env var from `.env.example`; update `docs/DEPLOYMENT.md`.
- Acceptance: grep of the built client bundle finds no API key; dashboard still works; tenancy enforced server-side.
- Tests: a test that builds and scans `.next` output for the key name/value; API tests with a missing/wrong key.

### F-06 Validate the GitHub App against a live installation   [ ]
- Owner type: human-required
- Depends on: none
- Branch: `docs/github-app-validation` (docs/evidence) plus fixes via `fix/*`
- Size: M
- Goal: prove the full path webhook -> analysis -> Check Run + comment on a real repo.
- Steps: create a GitHub App (permissions: checks write, pull requests write, contents read, issues read, metadata read; events: pull_request, issues, issue_comment, check_run, push); install on a sandbox repo; run through scenarios (open PR, push commit, edit description, close, force-push); record results and fix defects.
- Acceptance: a written validation report with screenshots; Check Run updates on each push; no duplicate comments; webhooks are idempotent on redelivery.
- Tests: add recorded-fixture tests for each webhook payload seen live.
- Research hook: this live repo becomes the first end-to-end data source.

### F-07 Sandbox proof and hardening   [ ]
- Owner type: pair
- Depends on: none
- Branch: `feature/sandbox-hardening`
- Size: XL (split: F-07a container limits, F-07b isolation tests, F-07c runtime option)
- Goal: execution of untrusted tests/mutants is safe; mutation testing (EV-04) depends on this.
- Steps:
  1. Container runner defaults: no network, read-only root FS, tmpfs workdir, non-root user, dropped capabilities, seccomp profile, CPU/memory/pids/ulimit/time limits.
  2. Adversarial test suite: fork bomb, memory bomb, infinite loop, disk fill, network egress attempt, reading host env/secrets, writing outside workspace, symlink escape, `/proc` access.
  3. Document `docs/security/EXECUTION_ISOLATION.md` results; evaluate gVisor/Firecracker for production and record a decision.
  4. Ensure `WORKER_EXECUTE_TESTS` stays opt-in and refuses to run without sandbox.
- Acceptance: all adversarial tests are contained and reported as such; resource limits enforced and tested; documented residual risk.
- Tests: the adversarial suite runs in CI (Linux runner).
- Risks: Windows dev machines cannot run all isolation features; CI must be the authority.

### F-08 Symbol-level impact in test selection   [x]
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/analysis-symbol-impact`
- Size: L
- Goal: feed changed-symbol information into selection and blast radius (audit gap: file-level only).
- Steps: extend `packages/analysis` diff-hunk -> changed-symbol mapping; extend graph to symbol/call level for Python; make `packages/testing` selection use symbol-reachability, with file-level fallback; keep full-suite fallback.
- Acceptance: on fixtures, selection is a strict subset of file-level selection where call-level info allows it and never drops a test that actually covers the change (checked vs coverage ground truth).
- Tests: fixtures with deliberately shared files; property test "selection superset of dynamic-coverage tests".
- Research hook: record precision/recall of selection vs dynamic coverage (used by LK-03).

### F-09 Language scope and parser upgrade   [ ]
- Owner type: pair (decision) + agent-ok
- Depends on: F-01
- Branch: `feature/parser-ts-treesitter`
- Size: L
- Goal: Python first (stdlib `ast`), TypeScript second via a real parser (tree-sitter or the TypeScript compiler API) with tsconfig path resolution.
- Steps: decision record; implement TS symbol extraction + import resolution including `paths`/`baseUrl`; keep Go/Java/Rust parsers behind "experimental".
- Acceptance: TS fixtures resolve cross-file imports incl. path aliases; regex parser removed from the default path.
- Tests: fixtures per language feature; parity tests Python.

### F-10 Observability baseline   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/ops-observability`
- Size: M
- Goal: structured logs, metrics and traces across api/worker.
- Steps: JSON logging with correlation ids (analysis id, job id, delivery id); OpenTelemetry traces; Prometheus-style metrics (job latency, queue depth, failure counts, LLM cost, sandbox kills); health/ready endpoints verify DB + queue.
- Acceptance: one analysis produces a single trace across webhook, queue, worker, publish; metrics visible locally via docker compose.
- Tests: unit tests for log redaction (no secrets).
- Research hook: latency/cost metrics feed the paper's overhead analysis.

### F-11 Flaky-test handling   [ ]
- Owner type: agent-ok
- Depends on: F-07
- Branch: `feature/testing-flaky`
- Size: M
- Goal: stop flaky tests from corrupting evidence.
- Steps: record per-test pass/fail history (exists: execution history); define flakiness score; rerun policy for failures (N reruns in sandbox); mark evidence `flaky` and reduce `q(e)` or exclude by policy; surface quarantined tests in UI.
- Acceptance: injected flaky test is detected and not counted as strong evidence; deterministic outputs.
- Tests: seeded flaky fixtures.

### F-12 Deprecate the heuristic score (flagged)   [ ]
- Owner type: agent-ok
- Depends on: VD-07 (flag mechanism)
- Branch: `feature/confidence-deprecate-score`
- Size: S
- Goal: keep the v1 0-100 score working but label it "uncalibrated heuristic" everywhere until CA-* ships.
- Acceptance: API field `score_kind="heuristic_uncalibrated"`; dashboard and PR comment show the label; docs updated.

### F-13 CI hardening   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `ci/hardening`
- Size: M
- Goal: stronger automated checks in `.github/workflows/ci.yml` (and separate workflows).
- Steps: coverage measurement + minimum threshold; `pip-audit`, `pnpm audit`; secret scanning (gitleaks) incl. history scan; SBOM generation; license check; pinned action versions; matrix for Python 3.12; cache; run adversarial sandbox suite (F-07); nightly benchmark job (non-blocking).
- Acceptance: CI fails on a seeded secret, a vulnerable dependency (test branch), or coverage drop.
- Tests: demonstration PRs documented.

### F-14 Golden fixtures corpus   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/bench-golden-fixtures`
- Size: L
- Goal: a small set of small repos with known truth, used by every later task.
- Steps: create fixtures for: correct PR with strong tests; correct PR with weak tests; incorrect PR that passes weak tests; test-tampering PR (deleted/weakened assertions); scope-creep PR; hallucinated dependency PR; vague-intent PR; multi-criterion PR with partial evidence. Each has `expected.json` (criteria, links, evidence quality bands, verdict). Store under `benchmarks/fixtures/intent/`.
- Acceptance: documented README per fixture; script to load them into the harness.
- Research hook: first labelled data; later extended into the gold set (IN-09, EP-04).

### F-15 One-command dev environment   [ ]
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/dev-onboarding`
- Size: M
- Goal: any contributor or agent runs the stack with one documented command.
- Steps: `make dev` or `pnpm dev` wrapper; docker-compose profiles (core, sandbox, observability); seed script (opt-in demo data, clearly labelled); troubleshooting section; Windows notes.
- Acceptance: fresh clone to running dashboard + API + worker in under 15 minutes following `docs/DEVELOPMENT_GUIDE.md`.

### F-16 Follow-up on the test commit on `dev`   [ ]
- Owner type: human-required
- Depends on: F-04
- Branch: n/a (decision)
- Size: S
- Goal: the empty commit `c2d5db6` ("test: verify commit identity for Mohith-c7") exists on `dev` only. Decide to leave it or revert via a normal PR. No force-push.
- Acceptance: decision recorded in `docs/decisions.md`.
