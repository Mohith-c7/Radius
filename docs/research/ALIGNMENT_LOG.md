# Alignment Log

Purpose: a dated, evidence-based check of whether what is built and merged matches the stated product vision and research goals. Entries are append-only; new reviews go on top of the older ones' conclusions, they do not rewrite them.

How to read the evidence: every claim cites a path in this repository at `origin/develop` commit `e3538fa` (257 commits, 1,090 tracked files). "Unverified" marks anything I did not or could not check (no builds, no test runs, no Docker, no live GitHub App, no network were used in this review). Line counts are `wc -l` over non-test `*.py` files and are only a rough size signal.

---

## Entry 2026-11-02: first independent review

Reviewer stance: independent, written without seeing prior conclusions. Blunt but fair. The project's documents are unusually honest about their own gaps (README, novelty assessment, pre-registration); most of the criticism below is about where effort is going and what the default product does, not about misstatements.

### 1. Vision and claims (with sources)

1. **Core promise.** A merge verdict is a statement about intent: for each thing the change was supposed to do, how much trustworthy evidence exists that it does, and how much that evidence can be trusted. Source: `docs/research/DESIGN.md` section 1; `docs/research/PRODUCT_AND_GTM.md` section 2.
2. **The LLM proposes, evidence disposes.** LLMs may extract criteria or verify links; the verdict is deterministic and never LLM-computed. Source: `docs/research/DESIGN.md` sections 1 and 7; `docs/decisions.md` DEC-009; `docs/security/PROMPT_INJECTION.md`.
3. **Evidence strength is measured, not assumed.** `q(e) = d_eff * i * f` (mutation detection power or capped static assertion strength, independence of authorship, freshness to head SHA); tamper findings discount it. "Tests pass" is explicitly insufficient. Source: `DESIGN.md` 6.3; `PRODUCT_AND_GTM.md` section 4 differentiator 2.
4. **Per-criterion support and four-state verdict v2** (`verified`, `failed`, `insufficient_evidence`, `needs_review`) with a justification tree. Source: `DESIGN.md` 6.4 and 6.5; DEC-008.
5. **Calibrated trust and abstention.** Calibrated probability P, conformal risk control, "uncalibrated prior" labelling until enough labels exist. Source: `DESIGN.md` 6.7; `preregistration/PREREGISTRATION.md` (H3a to H3c).
6. **Process verification.** Agent trajectories and process signals ("lucky pass") add predictive value beyond the final output. Source: `DESIGN.md` 6.6; `PREREGISTRATION.md` claim C4.
7. **Review triage and a manager layer.** Risk-ranked hunks plus an agent re-prompt for developers; honest aggregate portfolio, trends and policy compliance for managers. Source: `DESIGN.md` 6.8; `PRODUCT_AND_GTM.md` section 3; `tasks/TR-triage.md`, `tasks/MG-manager.md`.
8. **Differentiated from TestSprite-style generation.** Radius judges evidence against intent, works with any tests, is deterministic and self-hostable, and does not generate code into user repos. Source: `PRODUCT_AND_GTM.md` section 4; DEC-019; `DESIGN.md` section 10.
9. **Research contribution with falsifiable, pre-registered claims** (C1 to C5, RQ1 to RQ6, baselines B0 to B12, no gold at inference), explicitly narrowed after the literature review because criterion-to-evidence mapping and benchmark-time mutation strengthening already exist. Source: `PREREGISTRATION.md` section 1 and 2; `literature/novelty-assessment.md`.
10. **Production-grade, self-hostable open source.** Apache-2.0 core with open-core split, DCO, opt-in telemetry, supply-chain hardening, 10-minute install to first verdict. Source: DEC-018, DEC-022, DEC-023; `docs/production-readiness/{AUDIT,BACKLOG}.md`; `PRODUCT_AND_GTM.md` sections 8 and 10.
11. **Honesty as a product principle.** Intervals, abstention, no correctness guarantees, "heuristic, not probability" labelling. Source: `PRODUCT_AND_GTM.md` section 5; `docs/PRODUCT_VISION.md` (explainability over automation); `README.md` status note.
12. **Staged delivery with gates.** M0 to M7; MVP = M0 to M3 (criteria matrix in the PR comment is the first demo). Source: `docs/research/IMPLEMENTATION_PLAN.md` section 4; `PRODUCT_AND_GTM.md` section 6.

### 2. Traffic-light table

Legend. Status: shipped / dark (built, behind a flag or not wired) / designed-only / missing. Alignment: green (matches vision), yellow (partial or off-critical-path), red (absent or contradicting).

