# Radius Research Design: Intent-to-Evidence Verification

**Status:** Ratified by the owner on 2026-11-02 (see `docs/decisions.md` DEC-006 to DEC-015). Date: 2026-11-02.
**Audience:** every human or AI agent implementing any task in `docs/research/tasks/`.
**Read first:** `docs/AI_CONTEXT.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/audit/RADIUS_AUDIT.md`.

> All formulas, weights and thresholds in this document are **hypotheses with defaults**.
> They are to be tuned and tested by the evaluation plan (`EVALUATION_PLAN.md`), never treated as facts.
> Repo paths are as of 2026-11-02 and come from the audit; verify before editing.

---

## 1. Thesis

A merge verdict should be a statement about **intent**:

> For each thing the change was supposed to do, how much trustworthy evidence do we have that it does it, and how much do we trust that evidence?

Where the field is today:

| Question | Who asks it |
|---|---|
| Does the app work? | TestSprite and other AI test runners |
| Did CI pass / which tests did the change reach? | Radius v1 |
| Did the PR satisfy its stated criteria with *any* passing test? | AgentProof (rule-based) |
| Did the agent tamper with tests or leave suspicious code? | Verik, SlopGate |
| **Is each criterion proven by evidence that could actually have caught a failure, and is the resulting confidence calibrated?** | **Nobody we found (to be confirmed by a proper literature review, task EP-01).** |

Radius already verifies and does not generate code (`docs/AI_CONTEXT.md`). This design keeps that rule: LLMs may *propose* (criteria, links), but the verdict is computed **deterministically from validated evidence**.

**Principle: the LLM proposes, evidence disposes.**

---

## 2. Glossary (use these exact terms in code, DB, API and UI)

| Term | Definition |
|---|---|
| **Intent** | The set of things a change is supposed to accomplish, from all available sources. |
| **Intent source** | Where intent text came from: PR description, linked issue, commit message, `.radius/intent.yml`, agent task prompt, tracker ticket. |
| **Criterion** (`c`) | One atomic, testable statement of intent, with provenance, weight and a testability rating. |
| **Symbol** | A function, method, class or module-level definition (the unit of change and of linking). |
| **Evidence item** (`e`) | A fact produced by execution or analysis: a test result, mutation result, static finding, coverage record, attestation. Always bound to a repo + head SHA. |
| **Link** (`l`) | A typed, confidence-weighted, provenance-labelled edge in the IEG (criterion to symbol, symbol to test, test to result). |
| **IEG** | Intent-Evidence Graph: nodes = criteria, symbols, tests, evidence items, process events; edges = links. Versioned per head SHA. |
| **Evidence quality** `q(e)` | How likely this evidence is to have *failed* if the criterion were broken (0 to 1). |
| **Support** `S(c)` | Aggregate trustworthy evidence for a criterion (0 to 1). |
| **Unevidenced Intent Mass (UIM)** | Weighted share of criteria whose support is below threshold. |
| **Tamper finding** | A deterministic rule hit suggesting evidence was weakened or faked. |
| **Process trace** | Record of how the change was produced (agent actions, test runs, retries). |
| **Trust probability** `P` | Calibrated probability that the change is correct (no defect traced to it within a horizon). |
| **Abstention / `needs_review`** | Verdict state meaning "the system declines to decide; a human must." |
| **algo_version** | Version string stamped on every computed score for reproducibility. |

---

## 3. Data flow (v2 pipeline)

Existing v1 stages are kept; new stages are marked **NEW**.

```
GitHub webhook (PR opened/synchronized/edited, issue edited, check_run)
  -> Idempotency + tenancy resolution                         (exists)
  -> Job enqueue (SQL queue)                                  (exists)
  -> Worker: fetch diff + files                               (exists)
  -> Parse + symbol extraction + CPG                          (exists, to be upgraded: symbol-level)
  -> Blast radius                                             (exists, file-level -> symbol-level)
  -> NEW Intent collection + criterion extraction
  -> NEW Criterion -> symbol linking
  -> Test selection (graph-driven)                            (exists, extend with criterion awareness)
  -> CI result ingestion (JUnit/JSON/coverage/SARIF)          (exists, extend)
  -> NEW Tamper rule engine (diff-level)
  -> NEW Mutation service (changed symbols, sandboxed)
  -> NEW Evidence quality q(e)
  -> NEW Support S(c), UIM, per-criterion states
  -> NEW Process trace ingestion + process signals
  -> NEW Trust probability P (calibrated) + abstention
  -> Verdict v2 (verified | failed | insufficient_evidence | needs_review)
  -> NEW Review triage (risk-ranked hunks, agent re-prompt)
  -> Publish: Check Run + PR comment + dashboard + API       (exists, upgrade)
```

