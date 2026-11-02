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

---

## Entry 2026-11-02 (docs pass): doc and code mismatches from the first review

Scope: documentation and one small flag; verified against the code on branch `docs/truth-and-operator-docs`. No gates were changed.

| Mismatch in section 4.3 | State now |
|---|---|
| README and CHANGELOG said a flaky test "is treated as a failure" | Fixed. Both state the real defaults: reruns off (`WORKER_TEST_RERUNS=0`), `WORKER_FLAKY_POLICY=exclude` makes a flaky test neither pass nor fail and blocks `verified`; `fail` counts it as a failure. |
| README said contribution and security files "are being added", linking "planned", ingestion "not built", licence pending | Fixed. README maturity table now lists intent ingestion (flag off, not live-validated), linking libraries, the flagged-off steps and the Verdict v2 alpha; Apache-2.0 is stated; contribution and security files are linked. |
| F-05, F-06, F-07, F-10, F-13, F-14, F-15 (and F-02, F-03) unticked though merged | Ticked with commit references; F-03 and F-06 are `[~]` with the open part stated (capstone decision; no recorded live GitHub run). QS-05 ticked. A stray duplicate `LK-05 [x]` heading that held LK-04's notes was removed and LK-05 is `[~]` (alpha in-memory scope only). PRD-03 to PRD-08 and PRD-11 ticked in the backlog. |
| Gemini pruner and dependencies contradict DEC-021 | Partly fixed. The pruner now needs the explicit opt-in `RADIUS_FEATURE_GEMINI_PRUNER=true` as well as `GEMINI_API_KEY` (default off, tested); `docs/DEPLOYMENT.md` and `docs/security/PROMPT_INJECTION.md` state that it sends code and diffs to Google and is outside the egress policy. **Still open:** `google-genai` and `google-generativeai` remain core dependencies; moving them to an extra changes `uv.lock`. |
| M0 and M1 gates | Not changed. The live GitHub App run (F-06) and real gold data (IN-09/IN-10) are still missing. |
| Capstone `.docx` and generator in the repo | Left in place (owner decision pending, PRD-09). |

Also added: `docs/operations/` (PRD-17) with a configuration reference generated from the settings classes and checked by `tests/test_config_reference.py`, so the environment variable documentation can no longer drift silently. A similar automated check for task checkboxes versus merged task ids (review item 10) is still not built.

## Entry 2026-11-03: second independent review