| Capability | Vision requirement | What exists in code today (path, default, tested how) | Status | Alignment | Note |
|---|---|---|---|---|---|
| Graph-driven test selection (file-level) | Cheap, fast first value; v1 base | `packages/analysis`, `packages/graph`, `packages/testing`, wired in `apps/worker/src/radius_worker/orchestrator.py`; on by default; unit tests plus a 120-mutant self-evaluation (`docs/benchmarks/REAL_REPO_BENCHMARK.md`, own packages only, one language) | shipped | green | Solid, honestly scoped. This is v1, not the headline. |
| Symbol-level impact in selection | Symbol is the unit of linking | `packages/graph` symbol impact, `RADIUS_FEATURE_SYMBOL_IMPACT` default **false** (`apps/worker/src/radius_worker/config.py`); ground-truth test `tests/test_symbol_impact_ground_truth.py`; Python only | dark | yellow | Built, not default. Evidence that it helps in the default path is a small test. |
| Evidence-gated verdict v1 (`verified`/`failed`/`insufficient_evidence`) | Missing evidence never becomes a pass | `packages/confidence/.../infrastructure/scoring.py`; default; unit tests. `verified` means every executable changed file maps to selected tests that all ran and none failed | shipped | green | Sound abstain-by-default design, but evidence strength is not examined. A weak or agent-rewritten test yields `verified`. |
| 0-100 confidence score | Calibrated trust (replace heuristic) | Same file; labelled `heuristic_uncalibrated` (F-12); default | shipped (deprecated) | yellow | Correctly labelled. Calibration is the replacement and does not exist. |
| Test execution | Evidence needs real results | Sandbox runner `packages/testing`, `WORKER_TEST_EXECUTION_MODE` default **disabled**; adversarial suite `packages/testing/tests/test_sandbox_adversarial.py`; no external pen-test (README) | dark | yellow | By default the worker runs no tests, so the default verdict depends on the user uploading CI results. |
| CI result ingestion bound to head SHA | Evidence bound to current SHA (freshness `f(e)`) | API/`packages/testing`, JUnit XML + JSON, accumulated; default; tested | shipped | green | Freshness binding exists in v1 form. `EV-07` generalisation is not done. |
| Flaky-test handling | Flaky evidence must not count as proof | `WORKER_TEST_RERUNS` default **0** (off), `WORKER_FLAKY_POLICY=exclude`; `packages/testing`, `docs/FLAKY_TESTS.md` | dark | yellow | Off by default. README says flaky "is treated as a failure"; code default is "exclude, blocks verified" (see section 4). |
| Intent source ingestion from GitHub (IN-02) | Collect PR body, issues, commits, `intent.yml` | `packages/github/src/radius_github/intent_*.py`, `apps/worker/src/radius_worker/intent_ingestion.py`, `RADIUS_FEATURE_INTENT_INGESTION` default **false**; tests in `apps/worker/tests/test_intent_ingestion.py`; not yet live-validated (config text says "OFF until the live F-06 validation") | dark | yellow | Fixture-tested only; never exercised against a real installation in repo evidence (unverified). |
| Criterion extraction, testability, snapshots, persistence, API, dashboard panel | Intent as confirmable criteria | `packages/intent` (about 11,000 non-test lines, the largest package), `apps/api/.../routes/intent.py`, dashboard Intent panel (IN-11); API/dashboard available, but nothing populates it by default; unit, fuzz, determinism tests | shipped (as an API/UI, not a pipeline stage) | yellow | Well built, strong tests. With ingestion off, a normal PR never gets a snapshot unless someone POSTs a source. |
| LLM criterion extraction | Optional, guarded, opt-in | `packages/intent/.../infrastructure/llm`, `radius_shared.llm_guard`, 98-case injection corpus `tests/security/prompt_injection`; off by default | dark | green | Governance is genuinely ahead of most comparable tools. |
| Extraction metrics harness / gold annotation (RQ1) | Measure extraction P/R on a gold set | `packages/intent/.../evaluation`, `benchmarks/gold/` tooling; **no real gold data** (`benchmarks/gold/README.md`); only synthetic | dark | yellow | RQ1 numbers do not exist yet. M1 gate ("P/R measured on gold set") is not met. |
| Criterion-to-symbol linking (LK-02) | Link criteria to implementing symbols | `packages/linking` (about 3,100 lines), 5 linkers, noisy-OR; **no persistence, not called from the worker** (README of the package: "Persistence is LK-05") | dark | yellow | A library with no caller in `apps/`. Grep of `apps/worker` shows no import. |
| Symbol-to-test linking (LK-03) | Dynamic coverage contexts, strongest link signal | `packages/testing/.../linking`; `RADIUS_FEATURE_COVERAGE_CONTEXTS` default false; "not wired into the pipeline until LK-05" (config text) | dark | yellow | Task still `[~]`. |
| Symbol change extraction (LK-01) | Symbol-level change set | `packages/analysis`, `RADIUS_FEATURE_SYMBOL_CHANGES` default false; counts logged, "Nothing is persisted yet" | dark | yellow | Result is discarded after logging. |
| Test assertion extraction (LK-04) | Know what each test asserts | none found | missing | red | Prerequisite of `a_static` and of link quality. |
| Intent-Evidence Graph builder (LK-05) | The IEG is the data structure everything else reads | none | missing | red | **The keystone.** Every dark capability above is waiting on it. |
| Evidence item model / normalizers (EV-01) | Typed evidence bound to SHA | none (`packages/evidence` does not exist; only v1 test counts in `packages/confidence`) | missing | red | |
| Tamper rule engine (EV-02) | Detect weakened or faked evidence | **No code.** Only the word appears in unrelated tests; no `packages/tamper` | missing | red | The cheapest differentiator to ship and the one competitors (Verik, SlopGate) already have. |
| Authorship/independence (EV-03), `a_static` (EV-06), freshness (EV-07), `q(e)` (EV-08) | Measured evidence strength | none | missing | red | This is the headline claim; zero lines exist. |
| Mutation service, `d_mut` (EV-04/05) | Fault-detection power of tests | Only a **benchmark harness** `benchmarks/real/mutations.py` that mutates Radius's own code to evaluate test selection; no product service, no `packages/mutation` | missing (as product) | red | Do not confuse the benchmark's mutations with the planned evidence-strength mutation service. |
| Support S(c), UIM, per-criterion states (VD-01/02) | Per-criterion verdict | none | missing | red | |
| Verdict v2 + `needs_review` + justification tree (VD-03) | Four-state, auditable verdict | none; `VerificationStatus` has three states in `packages/confidence/.../domain/enums.py` | missing | red | |
| Policy engine / waivers (VD-04/05) | Org-configurable enforcement | none | missing | red | |
| PR comment / Check Run v2, republish after CI (VD-06) | Criteria matrix in the PR | `packages/github/.../publisher.py` renders v1 verdict, blast radius, heuristic score. README: check run "not re-published after later CI uploads" | shipped (v1) | yellow | The v2 comment does not exist; even v1 does not refresh after CI upload. |
| Process verification (PR-01..10) | Trajectories, process signals | none | missing | red | Differentiator 4 is designed-only. |
| Calibration and abstention (CA-01..09) | Calibrated P, conformal abstention | none; `packages/calibration` does not exist | designed-only | red | Pre-registration (H3) is detailed; code is zero. |
| Review triage (TR-*) | Risk-ranked hunks, agent re-prompt | none | designed-only | red | |
| Manager layer (MG-*) | Portfolio, trends, RBAC | Dashboard has repository/PR/analysis/compare pages (`apps/dashboard/app`); no org portfolio, trends or RBAC | designed-only | red | Dashboard is developer-facing. |
| Integrations (IT-*): CLI, Action v2, MCP, importers | Distribution wedge | Only a local composite action `.github/actions/radius-verify`; README: "Nothing is published" | designed-only | red | MCP/CLI is the stated wedge and does not exist. |
| Research track: literature, novelty, pre-registration, datasets | Falsifiable, pre-registered claims | `docs/research/literature/*`, `preregistration/PREREGISTRATION.md` (v0.2-draft, **not frozen**), `benchmarks/datasets/manifests` (17 pinned manifests), tooling with leakage-checked splits | shipped (docs/tooling) | green | High quality. But no experiment can run until the product emits the features (UIM etc.). |
| Security of untrusted text/code | Treat PR text and code as hostile | `radius_shared.llm_guard`, `docs/security/*`, hardened sandbox, HMAC webhooks, tenant 404 behaviour; SAST via CodeQL | shipped | green | Strong for pre-1.0. Pen-test and tenant isolation suite (QS-03/04) not done. |
| Supply-chain / community / CI hardening | Production-grade OSS | `.github/workflows/{ci,codeql,coverage,dependency-review,nightly,scorecard,security,commit-lint}.yml`, community files, Dependabot | shipped | yellow | Good, but a large share of recent effort (section 4). |
| Licence | Apache-2.0 open core | DEC-018 decided; **no `LICENSE`/`NOTICE` in the tree**; README says "licence pending" | designed-only | red | Public repo is all-rights-reserved today. |
| Docs consistency (README, task trackers) | Truthful docs | README mostly accurate; several stale lines and stale task checkboxes (section 4) | shipped | yellow | |