Re-computation triggers: new commit (new head SHA), PR/issue description edit, new CI result upload, new trajectory upload, policy change, waiver. Each trigger creates a new **assessment** row; older rows are retained (audit trail).

---

## 4. Architecture changes

### 4.1 New packages (follow existing domain / application / infrastructure / interfaces layering)

| Package | Responsibility |
|---|---|
| `packages/intent` | Intent sources, criterion extraction, criterion normalization, testability rating, intent snapshots. |
| `packages/evidence` | Evidence item model, normalizers (JUnit, coverage, SARIF, mutation), evidence quality `q(e)`, support `S(c)`, UIM. (Existing `packages/testing` and `packages/confidence` stay; this package depends on them.) |
| `packages/mutation` | Mutation engine adapters (Python first), scoping to changed symbols, caching, budget, equivalent-mutant handling. |
| `packages/tamper` | Deterministic rule engine and rule catalog for evidence tampering and weakening. |
| `packages/trajectory` | Process trace schema, ingestion, process signal extractors. |
| `packages/calibration` | Outcome labels, feature store, calibration models, metrics, abstention thresholds, model registry. |
| `packages/triage` | Hunk risk model, review budget allocation, agent re-prompt generation. |
| `packages/policy` | Per-repo/org policy (`.radius.yml`), waivers, enforcement rules. |

Note: `docs/decisions.md` DEC-003 removed placeholder packages "until a documented phase requires them". This document is that documented phase. Task F-01 recorded the decision as DEC-007 (DEC-005 was already taken by the branching model).

### 4.2 Worker job types (new, in `apps/worker`)

`collect_intent`, `link_intent`, `run_tamper_rules`, `run_mutation`, `compute_evidence`, `ingest_trajectory`, `compute_trust`, `compute_triage`, `backfill_outcomes`, `refit_calibration`. All idempotent, retried with the existing claim / stale-requeue / max-attempts behavior, and resumable (partial results stored).

### 4.3 API (new routes, under `apps/api/src/radius_api/routes/`)

- `GET/PUT /analyses/{id}/intent` (snapshot, edit, confirm criteria)
- `GET /analyses/{id}/criteria` and `/criteria/{cid}` (state, support, linked evidence)
- `GET /analyses/{id}/ieg` (graph, filterable)
- `GET /analyses/{id}/evidence` and `/evidence/{eid}`
- `GET /analyses/{id}/tamper`
- `POST /analyses/{id}/trajectories` and `GET`
- `GET /analyses/{id}/trust` (P, intervals, abstention reason, algo_version)
- `GET /analyses/{id}/triage` and `GET /analyses/{id}/reprompt`
- `GET/PUT /repositories/{id}/policy`; `POST /analyses/{id}/waivers`
- `GET /orgs/{id}/portfolio` and `/teams`, `/agents`, `/trends`, `/exports`
- `POST /internal/calibration/refit` (admin)
- Backward compatible: existing `/analyses/{id}/confidence` keeps v1 until the v2 feature flag is the default.

### 4.4 Dashboard (apps/dashboard)

New views: Intent panel (with confirm/edit), Criteria matrix (criterion x state x evidence), IEG viewer (extends the existing interactive graph), Tamper findings, Process timeline, Trust card (reliability diagram), Triage list, Manager portfolio, Policy editor. Remove use of `NEXT_PUBLIC_RADIUS_API_KEY` (task F-05).

---

## 5. Data model (migrations 0010 onward; Alembic in `infra/database/migrations/versions/`)

