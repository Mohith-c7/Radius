# Phase IN: Intent Layer (Milestone M1) -- Research Core, RQ1

Goal: capture what a change is *supposed* to do as a set of confirmable, testable criteria with provenance. See `../DESIGN.md` sections 2, 6.1. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### IN-01 Intent domain model   [x]
- Owner type: agent-ok
- Depends on: F-01
- Branch: `feature/intent-domain-model`
- Size: M
- Goal: pure-domain types in `packages/intent/domain` (no I/O).
- Steps: `IntentSource`, `Criterion` (id, text, normalized_text, origin, span, weight, testability, state), `IntentSnapshot`, value objects (`Span`, `Provenance`), invariants (span must lie within source text; criterion text non-empty; weights in (0,1]); ports (`IntentSourceFetcher`, `CriterionExtractor`, `TestabilityRater`).
- Out of scope: persistence, HTTP, LLM calls.
- Acceptance: >= 95% unit coverage on the domain; invariants tested; no infrastructure imports in the domain layer (enforced by an import-linter rule).
- Research hook: field definitions are the paper's formal model of intent.

### IN-02 Intent source ingestion   [ ]
- Owner type: agent-ok
- Depends on: IN-01, F-06 (live App for realistic payloads)
- Branch: `feature/intent-sources`
- Size: L
- Goal: fetch and store raw intent text from every supported source for an analysis.
- Steps:
  1. PR body and title (from webhook payload / API).
  2. Linked issues: parse closing keywords (`fixes|closes|resolves #n`, cross-repo `org/repo#n`), GitHub issue URLs; fetch via the GitHub App (needs `issues: read`); include issue body and (optionally) maintainer comments labeled as such.
  3. Commit messages in the PR range.
  4. Spec file: `.radius/intent.yml` in the repo (schema in IN-03); ignore if absent.
  5. Agent task prompt: optional `intent` field on `POST /analyses` and on the CLI/MCP (IT-02/IT-04).
  6. Hash each source; store `raw_text_hash`; refetch on edit events (`pull_request.edited`, `issues.edited`).
  7. Size limits (e.g. 64 KB per source), truncation marker, encoding normalization, strip HTML comments and hidden text; keep a flag if hidden/suspicious content was removed.
- Out of scope: tracker integrations (IT-07).
- Acceptance: for fixtures, all sources fetched with correct provenance; edits trigger a new snapshot; missing sources recorded as absent, not as errors.
- Tests: recorded GitHub payload fixtures; permission-denied path; huge-body path; unicode/RTL/zero-width characters.
- Security: sources are untrusted data; never executed.
- Research hook: record the distribution of which sources exist per PR (RQ1 context).

### IN-03 Deterministic criterion extraction   [x]
- Owner type: agent-ok
- Depends on: IN-01
- Branch: `feature/intent-extract-deterministic`
- Size: L
- Goal: extract criteria without any LLM.
- Steps: parse markdown task lists, bullets under headings matching a configurable pattern (Acceptance Criteria, Requirements, Expected, Definition of Done), numbered lists, Gherkin blocks, modal sentences ("must/should/shall/when...then"); parse `.radius/intent.yml`:
  ```yaml
  version: 1
  criteria:
    - id: C1
      text: "Users can reset their password via email link"
      weight: 1.0
      paths: ["src/auth/**"]        # optional hints for linking
      tests: ["tests/auth/test_reset.py::test_reset_flow"]   # optional explicit evidence
  ```
  Each criterion gets a span into its source; dedupe near-duplicates; stable ids across snapshots (hash of normalized text + source).
- Acceptance: on the gold set (IN-09) deterministic extraction reports P/R per source type; known edge cases handled (nested lists, code fences, tables).
- Tests: table-driven parser tests; fuzz tests for pathological markdown.

### IN-04 LLM-assisted extraction (guarded)   [ ]
- Owner type: pair
- Depends on: IN-03, F-10, QS-02 (done: use `radius_shared.llm_guard` and register an adapter per `docs/security/PROMPT_INJECTION.md`)
- Branch: `feature/intent-extract-llm`
- Size: L
- Goal: split compound statements, normalize wording, and find implicit criteria, *without* letting the LLM influence verdicts.
- Steps:
  1. Provider abstraction (Gemini, Anthropic, OpenAI-compatible, local/Ollama) behind one port; config via env; per-org enable flag; cost cap.
  2. Prompt + strict JSON schema; temperature 0; each output criterion must include `source_id` and a verbatim `quote`; programmatic verification that `quote` occurs in the source (fuzzy-match allowed with threshold); reject unverifiable outputs.
  3. Caching keyed by (prompt version, model, source hash); log to `llm_call_log`.
  4. Redact secrets/PII before sending; policy to disable code egress.
  5. Prompt-injection defenses: sources wrapped as data, no tools, outputs only parsed as JSON; test with adversarial PR bodies ("ignore previous instructions...").
  6. Fall back to deterministic result if the LLM fails or is disabled.