### 3. What a user actually experiences today on a PR

Traced from code, not from docs. Unverified end to end in this review (no stack was run); the trace is from `apps/api`, `apps/worker/src/radius_worker/{runner,orchestrator,config}.py`, `packages/confidence`, `packages/github/src/radius_github/publisher.py`, `README.md`.

1. **Install.** Docker Compose dev stack (`make dev`) brings up Postgres, migrations, API, worker, dashboard. It does **not** connect GitHub; connecting needs a hand-made GitHub App plus webhook/key variables (`README.md` Quickstart). The live GitHub App validation (F-06) exists as a runbook and scenario tests, not as a recorded live run (unverified). This is a setup-friction point against the "10 minutes to first verdict" target (`PRODUCT_AND_GTM.md` section 8).
2. **Webhook to job.** Signed webhook (HMAC), idempotent, an analysis row and a job in the Postgres queue.
3. **Worker.** Publishes an "in progress" Check Run, then (only if `RADIUS_FEATURE_INTENT_INGESTION` is true, default false) ingests intent sources into a snapshot. Then `_execute` in `orchestrator.py`: changed files, parse, code graph, discover tests, (optional symbol refinement, default off), select tests, run tests (default **disabled**), blast radius, `generate_report`. There is no call into `radius_linking`, no tamper step, no evidence-quality step, and the LK-01 symbol extraction result is logged and dropped.
4. **Verdict.** `DeterministicConfidenceScorer`: `failed` if any test failed; `insufficient_evidence` if changed executable files are not mapped to selected tests, tests were not run, none selected, all skipped, or flaky; otherwise `verified`. Plus the 0-100 heuristic score labelled uncalibrated.
5. **Where the evidence comes from.** Because test execution is off by default, a typical first result is `insufficient_evidence` ("Selected tests were not executed; upload CI results to verify", `scoring.py`). To get `verified` the user must run the selected tests in their CI and upload JUnit/JSON bound to the head SHA (`docs/CI_INTEGRATION_GUIDE.md`). README states the Check Run and comment are **not re-published** after that upload.
6. **PR comment / Check Run.** Verdict title, heuristic score and risk level, blast-radius table, selected tests, evidence list (`publisher.py`). No criteria, no intent, no evidence-strength statement.
7. **Dashboard.** Repository, PR, analysis pages, graph visualiser, test hub, report ingestion, and an Intent panel with criteria confirmation. The Intent panel is populated only if intent ingestion is enabled or someone submits a source via the API; it is not linked to the verdict.