All tables carry `organization_id`, `created_at`, and (where computed) `algo_version`. Use the existing SQLAlchemy models location `packages/shared/src/radius_shared/database/`.

| Table | Key columns |
|---|---|
| `intent_snapshot` | id, analysis_id, head_sha, sources_hash, confirmed_by, confirmed_at |
| `intent_source` | id, snapshot_id, kind (`pr_body`,`issue`,`commit`,`spec_file`,`agent_prompt`,`tracker`), ref, raw_text_hash, fetched_at |
| `criterion` | id, snapshot_id, text, normalized_text, origin (`deterministic`,`llm`,`human`), source_id, span, weight, testability (`testable`,`vague`,`non_functional`), state, state_reason |
| `criterion_symbol_link` | criterion_id, symbol_id, confidence, method (`explicit_ref`,`stacktrace`,`bm25`,`embedding`,`llm_verified`), cited_evidence (json) |
| `symbol_test_link` | symbol_id, test_id, confidence, method (`static_call`,`import`,`naming`,`dynamic_coverage`,`semantic`) |
| `test_assertion` | test_id, assertion_kind, target_symbol_id, strength_features (json) |
| `evidence_item` | id, analysis_id, head_sha, kind, source, payload_ref, collected_at, authored_by (`human`,`agent`,`unknown`), independence_factor |
| `evidence_quality` | evidence_id, criterion_id, d_mutation, a_static, i_independence, f_freshness, q, link_conf, algo_version |
| `mutation_run` | id, analysis_id, engine, scope (symbols), budget, started_at, finished_at, status |
| `mutant` | run_id, symbol_id, operator, location, status (`killed`,`survived`,`timeout`,`equivalent_suspect`,`error`), killed_by_test_id |
| `tamper_finding` | id, analysis_id, rule_id, severity, file, line, before, after, explanation |
| `trajectory` | id, analysis_id, agent_name, model, tool, started_at, ended_at, source_format, redaction_level |
| `trajectory_event` | trajectory_id, seq, ts, kind (`prompt`,`edit`,`test_run`,`command`,`revert`), payload_ref |
| `process_signal` | analysis_id, signal_id, value, evidence_refs, algo_version |
| `trust_assessment` | id, analysis_id, head_sha, support_by_criterion (json), uim, p_raw, p_calibrated, interval_lo, interval_hi, decision (`verified`,`failed`,`insufficient_evidence`,`needs_review`), reasons (json), calibration_model_id, algo_version |
| `calibration_model` | id, kind, trained_on_window, n_labels, metrics (json), status, created_by |
| `outcome_label` | id, pull_request_id, label (`correct`,`defect`,`reverted`,`unknown`), source (`revert_detect`,`szz_followup`,`incident`,`benchmark`,`human`), observed_at, horizon_days |
| `review_triage_item` | analysis_id, hunk_ref, risk, rationale (json), rank |
| `policy` / `waiver` | scope, rules (json), created_by; waiver: criterion_id or rule_id, reason, expires_at, approved_by |
| `llm_call_log` | id, purpose, provider, model, prompt_hash, input_ref, output_ref, tokens, cost, cached, latency |
| `audit_log` | actor, action, target, before, after, ts |

Retention and privacy settings are defined in task QS-06.

---

## 6. Algorithms (hypotheses with defaults)

### 6.1 Intent collection and criterion extraction (RQ1)

1. Gather sources: PR body; issues referenced by closing keywords (`fixes #n`) or links; commit messages; `.radius/intent.yml`; optional agent task prompt (passed via API/CLI/MCP); tracker tickets (Plane, Jira, Linear; later).
2. Deterministic pass: task-list checkboxes, bullet lists under headings like "Acceptance Criteria", Gherkin `Given/When/Then`, numbered requirements, sentences with "must / should / shall / when X then Y".
3. LLM-assisted pass (optional, flag-gated): normalize and split compound statements into atomic criteria. Constraints:
   - Strict JSON schema; temperature 0; model + prompt versions logged to `llm_call_log`.
   - Every criterion must cite a character span from a source; spans are verified programmatically (reject outputs with unverifiable spans).
   - **Prompt-injection defense:** PR/issue text is untrusted. The model never receives tools and never decides verdicts; outputs are validated against the schema and spans; instructions inside sources are treated as data.