Reviewer stance: independent, fresh read of `origin/develop` at commit `8c84a99` (merge of PR #100, Verdict v2 alpha). I formed conclusions from the code first and then checked them against the first review; where I agree I say so with my own evidence. No builds, Docker, live GitHub, test runs or writes were used (only read-only `gh` listing); "unverified" marks anything I could not check. Counts are `grep`/`wc` and are rough size signals. Test counts are `def test_` occurrences, so parametrised cases are under-counted.

**Headline.** The first review's central complaint (the differentiators have zero code and the verdict ignores intent) is **substantively addressed**: about 30,000 lines landed through PR #100 (plus earlier sub-PRs) that put intent, tamper rules, assertion strength and per-criterion support into a verdict that is computed, stored, served, rendered and re-published after CI upload. That is real progress and on-thesis. But (a) it is dark by default and needs several manual preconditions, (b) in its only realistic mode (no hand-written hints) it produced **no `verified` verdict on any of the 8 fixtures**, (c) its thresholds were set by eye on those same 8 hand-written fixtures and then those fixtures became the acceptance test, and (d) the cheap credibility items from the first review (F-06 live run, gold data, Gemini, capstone files, README contradictions, tracker hygiene) were mostly not done while hardening work continued. The risk has shifted from "no differentiator" to "a differentiator that looks more validated than it is".

### 0. Objective counts (read-only, at `8c84a99`)

| Metric | Value | Note |
|---|---|---|
| Commits on `origin/develop` | 350 total, 246 non-merge | first review: 257 / about 173 |
| PRs on GitHub (`gh pr list --limit 300`) | 74 merged, 5 open, 98 closed unmerged | why 98 were closed unmerged is unverified |
| Commit types, last 150 non-merge | feat 63 (42%), docs 42 (28%), build 12 (8%), test 11 (7%), fix 11 (7%), ci 7 (5%), chore 3, refactor 1 | first review (about 173): 73 feat, 43 docs, 22 fix, 10 test, 9 ci, 9 build, 9 chore |
| Share of last 150 non-merge commits touching differentiator paths (`packages/{evidence,confidence,linking}`, `analysis/tamper`, `verdict_v2`, `assertions`) | 51 of 150 = 34% (64 of 190 over 30 days) | first review: about 0%. The biggest positive change. |
| Same window, commits touching CI/infra/security/deps/community paths | 37 of 150 = 25% | first review estimated 30-40% |
| Same window, commits touching `packages/intent` | 24 of 150 = 16% | none since the first review (`git log --since=2026-11-02 -- packages/intent` is empty) |
| Python test functions in packages and apps | 2,365 (api 256, worker 217, analysis 191, confidence 86, evidence 269, github 205, graph 47, intent 371, linking 309, parser 46, repository 21, shared 68, testing 279) | plus 405 in root `tests/`, `benchmarks/`, `scripts/`, and 99 dashboard node tests in 11 files |
| Non-test Python LOC | about 69,600 (intent 10,971; testing 9,908; analysis 9,037; api 7,694; linking 5,666; worker 5,314; shared 4,316; github 4,274; evidence 3,502; confidence 2,746; parser 2,609; graph 2,101; repository 1,478); dashboard TS/TSX about 8,600; test Python LOC about 47,700 | test to source about 0.69 |
| Code that decides Verdict v2 | `packages/evidence` 3,502 + `apps/worker/.../verdict_v2` 2,968 + `confidence` verdict_v2 + `github` verdict_v2 | the verdict path is no longer the smallest package |
| `RADIUS_FEATURE_*` flags | 7 (`SYMBOL_IMPACT`, `SYMBOL_CHANGES`, `COVERAGE_CONTEXTS`, `TAMPER_RULES`, `ASSERTION_EXTRACTION`, `INTENT_INGESTION`, `VERDICT_V2` three-valued); **all default off** | `apps/worker/src/radius_worker/config.py`, `apps/api/src/radius_api/config.py` |
| Other off-by-default capability switches | `WORKER_TEST_EXECUTION_MODE=disabled`, `WORKER_TEST_RERUNS=0`, `RADIUS_LLM_INTENT_ENABLED=false`, `RADIUS_LLM_LINK_RERANK_ENABLED=false`, `RADIUS_INTENT_ALLOW_CROSS_REPO=false`, tracing and metrics off | `.env.example`, configs |
| Default-on additions | rate limiting, security headers, body-size limits (PRD-11) | `apps/api/src/radius_api/config.py` |
| Largest single PR | #100: +30,321 / -120, 120 files | others: #92 +6,386 (39 files), #98 +4,821 (72), #96 +4,197 (17), #99 +2,103 |
| Real (non-synthetic) gold PRs | 0 (`benchmarks/gold/README.md`) | unchanged |
| Recorded live GitHub App runs | 0 (`docs/github-app-validation/evidence/` empty; F-06 still `[ ]`) | unchanged |
| Migrations | 14 files; 0013 `verdict_v2` and 0014 `verdict_v2_requests` new; CI runs `alembic upgrade head` only | `.github/workflows/ci.yml` |
| Repository | PUBLIC, Apache-2.0 detected by GitHub | was no licence |
| Latest CI on `develop` | CI, Security, CodeQL, Coverage success; Scorecard failure | `gh run list`; Scorecard is informational |

### 1. Delta since the last review

| Item | First review | Now | Verdict |
|---|---|---|---|
| Tamper rules (EV-02) | none | `packages/analysis/src/radius_analysis/tamper` (9 rule modules, configurable severities, `scripts/tamper_eval.py`); runs inside v2 Stage A | closed; no measured false-positive rate on real code |
| Assertion extraction (LK-04) | none | `packages/testing/.../assertions` | closed |
| IEG builder (LK-05) | none | `packages/evidence` | closed |
| Evidence strength `q(e)`, `a_static`, freshness, lite independence | none | `packages/evidence` (static only, no mutation) | closed for the alpha |
| Criterion-to-test relevance, link-chain confidence | none | `packages/linking` (VS-04, LK-06) | closed; lexical |
| Verdict v2, `needs_review`, justification tree | none | `packages/confidence/.../verdict_v2`, flag off | closed behind a flag |
| PR comment v2 and republish after CI | none | `packages/github/.../verdict_v2`, outbox table | closed for v2 only; v1 still stale |
| Licence | missing | Apache-2.0 | closed |
| Container and HTTP hardening | n/a | PRD-08, PRD-11 | added; not on the first review's priority list |
| Live GitHub App run (F-06) | not recorded | not recorded | open |
| Real gold set (IN-09/10) | none | none | open |
| Gemini dependency and docs | present | present | open |
| Capstone files in tree | present | present | open |
| README contradictions | several | fewer, still wrong in five places (section 4.3) | partly open |
| Pre-registration | draft | draft; the `alpha-static` amendment promised by D17 is not written | open |
| Calibration, process verification, triage, manager, CLI/MCP/published Action | missing | missing | intentionally deferred |

### 2. Traffic-light table

Status: shipped / dark (built, not on the default path) / designed / missing. Alignment: green matches the vision, yellow partial or misplaced, red absent or contradicting.

| Capability | Vision requirement | What exists today (path) | Default | Tested how | Status | Alignment |
|---|---|---|---|---|---|---|
| Graph-driven test selection, v1 verdict | Cheap first value, abstain when unproven | `packages/{analysis,graph,testing,confidence}`, orchestrator | on | unit tests; 120-mutant self-evaluation on Radius's own code | shipped | green (honest, but not the differentiator) |
| Intent ingestion from the PR (title, body, issues, commits, `.radius/intent.yml`) | Intent as input | `apps/worker/.../intent_ingestion.py`, `packages/github/.../intent_*.py` | **off** (`RADIUS_FEATURE_INTENT_INGESTION`) | fixtures and fakes; no live run | dark | yellow: the flag text says "OFF until the live F-06 validation" and F-06 is not done |
| Criterion extraction (deterministic; optional LLM) | Confirmable criteria | `packages/intent`; default extractors `Manual` + `Deterministic` | deterministic runs when ingestion is on; LLM off | strong unit/fuzz tests; **no real gold data** | shipped as a library; extraction quality unmeasured | yellow |
| Tamper rules (EV-02) | Detect weakened or faked evidence | `radius_analysis.tamper`; runs in v2 Stage A regardless of `RADIUS_FEATURE_TAMPER_RULES` | v2 only | 8 fixtures, `tamper_eval.py`, unit tests; severities are "assumed" (D12) | dark | green on direction, yellow on validation |
| Assertion extraction and strength `a_static` | Know what a test asserts | `radius_testing.assertions`, `radius_evidence` | v2 only | fixture-per-kind tests | dark | yellow (static only; max over assertions is optimistic by design) |
| Criterion-to-symbol and symbol-to-test links, relevance | Link criteria to code to tests | `packages/linking`, `radius_testing.linking` | v2 only | 8 fixtures, `relevance_eval.py` sanity numbers | dark | yellow: relevance is lexical and "useful but not reliable" (design 3.6) |
| Evidence strength `q(e)`, support `S(c)`, UIM, criterion states | Measured strength, not "a test exists" | `packages/evidence` | v2 only | unit and property tests; gold-mode equality on 8 fixtures | dark | yellow: formulas exist, parameters are hypotheses |
| Mutation-based `d_mut` | Fault-detection power | none in product (benchmark harness only) | n/a | n/a | missing (deferred by decision) | red, correctly deferred |
| Verdict v2 (4 states, rules R1-R4, justification) | Auditable per-criterion verdict | `packages/confidence/.../verdict_v2`, `apps/worker/.../verdict_v2/`, API route, dashboard panel | **off**; `shadow` stores only; `on` replaces v1 | acceptance test over 8 fixtures (gold + auto), SQLite, fake GitHub | dark | yellow (section 4.1) |
| PR comment and Check Run v2, republish after CI | Criteria matrix in the PR | `packages/github/.../verdict_v2/markdown.py`, `publish.py`, migration 0014 outbox | off | golden markdown, escaping tests | dark | green on design; **never seen on a real PR** |
| Republish after CI for v1 | Fresh verdict | not done (README says so) | n/a | n/a | missing | yellow |
| Policy engine and waivers (VD-04/05) | Org enforcement | none | n/a | n/a | missing | red, deferrable |
| Calibration, abstention band (CA-*) | Calibrated trust | none; `needs_review` only via rules R3a-R3c | n/a | n/a | designed | red; correctly labelled uncalibrated |
| Process verification (PR-*) | Trajectory signals | none | n/a | n/a | designed | red, deferred |
| Review triage (TR-*), manager layer (MG-*) | Risk-ranked hunks, portfolio | none | n/a | n/a | designed | red, deferred |
| Distribution: CLI, MCP, published Action, images | The adoption wedge | only local composite action `.github/actions/radius-verify`; nothing published | n/a | n/a | designed | red |
| Symbol-level selection, coverage contexts, symbol changes (F-08, LK-01/03) | Better selection | worker flags | off | ground-truth test, Python only | dark | yellow |
| LLM egress controls | Off, opt-in, no code leaves | `radius_shared.llm_guard`, `EgressPolicy`, `.env.example` | off | 98-case injection corpus with stub models | shipped | green |
| Gemini pruner (legacy) | Remove or gate (DEC-021) | `google-genai`, `google-generativeai` in root `pyproject.toml` lines 32-33; `SemanticPruner` constructed in `orchestrator.py` (about line 593) and reachable only via `_run_semantic_cpg_poc`, which only tests call; `GEMINI_API_KEY` still documented in `docs/DEPLOYMENT.md` | not on pipeline | n/a | present | yellow to red: contradicts "code stays local" if a key is set |
| Security hardening (HTTP, containers, CodeQL, Trivy, Dependabot, DCO, scorecard) | Production-grade OSS | 9 workflows, API middleware, Dockerfiles | on | CI | shipped | yellow: good work, but a quarter of recent commits |
| Pre-registration and datasets | Falsifiable claims | `PREREGISTRATION.md` v0.2-draft, pinned manifests | n/a | n/a | docs | green; not frozen; no `alpha-static` amendment |
| Product vision doc | One statement of purpose | `docs/PRODUCT_VISION.md` unchanged (pre-intent framing, footer cites DEC-006..015) | n/a | n/a | stale | yellow |

### 3. The user's actual experience on a PR today, by flag state

Traced from `apps/worker/src/radius_worker/{runner,config,intent_ingestion}.py`, `apps/worker/src/radius_worker/verdict_v2/*`, `apps/api/src/radius_api/routes/tests.py`, `packages/github/src/radius_github/verdict_v2/*`, `docs/verdict-v2.md`. Nothing was run; unverified end to end.

**Before any of this exists.** `make dev` (several minutes, Docker) brings up the stack but does not connect GitHub. The user must create a GitHub App by hand (checks write, pull requests write, contents read, issues read; `docs/github-app-validation/RUNBOOK.md`), set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, the webhook secret and URL, and install it on a repository. That App has no recorded live run in this repo (F-06 `[ ]`, empty `evidence/`). The README links `docs/verdict-v2.md` only from the maturity table.

**State A: flag `off` (default).** v1 pipeline: HMAC webhook, job, in-progress Check Run, orchestrator (parse, graph, test selection, test execution disabled by default), v1 verdict, comment with verdict, "uncalibrated" heuristic score, blast-radius table and selected tests. With no CI upload the verdict is `insufficient_evidence`. If the user wires `scripts/radius_ci.py` or the composite action and uploads, the API recomputes v1 but does **not** republish the comment or Check Run (README maturity row), so GitHub keeps showing `insufficient_evidence` after CI passed. The v2 route answers 404 `disabled`. Intent ingestion returns early when its flag is false (`ingest_intent_best_effort`). Nothing changed for the default user since the first review.

**State B: `RADIUS_FEATURE_VERDICT_V2=shadow`.** After the orchestrator and before the v1 publish, `run_verdict_v2_for_analysis` (`runner.py` around line 244) runs Stage A (re-runs LK-01 symbol changes, EV-02 tamper, LK-02, LK-03, LK-04, VS-04 relevance from the checkout; 120 s total, 60 s per producer; `collect.py`), then Stage B, and stores a bundle in table `verdict_v2`. v1 is still the only thing on GitHub. The API serves `GET /api/v1/analyses/{id}/verdict-v2`; the dashboard panel is marked "shadow". If intent ingestion is off (default) there is no snapshot and the stored result is `insufficient_evidence` (R2d). A user who sets only the v2 flag gets a useless shadow result; `docs/verdict-v2.md` says intent ingestion is needed, but I found no runtime warning (unverified).

**State C: `on`.** Same computation, then `v2_replaces_v1` (`runner.py` around line 689) publishes the v2 comment and `Radius confidence` Check Run instead of v1, falling back to v1 on any v2 error or stale head. The first publish, with no CI results yet, is the neutral "Awaiting CI test results" comment (rule R2p). When CI uploads per-case JUnit/JSON, `tests.py::_request_verdict_v2_republish` writes an outbox row; the worker consumer re-scores without a new clone and updates the same comment and Check Run within one poll interval; replay is a no-op by digest; a result for a non-head commit is never published.

**What must be configured for a meaningful v2 verdict (none is default):**

1. `RADIUS_FEATURE_VERDICT_V2` on **both** API and worker (separate config fields, same variable; a mismatch gives a half-working system, inferred, unverified).
2. `RADIUS_FEATURE_INTENT_INGESTION=true` plus GitHub App credentials in the worker, otherwise there are no criteria. Criteria come from PR title and body, linked issues, commit messages and `.radius/intent.yml`, the last read **at the PR head SHA** (`packages/github/.../intent_sources.py`, `ref=ctx.head_sha`), through the deterministic extractor (LLM extraction off).
3. CI that runs the tests and uploads **per-case** results bound to the head SHA (`POST /api/v1/analyses/{id}/tests/results?commit_sha=`). Worker-run sandbox results are aggregate only and unused in the alpha (D7).
4. For a correct PR to reach `Verified`, a hand-written `.radius/intent.yml` with `tests:` hints (section 4.1 item 1).
5. A Python repository; other languages give "analysis incomplete" (R2d).
6. `RADIUS_FEATURE_TAMPER_RULES` and `RADIUS_FEATURE_ASSERTION_EXTRACTION` are **not** needed: Stage A runs its own producers. Those flags only affect the orchestrator path, so an operator reading the flag list will wrongly think they must enable them.

**What the user sees.** One PR comment headed `Radius verdict (v2 alpha): <verdict>`, a summary line (criteria proven, unproven intent mass vs 0.20, intent coverage, "static assertion strength only (no mutation testing)"), a one-sentence "Why", a criteria table (state, support x / 0.50, evidence), "What to do next", collapsible per-criterion evidence, tamper findings, uncovered changes, a collapsed legacy v1 score, and a footer "algo verdict-v2-alpha-1 | profile alpha-static (thresholds uncalibrated)". Check Run: `success` only for a non-pending `Verified`, `failure` for `Failed`, `neutral` otherwise (`markdown.py::check_conclusion`). The Check Run title (`Radius v2: Verified (2/2 criteria proven)`) does not carry the static-only or uncalibrated caveat; only the body does.

**Friction, by severity.** (1) Two flags, a hand-made GitHub App, CI upload and hint files before a correct PR can be `Verified`. (2) Ingestion is documented "OFF until live validation", which has not happened. (3) The criteria shown (`C1`...) come from heuristic extraction of PR prose with no gold-measured precision, so a bad extraction yields a confident-looking table. (4) There is no example of a real PR with this comment, only golden strings. (5) The README text and mermaid note still say intent is "not in the verdict yet".

### 4. Findings

#### 4.1 Evidence honesty and validity of the v2 alpha

1. **The realistic path never says `Verified` on the fixtures.** `apps/worker/tests/test_verdict_v2_acceptance.py` records in `KNOWN_AUTO_DEVIATIONS` that in auto mode (no hints) the one fixture designed to be `verified` (01, correct and strong tests) becomes `insufficient_evidence`. Six of eight fixtures differ from the design in at least one criterion state (01, 02, 03, 05, 06, 08). The direction is right (a test asserts auto may be more cautious, never more optimistic), but the user-visible path today is "almost always not verified", the same first impression as v1 with more machinery.
2. **"Gold mode" is not validation.** `scripts/verdict_v2_run.py` defines gold mode as the fixture's `expected.json` links fed in as `.radius/intent.yml` hints. Matching the design "to 0.001" there shows the formulas implement the spec, not that the spec is right. The earlier log entry's "reproduces ... to 0.001" should be read that way; only auto mode carries information.
3. **Fixture overfit risk is high and mentioned only as risk R10.** `VERDICT_V2_SLICE.md` finding F6 says the DESIGN defaults (`cap_static` 0.4, `tau_support` 0.6) could never produce `verified` on the fixtures, so the alpha profile uses 0.6 / 0.5 (`packages/evidence/src/radius_evidence/domain/config.py`: `cap_static 0.60`, `tau_support 0.50`, `uim_max 0.20`, `tau_weak 0.20`, `iota_unknown 0.8`). The `l_cs` saturation gate (0.20/0.40) was set from the top-1 link scores measured on the same fixtures (0.28 to 0.91, F5, section 3.5), the `type_check` vs `none_check` weights were split because "the fixtures disagree with each other", and a remaining mismatch (08 C2 `proven` vs `weak`) was handled by proposing per-profile expectations "rather than lowering thresholds to fit one fixture". The fixtures are eight hand-written, one-language, toy-sized cases written by the same team for the same design. R10 ("tuned by eye on 8 hand-written fixtures", mitigation "labelled and versioned") is honest, but the label does not reach the Check Run title. I would defend the alpha as a demonstrator; I would not defend any threshold as evidence. No precision, recall or false-verified rate exists, and with n=8 and no held-out set none can.
4. **Verdict word versus evidence.** `Verified` can rest on one test per criterion with "assertion strength 1.00 capped at 0.60", independence 0.8 for tests written in the same PR by an unknown author (agents only get 0.6 with commit trailers, D13), no mutation and no check that the test could fail. The comment hedges in the "Why" line and footer and `docs/verdict-v2.md` says `Verified` does not mean correct. But the label `PROVEN` for support 0.60 from one static test, and a green Check Run, are stronger than the evidence; a green check is what branch protection and busy reviewers read.
5. **The author controls the intent and the hints.** Criteria come from the PR body the author wrote, and `.radius/intent.yml` (whose `tests:` and `paths:` hints saturate link strength to 0.95 to 1.0) is read from the PR head. An agent or author can state easy criteria and point them at a test it added. Tamper rules and static strength mitigate some of it, but nothing compares against intent from a source the author does not control (base-branch `intent.yml`, an issue authored by someone else, reviewer confirmation). I searched `docs/security/*`, the design and `verdict-v2.md` for "self-attest", "gaming", "author-controlled" and found no discussion. This is the most important unmodelled adversary for a tool whose pitch is verifying agent work.
6. **Circularity in the tamper and relevance checks.** Tamper severities were "assumed" in the fixtures first, then confirmed as defaults (D12); the fixtures that exercise the rules were authored to trigger them. No run on a real repository's history estimates false positives. DEC-028 shows the right reflex (downgrade a rule that would falsely accuse) but it was found only because a fixture exposed it.
7. **Research validity (carried over, still true).** RQ1 has zero real gold PRs; the RQ2/3 primary label `L_ABS` comes from a mutation-based method close to the predictor, while the alpha does no mutation, so UIM from static assertion shape is a different construct from the pre-registered one (D17 promised an amendment; not written); B4 is a re-implementation from a README; the pre-registration is unfrozen. Positive: shadow mode is a free hook to collect real v2 outputs, and every stored bundle carries `profile` so alpha data is not pooled with confirmatory data. Nothing is collecting that data yet.

#### 4.2 Scope, drift and PR size

1. **PR #100 is +30,321 lines in 120 files, one review unit.** It merged a design, two migrations, a renderer, an outbox, an API route, a dashboard panel and a worker runtime. Sub-pieces had landed earlier (#92, #96, #98, #99), which softens this, but the integration PR is what a reader must trust, and at that size the merge review was in practice a CI pass.
2. **Hardening versus differentiators.** 34% of the last 150 non-merge commits are differentiator work (up from about 0%). 25% still touch CI/infra/security/community paths, and PRD-08 (#87, Trivy) and PRD-11 (#91, CSP and rate limits) merged after the first review advised pausing new hardening (partly timing: they were in flight). PRD waves 2 to 5 (release, Helm, docs site) have not started, which is right.
3. **Machinery before data.** LK-06 (#93) built calibration plumbing before any labels exist; `packages/linking` is 5,666 lines and the relevance rule was changed during implementation from a raw BM25 gate to a multi-signal rule (more tunable parameters) for a result shown on 8 fixtures.
4. **Flag sprawl.** Seven all-off flags with non-obvious interactions (v2 ignores the tamper and assertion flags, needs the intent flag, needs the flag on API and worker). No single "enable the alpha" switch and no startup check for inconsistent combinations (searched config and runner; none found).
5. **Duplicate computation.** Stage A re-runs LK-01 and tamper from the checkout instead of sharing orchestrator results (design 2.3). Fine for an alpha; matters on large repos.

#### 4.3 User-facing text that overclaims or contradicts

| Where | Text | Problem |
|---|---|---|
| `README.md` mermaid note and "Intent layer (M1)" row | "does not feed the verdict or the PR comment yet", "Not in the verdict", "automatic ingestion from the PR is not built" | Contradicted by the v2 row in the same table and by merged `intent_ingestion.py` (flag off) |
| `README.md` "Criterion-to-evidence linking, mutation-based evidence strength, calibration: planned" | | linking is built (dark); mutation and calibration are not |
| `README.md` flaky row and `CHANGELOG.md` | "a flaky test is treated as a failure" | Default `WORKER_FLAKY_POLICY=exclude`; flaky blocks `verified`; reruns default 0. Unchanged since the first review |
| `README.md` repository layout | package list | omits `evidence` and `linking` |
| `README.md` "Check run ... not re-published" | | true for v1, false for v2 |
| v2 comment and Check Run | `PROVEN`; green Check Run on `Verified`; caveat in body only | see 4.1 item 4 |
| `docs/PRODUCT_VISION.md` | "Can this change be merged safely?" framing | two competing statements of purpose remain |
| `CHANGELOG.md` | "recorded decisions DEC-006 to DEC-025" | stale (DEC-028) |
| `SECURITY.md`, `CODE_OF_CONDUCT.md` | `security@<owner-configures-domain>`, `conduct@<owner-configures-domain>` | A public security policy whose fallback address is a placeholder |
| `docs/research/PRODUCT_AND_GTM.md` | "quantifies evidence strength" vs competitors | Today strength is static assertion shape; the doc is labelled hypotheses but the wording will be quoted |

Credit: `docs/verdict-v2.md` is candid about limits (alpha, static only, Python only, uncalibrated, not live- or browser-validated, hint-dependent) and the README marks v2 "alpha, off by default". The overclaim risk sits in the artifact users actually see (the PR check), not in the docs.

#### 4.4 Security and privacy

1. **Untrusted PR text in the comment.** Good: criterion text, test names, paths and tamper snippets are escaped for @mentions, issue refs, links, images, HTML and bidi characters; 60,000-character cap; golden tests. Residual: tested on strings, not against GitHub's real markdown rendering (unverified); attacker-chosen criterion text is amplified into a bot comment under the App's identity.
2. **Untrusted code on the worker.** Stage A analyses PR code in-process (not in the sandbox): `ast`, tree-sitter, tamper rules, assertion extraction over up to 5,000 `.py` files of up to 1 MB (`sources.py`: `MAX_FILES`, `MAX_FILE_BYTES`). Timeouts use a worker thread (`collect.py::guarded`), and Python cannot kill a running thread: `pool.shutdown(wait=False, cancel_futures=True)` abandons it, so a timed-out producer can keep consuming CPU and memory. Not measured; a denial-of-service concern on shared workers.
3. **LLM egress.** Defaults off and gated; the v2 verdict path makes no LLM calls. The link re-ranker still sends symbol names and paths when enabled (DEC-026); I could not confirm the opt-in text says so (unverified).
4. **Gemini legacy path.** Still a core dependency; `orchestrator.py` reads `GEMINI_API_KEY` and constructs `SemanticPruner`, which sends source to a third party; reachable only via a test-called method, so latent, not live. `docs/DEPLOYMENT.md` still documents the key although DEC-021 said to remove or gate it. Open since the first review.
5. **Secrets and keys.** Server-side dashboard proxy, HMAC webhooks, gitleaks, `redact_secrets`. No new key-handling problem found in the v2 code; I did not audit the new `proxy-verdict-v2` route beyond noting it has a test.
6. **Tenant isolation.** v2 store, route and publisher carry `organization_id` and the integration PR claims isolation tests (not independently verified); the dedicated QS-04 suite is still not done.
7. **Public repo contents.** The repository is now public with Apache-2.0. Root `Radius_Capstone_Project_Diary_FALL_2026.docx` (copy in `docs/capstone/`) and `generate_capstone_diary.py` remain; contents not inspected. DEC-018's owner actions (second author's consent, sponsor/IP check) cannot be seen as completed; with the repo public and licensed these are live, not hypothetical.

#### 4.5 Operational concerns

- **Migrations.** 0013/0014 are plain tables (bundle JSON, request outbox). CI only runs `alembic upgrade head` on a fresh database: no upgrade-from-previous test, no downgrade test. Tests use SQLite; Postgres tests are opt-in, so JSON and upsert behaviour on the real database is unverified.
- **Memory.** Source reading allows up to 5,000 files x 1 MB in memory; bundle and comment are capped; I found no memory limit for the worker in `docker-compose.yml` (other deployment manifests not checked).
- **Republish consumer.** Runs in the worker poll loop and catches its own errors (`runner.py::_process_verdict_v2_requests`). Stale-head, superseded-analysis and live-head checks are thoughtful.
- **CI.** `ci.yml` still has the F-07 adversarial-suite step commented out as a PLACEHOLDER saying the files do not exist; the suite exists (`packages/testing/tests/test_sandbox_adversarial.py`) and probably runs through the general test step, but the comment is stale and I did not verify it runs. No CI job builds the Compose stack or runs a browser test.
- **Trackers.** `docs/research/tasks/F-foundations.md` is still 7 done / 9 open although F-05, F-07, F-10, F-14, F-15 and others are merged; new EV, VD and LK items are ticked accurately with status notes. The rule works for the active stream and not for older items.

### 5. Did the first review's findings get addressed?

| First-review finding | Status | Evidence |
|---|---|---|
| Differentiators have zero code; intent does not reach the verdict | **Addressed behind a flag** | PR #100; `docs/verdict-v2.md`; `verdict_v2_mode` default off in both configs |
| Tamper rule engine missing | **Addressed** | `packages/analysis/.../tamper`, PR #92; severities still assumed |
| IEG (LK-05), assertion extraction (LK-04), EV-01/06/07/08 missing | **Addressed (alpha, static)** | `packages/evidence`, `packages/testing/.../assertions` |
| Per-criterion verdict, `needs_review`, justification tree missing | **Addressed (alpha)** | `radius_confidence.verdict_v2`; rules R1-R4 |
| Verdict stale after CI upload | **Addressed for v2 only** | `tests.py::_request_verdict_v2_republish`; README still says v1 is not republished |
| No licence | **Addressed** | `LICENSE`, `NOTICE`; GitHub reports Apache-2.0 |
| Owner IP actions (second-author consent, sponsor, AI-assisted commits) | **Not evidenced** | nothing in `docs/production-readiness/OWNER_ACTIONS.md`; unverifiable from the repo |
| Default first run yields `insufficient_evidence` | **Not addressed; arguably deeper** | test execution still disabled; v2 needs several manual preconditions |
| Live-validate GitHub App (F-06); decide intent-ingestion default | **Not addressed** | empty `docs/github-app-validation/evidence/`; flag text unchanged |
| Real gold set, publish RQ1 numbers (IN-09/10) | **Not addressed** | `benchmarks/gold/README.md` |
| Thin demo on scripted PRs (PL-04) | **Partly** | `scripts/verdict_v2_run.py` prints states and markdown for the 8 fixtures; no live repo with real PRs |
| Reconcile docs (README maturity, flaky wording, trackers, vision) | **Partly** | v2 row and licence fixed; flaky wording, intent rows, layout list, `PRODUCT_VISION.md`, F tracker unchanged |
| Remove Gemini pruner and dependencies | **Not addressed** | `pyproject.toml` lines 32-33; `docs/DEPLOYMENT.md` line 82 |
| Remove capstone artefacts | **Not addressed** | root `.docx`, `docs/capstone/`, `generate_capstone_diary.py` |
| Stop adding supply-chain/CI tasks until a v2 slice exists | **Not followed** | PRD-08 (#87), PRD-11 (#91), Trivy workflow; 25% of recent commits |
| Stop extending `packages/intent` | **Followed** | no commits since the review |
| Defer mutation, process, calibration, triage, manager | **Followed** | none started (LK-06 calibration machinery is a partial exception) |
| Stop adding LLM surfaces | **Followed** | v2 has no LLM calls |
| Defer pre-registration freeze and baselines | **Followed**, but the `alpha-static` amendment (D17) is not written | `PREREGISTRATION.md` last changed at v0.2-draft |
| Automated doc/code drift check | **Not addressed** | no script found |

### 6. Prioritized next 10 actions

1. **Make the alpha un-misreadable in the PR.** Put "alpha, static evidence only, uncalibrated" in the Check Run title; make the Check Run conclusion `neutral` for `Verified` until a stronger signal exists; rename `PROVEN` for the alpha (for example `SUPPORTED (static)`). Why: the product principle is honesty and "never turns missing evidence into a pass"; a green check is a pass. Small change in `packages/github/.../verdict_v2/markdown.py`.
2. **Run shadow mode on real PRs and read them.** Do the F-06 live run, enable `shadow` plus intent ingestion on Radius's own repo and one or two external Python repos, and hand-read 30 stored bundles. Why: the only way to learn whether extraction, relevance and tamper are usable; the thesis is untested outside 8 fixtures.
3. **Collect a real gold set (30 to 50 PRs, IN-09/10) and report extraction P/R and criterion-to-test link accuracy, even if poor.** Why: every v2 number depends on extraction and linking measured only on synthetic data.
4. **Freeze the alpha parameters and evaluate on data you did not tune on.** Keep the 8 fixtures as regression tests only; build a held-out set (new fixtures written by someone else, or mined PRs); state a false-verified budget in advance; write the `alpha-static` pre-registration amendment (D17). Why: removes the "tuned on what it is evaluated on" objection.
5. **Fix auto-mode linking, not the thresholds.** Fixture 01 gives `insufficient_evidence` without hints; use the test-to-symbol call path LK-03 already computes, measure on the held-out set, and document `intent.yml` hints as a first-class path with an example. Why: the honest default must be able to say `verified` to a good PR, or the product is v1 with more words.
6. **Model the author-controls-intent adversary.** Read criteria and hints also from the base branch or a linked issue by another author; add a rule for "criteria or hints added in the same PR as the tests they point at"; document the limit. Why: this is the adversarial core of verifying agent code and is currently open.
7. **One-step enablement and misconfiguration warnings.** Log a warning (or health flag) when v2 is on but intent ingestion or App credentials are missing, or API and worker disagree; document that the tamper and assertion flags are not needed. Why: removes most of the friction in section 3; trivial code.
8. **Close the visible credibility gaps:** remove the capstone files; drop or extra-ize the Gemini dependencies and docs; fix the README contradictions in 4.3; replace the `<owner-configures-domain>` placeholders; add a script that fails CI when a merged task ID is unticked. Why: all are visible within five minutes of reading and undercut the honesty principle.
9. **Make the first run produce evidence and republish v1.** Ship a two-line published CI step (or a default sandbox run in the Compose stack) and republish the v1 comment after CI upload by reusing the v2 outbox. Why: "not verified, upload results" plus a stale comment is the worst first impression.
10. **Bound Stage A.** Move its producers to a killable subprocess (or add a hard CPU/memory limit), set container limits, and add a Postgres-backed test for migrations 0013/0014 and the outbox. Why: analysing untrusted code in-process is the likeliest operational failure once the flag is used.

**STOP / defer list.**

- **Stop** further hardening, scanning, community-health or Dependabot-policy work until actions 1, 2 and 8 are done; defer PRD waves 2 to 5 (release pipeline, Helm, docs site, SSO, perf pages, badge).
- **Stop** adding scoring parameters, linkers, signals, relevance rules or states to the alpha before a held-out evaluation exists (action 4); each knob multiplies the fixture-overfit surface.
- **Stop** extending `packages/intent` and calibration plumbing (LK-06 follow-ups, CA-* code) until real gold data exists.
- **Defer** mutation (EV-04/05), policy and waivers (VD-04/05), process verification, triage, manager layer, CLI/MCP, TypeScript/Go/Java evidence, any new LLM feature, and dashboard polish for v2.
- **Defer** pre-registration freeze and baselines B3 to B12; write only the `alpha-static` amendment.
- **Do not** make v2 the default or recommend it as a required check until actions 2 to 5 have reported.

**Five cheap objective signals for the next check.**

1. **Differentiator versus hardening commit share** (`git log --since=30.days --no-merges --name-only`): target differentiator-path commits at least 30%, infra/security/community commits below 15%. Today 34% and 25%.
2. **Real-data counts:** real gold PRs in `benchmarks/gold` (0), external repos with stored shadow bundles (0), recorded live GitHub App runs (0).
3. **Held-out auto-mode outcomes:** correct PRs that reach `Verified` with no hints, and incorrect PRs that do (false-verified). Today 0 of 1 correct on the fixtures, and no held-out set exists.
4. **Default-path reachability:** is `RADIUS_FEATURE_VERDICT_V2` anything but `off` in any shipped compose or example env, and is there a documented one-step enablement? (`docker-compose.yml`, `.env.example`). Today no.
5. **Doc/code integrity:** count of README/CHANGELOG/vision statements contradicted by code (about 8 listed in 4.3), merged-but-unticked task IDs (F tracker: at least 5), open placeholders (`<owner-configures-domain>`: 2).

(Optional sixth: lines changed in the largest merged PR per week; today 30,321.)

### 7. What would make a skeptical maintainer or researcher dismiss this (updated)

Open-source maintainer:

- "The PR comment says PROVEN and the check is green, while the footnote says thresholds are uncalibrated and tests are rated by assertion shape. Which is it?"
- "I wrote `intent.yml` in the same PR as my test and the tool accepted my own hint as proof."
- "To see v2 I need a flag on two services, a hand-made GitHub App, CI uploads and hint files, and the README says intent is 'not in the verdict'."
- "There is no recorded live run and no screenshot of a real PR; the project's own docs say nothing was validated against GitHub or a browser."
- "SECURITY.md's fallback address is a placeholder; a capstone diary and a Gemini dependency sit in a repo that says code stays local."
- "A 30,000-line PR merged as one unit; a quarter of recent commits are CI and scanners."
- "Verik and SlopGate already ship tamper rules; these are in a flag-gated pipeline nobody has run on a real repo."

Researcher or reviewer:

- "Thresholds were set on eight hand-written fixtures and the same fixtures are the acceptance test; 'gold mode' feeds the expected links as hints. This validates the code against its own spec."
- "The only realistic mode fails the one positive example. Where is any precision or recall?"
- "The pre-registered primary label comes from a mutation-based method close to your predictor, and the alpha does no mutation, so the shipped UIM is a different construct from the pre-registered one, with the promised amendment unwritten."
- "Criteria are extracted from author-written prose with no measured accuracy; RQ1 has no real data."
- "The main baseline is re-implemented from the README of an unlicensed repository; the pre-registration is unfrozen and covers experiments that cannot yet run on this pipeline."
- "The gold-patch-free claim (C2) rests on a mutation signal that does not exist in the product."

### 8. Strengths worth keeping

- Honest-by-construction rules: failures first, abstention by default, `needs_review` only via named rules, no LLM in the verdict path, "auto mode never more optimistic" enforced by a test, and DEC-028's refusal to accuse on unverifiable evidence.
- Shadow mode, `algo_version`/`profile` stamping and the outbox are the infrastructure an honest evaluation needs.
- `docs/verdict-v2.md` states its limits plainly; renderer escaping and size caps are careful.
- The sequencing now follows the first review's critical path (tamper, assertions, IEG, support, verdict, comment) in small mergeable pieces before the large integration.

### 9. Items I could not verify

- Any live behaviour: GitHub App, a real PR comment, a browser, PostgreSQL (tests use SQLite).
- Whether the sandbox adversarial suite runs in CI; CI job bodies beyond the names and the commented placeholder.
- Whether the DEC-018 owner actions (second-author consent, sponsor/IP) were completed outside the repository.
- Contents of the capstone `.docx`.
- Why 98 PRs are closed unmerged.
- Whether any startup warning exists for inconsistent v2 flag combinations (none found by search).
- Whether the link re-ranker opt-in text discloses name and path egress.
- Stage A memory behaviour on large repositories.

### Actions taken on the 2026-11-03 findings 2 to 5 (honesty and author trust)

Branch `feature/verdict-v2-honesty-author-trust` (DEC-030, `docs/security/VERDICT_V2_THREAT_MODEL.md`): the Check Run title carries "alpha - static evidence only - uncalibrated"; the Check Run is `neutral` for every verdict unless `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS=strict` (`failure` only for R1a/R1b/R1c); `PROVEN` is shown as `SUPPORTED` and `verified` as "Supported by static evidence (alpha)", with a disclaimer on the first line of the comment; criteria and hints carry provenance tags and author-only `tests:` hints are capped at 0.7 (flag and reason `author_supplied_hint`). Not done: no calibration or held-out set (finding 3 stands), no per-criterion base-spec comparison, no third-party issue trust, no recorded confirming actor. The thresholds are still the ones fitted to the 8 fixtures.