**Direct answer.** The headline promise (intent-to-evidence verification with measured evidence strength) is **not visible to a user today**. The default product is the v1 product: file-level (optionally symbol-level) test selection plus a conservative abstain-by-default verdict and a heuristic score. That v1 is honest and non-trivial (it never turns missing evidence into a pass), but it is exactly the category the research docs say is not the contribution ("Radius v1: did CI pass / which tests did the change reach", `DESIGN.md` section 1 table).

Wiring of the new capabilities into the **default verdict**:

| Capability | In default verdict? | Detail |
|---|---|---|
| Intent (criteria, snapshots) | No | Exists as API/dashboard; ingestion flag off; verdict code takes no intent input (`GenerateConfidenceReportCommand` carries impact, tests, analysis only). README confirms "Not in the verdict." |
| Criterion-to-symbol linking | No | Library only; no caller in `apps/`; no persistence. |
| Symbol-to-test linking | No | Flag off; "not wired into the pipeline until LK-05." |
| Tamper rules | No | Do not exist. |
| Symbol impact | No by default | Flag off. When on, it narrows test selection and blast radius only. |
| Flaky handling | No by default | Reruns default 0. When on: flaky tests are excluded and block `verified`. |
| Evidence quality, support, UIM, verdict v2, calibration, process, triage, manager | No | Not built. |

### 4. Drift and risk assessment

#### 4.1 Where effort is going versus where the differentiators are

Observed from `git log origin/develop` (257 commits; about 173 non-merge by subject prefix: 73 `feat`, 43 `docs`, 22 `fix`, 10 `test`, 9 `ci`, 9 `build`, 9 `chore`):

- Package size (non-test Python, rough): `intent` 10,971, `testing` 7,294, `analysis` 5,237, `linking` 3,119, `github` 3,017, `parser` 2,609, `confidence` 2,021 (the verdict), `graph` 2,101. **Zero lines** for evidence quality, tamper, mutation service, verdict v2, calibration, trajectory, triage, policy, manager. The intent package is five times the size of the package that computes the verdict, and none of it influences the verdict.
- Roughly 30 to 40 percent of recent non-merge commits are supply-chain, CI, Dependabot, advisories, community-health, README/changelog tooling and licence work (keyword count of the log gives 47 of about 173; the regex is loose, treat as an order of magnitude, hand count unverified). In the last ~40 commits: PRD-03/04/05/06/07, pnpm audit baselines, Dependabot grouping, gitleaks allowlists, commit-lint scopes, action pin bumps. Against that, the number of commits touching the differentiators (evidence strength, verdict v2, calibration, process, triage, manager) is **zero**.
- The research docs themselves are large: about 4,300 lines of markdown under `docs/research` plus 820 under `docs/production-readiness`, versus the ~2,000-line verdict implementation. The planning-to-building ratio for the differentiators is extreme.
- Sequencing follows the plan's order (F, then IN, then LK), so this is not unplanned drift; it is a *plan whose first half is differentiator-free* (see the critical path below). The IMPLEMENTATION_PLAN says the MVP is M0 to M3 and the headline mutation feature is M4; so even a successful MVP lacks the measured-strength claim (only static `a_static`, capped at 0.4).

#### 4.2 Critical path to the first user-visible "verdict v2 per criterion"