4. Testability rating (rule-based first): `testable` (observable behavior), `vague`, `non_functional` (perf/security; needs different evidence). Vague criteria are surfaced to the author with a clarification prompt and, by policy, either excluded from UIM with a warning or counted as unevidenced.
5. Human confirmation (UI) is a first-class signal and is logged (feeds RQ1 measurement).
6. No sources at all: the assessment records `intent_missing` and defaults to `insufficient_evidence` for behavior-changing diffs (policy-configurable).

### 6.2 Linking (RQ1)

- criterion -> symbol, ranked candidates from: explicit references (file/symbol/function names in text, stack traces), lexical retrieval (BM25 over symbol names/docstrings/paths), embedding retrieval, optional LLM verification that must quote the code span supporting the link. Restricted to **changed or blast-radius symbols** to keep precision high.
- symbol -> test: static call/import graph (exists), naming convention (exists), **dynamic per-test coverage contexts** (new; strongest signal), semantic similarity (weak, last resort).
- test -> assertion: AST extraction of what each test asserts and on which symbol.
- Each link stores method + confidence + provenance. Combined link confidence = noisy-or across independent methods, capped at 0.95 for non-explicit methods.

### 6.3 Evidence quality `q(e)` (weak-test pillar, RQ2)

For evidence item `e` linked to criterion `c`:

```
q(e, c) = d_eff(e, c) * i(e) * f(e)

d_eff = d_mut                      if mutation data exists for the symbols behind c
      = min(cap_static, a_static)  otherwise          (default cap_static = 0.4)

d_mut     = killed_mutants_by_e / (non-equivalent mutants in symbols behind c)
a_static  = static assertion-strength score in [0,1] (value-checking assertions >
            type/None checks > bare "no exception"; 0 for tautologies)
i(e)      = 1.0 independent human-authored or pre-existing test
          = iota_agent (default 0.6) if test added/edited by the same agent in this PR
          = iota_unknown (default 0.8) if authorship unknown
f(e)      = 1.0 if bound to current head SHA, else 0.0 (stale evidence does not count)
```

Tamper findings against `e` multiply `q` by `(1 - severity_penalty)` (defaults: high = 1.0 i.e. nullify, medium = 0.5, low = 0.2).

### 6.4 Support, UIM, per-criterion state

```
S(c) = 1 - PROD over e in E(c) of (1 - lambda_kind(e) * q(e, c) * l(c, e))
       where l(c, e) = combined link confidence criterion -> symbol -> test -> e

UIM  = SUM_c w_c * [ S(c) < tau_support ] / SUM_c w_c        (default tau_support = 0.6)
```

Per-criterion state:

| State | Rule (defaults) |
|---|---|
| `proven` | `S(c) >= tau_support` and no failing linked evidence |
| `weak` | `0.2 <= S(c) < tau_support` |
| `unevidenced` | `S(c) < 0.2` or no linked evidence |
| `contradicted` | any independent linked evidence failed |
| `excluded` | vague and policy excludes, or waived (with expiry) |

### 6.5 Verdict v2 (deterministic)

1. `failed` if any contradicted criterion, or any required CI check failed on the current SHA, or a high-severity tamper finding exists.
2. `insufficient_evidence` if intent is missing for a behavior change, or UIM > `uim_max`, or coverage of changed symbols by linked evidence < floor.
3. `needs_review` (abstain) if calibrated `P` lies in the abstention band, or process signals exceed risk threshold, or model confidence interval is too wide.
4. `verified` otherwise.

Every verdict stores a **justification tree** (which rule fired, which criteria, which evidence ids) so a human can audit it without rerunning anything.

### 6.6 Process signals (RQ4)

Extractors on the trajectory (or on git history when no trace exists). Candidate signals:
`test_edit_before_pass`, `assertion_removed_then_green`, `retry_count`, `edit_revert_thrash`, `scope_growth` (files outside blast radius), `time_to_green`, `late_test_weakening`, `flaky_pass_reliance`, `ignored_failure`, `dependency_added_unverified`. Each yields a value and evidence refs. A **lucky-pass indicator** is a learned or rule combination, never used alone for a verdict until RQ4 shows predictive value.