- Out of scope: the LLM deciding if a criterion is satisfied.
- Acceptance: LLM path improves recall vs deterministic on the gold set without dropping precision below a documented floor; 100% of emitted criteria have verified quotes; injection suite passes.
- Tests: mocked provider tests; injection suite; schema violation tests; cache-hit tests.
- Research hook: ablation "deterministic vs LLM-assisted" (EP-12); record model/prompt versions.

### IN-05 Testability rating   [ ]
- Owner type: agent-ok
- Depends on: IN-03
- Branch: `feature/intent-testability`
- Size: M
- Goal: rate each criterion `testable`, `vague`, or `non_functional`.
- Steps: rule-based features (observable verb, concrete nouns, numbers, conditions, negations; vague terms like "better", "improve", "clean up"); non-functional keywords (latency, security, accessibility); produce a reason string; produce a clarification prompt for vague items.
- Acceptance: documented rule list; precision measured on gold set; reasons are human-readable.
- Product hook: authors see "this criterion is too vague to verify; try: ...".

### IN-06 Intent snapshots and versioning   [x]
- Owner type: agent-ok
- Depends on: IN-02, IN-03
- Branch: `feature/intent-snapshots`
- Size: M
- Goal: immutable snapshots tied to (analysis, head SHA, sources hash); diffs between snapshots.
- Steps: create snapshot on any source change; carry over human confirmations when a criterion's normalized text is unchanged; mark criteria removed/added/changed; expose a diff.
- Acceptance: editing the PR description creates a new snapshot without losing confirmations on unchanged criteria; older assessments still reference their original snapshot.

### IN-07 Persistence and migration   [x]
- Owner type: agent-ok
- Depends on: IN-01
- Branch: `feature/intent-persistence`
- Size: M
- Goal: tables `intent_snapshot`, `intent_source`, `criterion` (see `DESIGN.md` section 5) via Alembic migration `0010`.
- Steps: SQLAlchemy models in `packages/shared/.../database/`; repositories in `packages/intent/infrastructure`; indices on (analysis_id, head_sha), (snapshot_id).
- Acceptance: upgrade and downgrade tested; org-scoped queries only; migration applies on top of 0009 in CI.
- Tests: repository tests; tenant isolation tests.

### IN-08 Intent API   [ ]
- Owner type: agent-ok
- Depends on: IN-06, IN-07
- Branch: `feature/intent-api`
- Size: M
- Goal: endpoints `GET/PUT /analyses/{id}/intent`, `POST /analyses/{id}/intent/confirm`, `GET /analyses/{id}/criteria`.
- Steps: request/response models; validation (editing criteria text creates `origin=human`); rate limits; OpenAPI + `docs/API_CONTRACTS.md`.
- Acceptance: contract tests; unauthorized and cross-tenant access return 404/403 as per existing conventions.

### IN-09 Gold annotation set for RQ1   [ ]
- Owner type: human-required
- Depends on: F-14, EP-03
- Branch: `feature/bench-intent-gold`
- Size: XL
- Goal: human-annotated ground truth for criteria extraction (and later links).
- Steps: pick >= 150 PRs (mix of human and agent PRs, several languages/projects, varying description quality); define the annotation guideline (what counts as an atomic criterion; vague vs testable); two annotators per PR; measure inter-annotator agreement (Cohen's kappa); adjudicate disagreements; store as JSON under `benchmarks/intent_gold/` with source snapshots (respect licensing; store references + hashes where text cannot be redistributed).
- Acceptance: guideline doc, kappa >= 0.6 (or documented reasons), adjudicated set committed or reproducibly downloadable.
- Research hook: this is a paper dataset; plan its release.

### IN-10 Extraction metrics harness   [ ]
- Owner type: agent-ok
- Depends on: IN-03, IN-09
- Branch: `feature/bench-intent-metrics`
- Size: M
- Goal: run extraction over the gold set and report precision, recall, F1 (exact and fuzzy match), span accuracy, testability accuracy, per source type and per extractor (deterministic, LLM-assisted).
- Acceptance: one command prints a table and writes JSON; results are stored with `algo_version`; CI runs a small subset.

### IN-11 Dashboard Intent panel and confirmation   [ ]
- Owner type: agent-ok
- Depends on: IN-08
- Branch: `feature/dashboard-intent-panel`
- Size: L
- Goal: UI to view, edit, add, remove and confirm criteria; shows provenance (highlight the source span), testability rating, and clarification prompts.
- Acceptance: keyboard accessible; shows diffs between snapshots; confirmation is logged with user and time; empty state explains how to add intent (`.radius/intent.yml`, issue links).
- Product hook: the "wow" moment: the PR is turned into a checklist of what it must prove.
- Research hook: confirmation actions are measured (acceptance rate of extracted criteria).

### IN-12 Missing-intent handling and author prompts   [ ]
- Owner type: agent-ok
- Depends on: IN-05, VD-06
- Branch: `feature/intent-missing-handling`
- Size: S
- Goal: define behavior when no usable intent exists: record `intent_missing`, add a PR comment asking for acceptance criteria (with a template), and let policy decide the verdict impact (default: behavior-changing diff -> `insufficient_evidence`).
- Acceptance: documented policy matrix; comment is posted once, not repeatedly.