Done: IN-01 to IN-08, IN-11, LK-01, LK-02, partial LK-03. Missing, in dependency order (derived from `docs/research/tasks/{LK,EV,VD}-*.md` and `DESIGN.md` sections 3 and 6; ordering is my judgement, check against each task's `Depends on`):

1. **Turn on and live-validate intent ingestion** (F-06 live run, then default-on or documented opt-in). Without a snapshot per PR nothing downstream has input.
2. **LK-05 IEG builder and persistence** (also persists LK-01 changes, LK-02 links). Keystone.
3. **LK-04 test assertion extraction** (input to `a_static`).
4. **LK-03 finish and LK-06 link combination** (confidence for symbol-to-test and end-to-end link confidence `l(c,e)`).
5. **EV-01 evidence item model and normalizers** (turn JUnit/coverage results into typed evidence).
6. **EV-07 freshness binding** (largely exists in v1; generalise).
7. **EV-06 static assertion strength `a_static`** and **EV-03 authorship/independence**.
8. **EV-02 tamper rule engine** (can and should be done *before* the rest; it is independent and self-contained).
9. **EV-08 `q(e)` combiner and config** (`algo_version` stamped).
10. **VD-01 support S(c)**, **VD-02 UIM and states**, **VD-03 verdict rules v2 + justification tree** (`needs_review` can be stubbed because calibration is later).
11. **VD-07 feature flag/v1 compatibility**, then **VD-06 PR comment and Check Run v2 with republish after CI upload** (without republish the user sees stale verdicts).
12. Optionally VD-04 policy for advisory vs required mode.

That is roughly 14 to 16 tasks, none started, ahead of the first visible criterion matrix. Effort-sizing in the task files suggests months for a small team; this review did not estimate beyond that.

#### 4.3 Contradictions between docs and code, and claims the code does not support

- **Flaky handling.** `README.md` maturity table and `CHANGELOG.md` say a flaky test "is treated as a failure". Code default `WORKER_FLAKY_POLICY=exclude` (`apps/worker/.../config.py`) and `scoring.py` treat flaky as a verification gap (verdict `insufficient_evidence`), not a failure; rerun is also off by default, so there is no flaky detection in a default install.
- **README is behind the code.** It says contribution/security files "are being added (PRD-03)", but `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md` etc. are in the tree (merged via PR #50). It lists "Criterion-to-evidence linking ... planned" and "automatic ingestion from the PR is not built", whereas `packages/linking` and IN-02 ingestion are merged (dark). Not harmful, but the file is the front door.
- **Task trackers stale.** `docs/research/tasks/F-foundations.md` still shows F-05, F-06, F-07, F-10, F-14, F-15 as `[ ]` although commits for them are merged (`824697b`, `e2c99f8`, `f35006e`, `83b9832`, `2039b04`, `a08b31b`). The "Definition of Done: tick the checkbox" rule is not holding, so the trackers cannot be used as a progress metric.
- **Milestone gate claims.** M0 gate requires "live GitHub App test done" and "README matches code"; the live test is not recorded in the repo and the README mismatches above exist. M1 gate requires extraction P/R measured on a gold set; no real gold data exists (`benchmarks/gold/README.md`). Yet M2-level work (LK-01..03) was merged. The gates are not being enforced.
- **Legacy Gemini path.** DEC-021 says the Gemini pruner is "flagged"; `google-genai` and `google-generativeai` remain **core** dependencies in `pyproject.toml`; `docs/DEPLOYMENT.md` still documents `GEMINI_API_KEY`; `SemanticPruner` is imported in `orchestrator.py` inside `_run_semantic_cpg_poc`, which is only called from tests, so it is not on the live path (checked by grep). Multiple legacy docs (`docs/PHASE3.md`, `PHASE4_PRD.md`) still describe Gemini reasoning cards as completed features, and `apps/dashboard/components/interactive-graph.tsx` still references pruning/Gemini (not inspected in depth, unverified what it renders). A new reader sees a code-egress to a third party advertised in docs that contradicts DEC-021.
- **Vision doc vs research doc.** `docs/PRODUCT_VISION.md` still frames the product as "Can this change be merged safely?" and lists test-selection-era principles; the intent-to-evidence thesis lives only in `docs/research/`. Two competing statements of purpose in the repository.
- **Competing roadmaps.** `docs/PHASE3.md` (about 100 KB), `PHASE*_PRD.md`, `roadmap.md`, `milestones.md` (152 bytes), `api.md`, `architecture.md` (stubs) coexist with the research plan. The "single source of truth" claim in `docs/research/README.md` is not true for a reader of `docs/`.

#### 4.4 Research-validity risks

- **No experiment can start.** RQ2 to RQ5 need `UIM`, `q(e)`, P and process features computed by the production pipeline (`EP-05` requires "same pipeline as production"). None exists. Preregistration is correctly not frozen, but the freeze is gated on features and datasets, not on the owner.
- **RQ1 has no data.** Zero real gold PRs; the extraction F1 >= 0.75 and Top-3 >= 0.80 hypotheses are untested. The synthetic data is clearly labelled, which is good.
- **Label validity (RQ2/RQ3 primary label `L_ABS`).** The primary label is "passes official tests but fails SWE-ABS strengthened tests". That label is itself produced by a mutation/strengthening method closely related to the predictor (`d_mut`). The risk is circularity: UIM may be predicting "what strengthened tests catch" rather than correctness. The pre-registration partly acknowledges this (robustness on `L_cons`); it remains the largest threat to C2.
- **Criteria on SWE-bench are not PRs.** SWE-bench tasks have issue text but not acceptance-criteria PR bodies; criterion extraction quality on that text is a hidden confound in RQ2 (extraction error propagates into UIM). The harness must separate extraction error from evidence-strength effect.
- **Compute.** H2 requires thousands of patches with mutation runs (min 5,000, power analysis assumes ~0.20 prevalence). No budget or measurement of mutation cost per patch exists in the repo; this may force the "underpowered" fallback.
- **Mixed-language/time claims.** Calibration "under time and repo shift" (H3b) needs time-split labels; dependence on SWE-ABS's coverage of repos is unverified.
- **Baselines.** B4 (AgentProof-style) is "re-implemented from a README" of a tool with no stated licence and 0 stars; a weak re-implementation of the key baseline makes C1 trivially winnable and reviewers will notice.
- **Unfalsifiable-leaning claims.** Differentiators 3 and 4 in `PRODUCT_AND_GTM.md` (calibrated trust; process signals) are plausible but if the process dataset (own trajectories) is small, C4 degrades to exploratory. The plan acknowledges fallbacks; they should be decided now, not at the end.
- **Self-evaluation only.** The only existing numbers (`REAL_REPO_BENCHMARK.md`) are on Radius's own four packages (120 mutants). Fine as a smoke test, not as evidence; avoid citing them externally.
- **Pre-registration complexity.** The prereg is long and highly elaborate for a pre-1.0 project with no running feature. Over-specified protocols increase the cost of any required amendment and give a false sense of rigor before the construct (UIM) works at all.

#### 4.5 Product risks

- **Setup friction.** A self-made GitHub App, secret handling, Docker build ("about 10 minutes on a cold cache"), then a default that runs no tests, so the first PR typically yields `insufficient_evidence` until CI upload is wired. First-run value is "not verified, upload results".
- **Stale verdicts.** Check Run not re-published after CI upload (README). A user can see "insufficient evidence" on a PR whose CI later proved it.
- **Trust and strictness.** The v1 verdict's `verified` requires every changed executable file to map to selected tests that passed. This is conservative, so noisy abstentions are likely on real repos (docs, config, generated code, non-Python). No measured abstention rate on external repos exists.
- **Untrusted PR text and code.** Good controls for LLM input (sanitiser, nonce-delimited blocks, span-verified outputs, 98-case corpus). Gaps: the injection suite uses stub models, not live-model runs (the doc says no network); pen-test for the sandbox not done; tenant isolation suite (QS-04) not done; `execute_tests` legacy flag can still select `unsafe_in_process` (guarded in uat/production by `RADIUS_ALLOW_UNSAFE_EXECUTION`, but dev-mode users may enable it).
- **LLM egress.** DEC-021 and DEC-026 limit egress to redacted intent text and symbol names/paths/change kinds. The linking re-ranker sends file paths and qualified names, which can be sensitive for private repos; this should be stated to users in the opt-in text (unverified whether it is).
- **Single-maintainer bus factor and IP.** Five commits by a second author and a capstone/sponsor question block the licence (DEC-018). AI-assistant co-authored commits (12 attributed to "Claude") make provenance explicit but are treated as the owner's work by decision.
- **Distribution.** The stated wedge (MCP/CLI/Action for agent users) is entirely unbuilt; the only distribution path today is "self-host a Compose stack and hand-create a GitHub App".

#### 4.6 Things that could embarrass the project publicly

1. **No licence file in a public repository.** Legally all-rights-reserved while the README invites use; a would-be adopter or reviewer cannot legally fork or evaluate it. DEC-018 documents this, but it still reads as "open source with no licence".
2. **Committed capstone artefacts.** `Radius_Capstone_Project_Diary_FALL_2026.docx` at the repo root, a second copy at `docs/capstone/`, and `generate_capstone_diary.py` (which also mentions Gemini). They are unrelated to the product, may carry academic or personal information, and contribute to the IP-ownership question. Contents of the .docx were not inspected (unverified).
3. **Legacy Gemini path** (section 4.3): core dependency, documented API key, docs advertising LLM pruning. Not on the live path, but it contradicts "code stays in the customer's environment".
4. **Unverified quickstart.** README says the first build takes several minutes and cites a reference run; no CI job in the workflows list builds the Compose stack end to end (workflow list only; job content of `ci.yml` was not read in detail, unverified). A broken `make dev` is the fastest way to lose a first visitor.
5. **Name.** "Radius" trademark clearance not done (DEC-024); the name is generic and heavily used in software.
6. **Over-claiming risk in competitor comparisons.** `PRODUCT_AND_GTM.md` says TestSprite etc. "Radius ... works with any tests" and "deterministic and self-hostable" as differences. Today Radius cannot judge test quality at all. Comparing against a funded competitor on a capability that is unbuilt invites a fair rebuttal. README is careful about this; the GTM doc is not (but is marked as hypotheses).
7. **Planning volume as signal.** 4,300 lines of research plan against a verdict module of ~2,000 lines can read as "a plan, not a product".

### 5. Prioritized course correction

#### The next 10 things to do

1. **Ship tamper rules (EV-02) as the first differentiator.** Independent of IEG, deterministic, testable on `benchmarks/gold`/golden fixtures, and visible in the PR comment. Why: it makes the vision (agent-weakened tests) real in days, and the comparison with Verik/SlopGate becomes concrete.
2. **Live-validate GitHub App (F-06) and decide intent ingestion default-on.** Why: no intent, no intent-to-evidence product; a recorded live run is the M0 gate and a credibility artefact.
3. **LK-05 IEG builder + persistence, minimal version (criterion, symbol, test, link).** Why: it unblocks every dark package; start with one language (Python) and existing LK-02/LK-03 outputs.
4. **EV-01 + EV-06 + EV-07 + EV-08: cheap `q(e)` with static assertion strength capped at 0.4.** Why: the first measurable "this test would not have caught it" statement, with `algo_version`.
5. **VD-01..03 behind `RADIUS_FEATURE_VERDICT_V2`, rendered as a per-criterion table in the comment (VD-06 partial), plus republish after CI upload.** Why: this is the headline promise visible to a user; do a thin vertical slice first, then deepen.
6. **Make the default first-run produce evidence.** Either default-on sandbox execution in the Compose stack or a two-line Action that runs selected tests and uploads results. Why: today's default yields `insufficient_evidence`, which is a bad first impression and a bad demo.
7. **Collect the real gold set (IN-09) for 30 to 50 PRs and publish real RQ1 numbers (IN-10), even if unflattering.** Why: M1's gate is unmet; also tests whether intent exists in real PRs at all (the biggest product-viability unknown).
8. **Resolve the licence and the sponsor/IP question, and remove capstone artefacts from the tree (history stays; decide on rewrite).** Why: the open-source and research-artifact promises depend on it.
9. **Thin demo: one repo, four scripted PRs (PL-04) showing "tests pass but criterion unproven".** Why: the claim must be demonstrable in 5 minutes; use it also as the integration test for the v2 slice.
10. **Reconcile docs: update README maturity table, F-task checkboxes, flaky wording, Gemini dependency/doc status; add an automated "doc/code drift" check (e.g. a script that fails if a merged task ID is unticked).** Why: honesty is a product principle and the trackers are the only progress instrument.

#### Stop or defer

- **Stop** adding new supply-chain/CI/community-health tasks beyond the already planned set until a verdict-v2 slice is merged; defer PRD-wave 2 to 5 (release pipeline, Helm, docs site, SSO, perf pages, badge) except the licence.
- **Stop** extending `packages/intent` (more extractors, more sources, more UI) until real gold data shows what fails; it is already the biggest package.
- **Defer** mutation service (EV-04/05/09/10) until the `q(e)` static slice and IEG are live; keep the mutation *benchmark* separate.
- **Defer** process verification, calibration, triage and manager layer implementation; do not start them before a verdict-v2 slice exists. Keep only the data capture that is cheap (outcome labels from revert detection) if desired.
- **Defer** pre-registration freezing and baseline re-implementations (B3 to B12) until the construct runs.
- **Stop** adding LLM re-rankers and other LLM surfaces (LK-02 re-ranker was built before any non-LLM link quality was measured on real data).
- **Remove/deprecate** the Gemini pruner, its two core dependencies and its docs; move to an optional extra or delete.
- **Defer** TypeScript/Go/Java/Rust expansion; stay Python (DEC-013).
- **Defer** additional trackers/GitLab/Bitbucket integrations (IT-07, IT-10).

#### Re-check cadence

Every 4 weeks, and at each milestone gate (M2 and M3 especially), as a short appended entry to this file, run by someone other than the person who wrote the most recent code. A "drift alarm" check also whenever more than 10 consecutive non-merge commits touch none of the differentiator paths.

#### Five metrics a future check should read (all cheap and objective)

1. **Differentiator commit share:** non-merge commits in the last 30 days touching `packages/{evidence,tamper,mutation,calibration,trajectory,triage,policy}` or `packages/confidence` verdict code, divided by all non-merge commits (`git log --since=30.days --no-merges --name-only`). Today: ~0.
2. **Verdict inputs:** the set of fields in `GenerateConfidenceReportCommand` and whether any is derived from intent/links/tamper/evidence quality (a grep or a type check). Today: none.
3. **Default-path reachability:** for each "dark" package, is it imported from `apps/worker` or `apps/api` request path and enabled by default? (feature-flag table from `apps/worker/src/radius_worker/config.py` plus an import grep). Today: linking, tamper, mutation are 0 of 3.
4. **Real-data count:** number of real (non-synthetic) gold PRs in `benchmarks/gold`, external repos executed in `benchmarks/real/corpus.json`, and live-installation PRs analysed with intent on. Today: 0, 0, unrecorded.
5. **Gate and tracker integrity:** count of task IDs merged in git log versus ticked in `docs/research/tasks/*.md`, and count of milestone gates whose criteria are demonstrably met. Today: F tasks at least 6 merged but unticked; M0 and M1 gates unmet on paper.

(Optional sixth: time-to-first-verdict from a clean machine, measured by a CI job that builds the Compose stack; currently unmeasured.)

### 6. What would make a skeptical maintainer or researcher dismiss this project

Open-source maintainer:
- "There is no LICENSE file." (Immediate stop.)
- "It says verifies agent code, but the default verdict is test selection plus 'upload your CI results'. Where is the intent part?"
- "I installed it and my PR said `insufficient_evidence`. Then CI passed and the check still says so."
- A Docker build of several minutes, a hand-made GitHub App, and no published CLI, Action or image.
- Capstone diary and generator script in the repo root; Gemini dependencies in a tool whose docs say code stays local.
- A repository whose commit history is dominated by CI, audit baselines and templates, with a 4,000-line research plan and no tamper rule yet, where Verik and SlopGate ship tamper rules today.
- Bus factor of one active author plus AI-assisted commits, with an IP question open.

Researcher / reviewer:
- "Criterion-to-evidence mapping and mutation-based test strengthening both exist; the combination is claimed but nothing is implemented, and there are no results."
- "Your primary label comes from a mutation-based strengthening method that is close to your own predictor; this is circular unless shown otherwise."
- "Extraction and linking quality are measured on synthetic data only; criteria on SWE-bench issues are not PR acceptance criteria."
- "The main baseline (AgentProof-style) is re-implemented from a README of an unlicensed 0-star repository."
- "A pre-registration that is not frozen, for experiments that cannot yet run, with a protocol this elaborate, reads as planning in place of evidence."
- "The only measured results are a 120-mutant self-evaluation on the authors' own code."
- "Process-aware claims depend on trajectories you do not have; AgentLens' code was not released."

### 7. Items I could not verify (explicit)

- Whether `make dev` works from a clean clone; whether the dev stack was ever run end to end on a live GitHub installation (F-06 evidence).
- Contents of the capstone `.docx`, and what `apps/dashboard/components/interactive-graph.tsx` renders for AI-pruning.
- CI job details (`.github/workflows/ci.yml` was only listed, not read in full) and whether CI currently passes on `develop`.
- Whether the opt-in LLM text shown to users discloses file-path egress.
- The exact effort split (the 47/173 keyword count is a rough heuristic, not a hand classification).
- Hand-checked task `Depends on` lines for the ordering in 4.2.

---

## Entry 2026-11-02 (later): status after the Verdict v2 alpha integration

Evidence: branch `feature/verdict-v2-integration` (not yet merged to `develop`); acceptance test `apps/worker/tests/test_verdict_v2_acceptance.py`; DEC-027 and DEC-028.

- **What changed against the 2026-11-02 review above.** The "intent does not reach the verdict" gap is closed behind a flag: with `RADIUS_FEATURE_VERDICT_V2=on` the PR comment and Check Run show per-criterion states, the unproven intent mass and tamper findings, and are updated in place after CI uploads (shadow mode only stores). The default stays `off`; with it off v1 output is unchanged (tests compare it).
- **Measured, not claimed.** On the 8 F-14 fixtures the real pipeline (LK-01..04, VS-04 relevance, EV-02 tamper, EV-06/07/08, VD-01..03) reproduces the design expectations in gold mode (hand-fed links) to 0.001 and reproduces every PR verdict in auto mode except fixture 01, where conservative criterion-to-test relevance gives `insufficient_evidence` instead of `verified` (never the unsafe direction). Six fixtures differ in at least one auto-mode criterion state; each is listed with its reason in `KNOWN_AUTO_DEVIATIONS`. Eight fixtures is a sanity check, not an evaluation: no precision or recall claim follows.
- **Decision recorded (DEC-028).** A guarded import that cannot be verified offline is `medium` (`needs_review`); only a registry miss is `high` (`failed`).
- **Still unverified.** Live GitHub (a fake client was used), a browser (the dashboard panel has unit tests only), PostgreSQL (SQLite in tests; Postgres tests are opt-in), calibration of every threshold, and any non-Python language.

### Actions taken on the 2026-11-03 findings 2 to 5 (honesty and author trust)

Branch `feature/verdict-v2-honesty-author-trust` (DEC-029, `docs/security/VERDICT_V2_THREAT_MODEL.md`): the Check Run title carries "alpha - static evidence only - uncalibrated"; the Check Run is `neutral` for every verdict unless `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS=strict` (`failure` only for R1a/R1b/R1c); `PROVEN` is shown as `SUPPORTED` and `verified` as "Supported by static evidence (alpha)", with a disclaimer on the first line of the comment; criteria and hints carry provenance tags and author-only `tests:` hints are capped at 0.7 (flag and reason `author_supplied_hint`). Not done: no calibration or held-out set (finding 3 stands), no per-criterion base-spec comparison, no third-party issue trust, no recorded confirming actor. The thresholds are still the ones fitted to the 8 fixtures.