### 6.7 Calibration (RQ3)

- Features: `S` distribution, UIM, tamper counts, `d_mut` summary, process signals, change size, blast-radius size, language, provenance (agent/human).
- Labels: `outcome_label` (reverts, SZZ-style follow-up fixes, incident links, benchmark ground truth, human overrides).
- Models, in order: logistic regression baseline -> isotonic/Platt calibration -> **split conformal risk control** for the accept/defer decision (target: error rate among accepted PRs <= alpha).
- Metrics: ECE, Brier, reliability curve, AUROC, selective accuracy vs coverage.
- Cold start: prior from benchmark labels; the UI must say "uncalibrated prior" until `n_labels` passes a minimum.
- Drift detection and scheduled refit; every model version stored in `calibration_model`.

### 6.8 Review triage (RQ5)

```
risk(h) = base(h) * (1 + beta * u(h))
base(h) = f(symbol criticality, blast-radius reach, churn, ownership, size, tamper hits)
u(h)    = unevidenced intent mass attributable to hunk h via IEG
```

Choose a hunk set under a review budget (lines or minutes) maximizing covered risk (greedy on risk per cost; submodular-style guarantee noted in the paper). Output: ordered list + rationale + an **agent re-prompt** that cites evidence ids and lists missing evidence.

---

## 7. Governance of LLM use

| Use | Allowed | Notes |
|---|---|---|
| Criterion splitting/normalization | Yes, flagged | Span-verified, schema-validated |
| Link verification | Yes, flagged | Must quote supporting code span |
| Test/probe generation | Stretch (task EV-12) | Probes are verification artifacts, never committed to the user's repo; needs decision DEC |
| Verdict / score computation | **No** | Deterministic only |
| Explanations | Yes | Must cite evidence ids; template-first, LLM-polish optional |

All LLM calls: provider abstraction, caching by prompt hash, cost cap per org, local-model option, full logging, opt-out for code egress (policy), PII/secret redaction before send.

---

## 8. Security and trust model (summary; details in `tasks/QS-quality-security-ops.md`)

- Treat PRs, issues, agent traces and test output as **untrusted input**.
- Mutation/test execution only in the isolated sandbox: no network, read-only base FS, CPU/memory/pids/time limits, per-run ephemeral workspace, no secrets in env.
- Webhook HMAC + idempotency (exists); API keys scoped per org; RBAC for manager features.
- Tenant isolation tests for every new table/endpoint.
- Secret redaction on all stored trajectories and logs.

---

## 9. Reproducibility requirements (needed for the paper and for audits)

- Every computed artifact stores `algo_version`, input hashes, config snapshot and (for LLM steps) model + prompt versions.
- A `radius replay <assessment-id>` command recomputes an assessment from stored inputs and must produce the same output (task QS-09).
- Randomness (sampling mutants) uses recorded seeds.
- Experiments run through the same pipeline as production (task EP-05), not separate scripts.

---

## 10. Non-goals

- Radius does not write or modify application code in the user's repo.
- Radius does not replace CI, test frameworks or human accountability for merges.
- No language beyond Python (first) and TypeScript (second) until the evaluation shows value.
- No claim of "guarantee of correctness"; all outputs are evidence summaries with calibrated uncertainty.

---

## 11. Open decisions (resolved 2026-11-02; see `README.md` decision log and DEC-010 to DEC-015)

1. Default branch of the GitHub repo (`origin/HEAD` currently points to `dev`; flow is develop -> dev -> main).
2. Whether verdict v2 adds `needs_review` as a fourth state (recommended) or maps it into `insufficient_evidence`.
3. Whether probe/test generation (EV-12) is allowed given "Radius does NOT generate code".
4. Open-source strategy (open core vs fully open vs closed) and license.
5. First target language(s) and first target test framework.
6. Data sources for calibration labels (own history vs public OSS only).
7. LLM provider defaults and whether code may leave the customer's environment.
