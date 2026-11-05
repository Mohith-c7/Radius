# Radius Intent Package

Owns the intent layer: what a change is supposed to do, as confirmable, testable criteria with provenance (`docs/research/DESIGN.md` 6.1, RQ1). IN-01 delivered the pure domain model and ports; IN-07 added persistence; IN-03 adds deterministic (LLM-free) criterion extraction; IN-06 adds the snapshot service (versioning, carry-over of human decisions, diffs). IN-04 adds an optional, default-off, guarded LLM extractor behind a provider port. IN-05 adds deterministic testability rating. IN-02 (last section) ingests the sources from GitHub.

Layout follows DEC-003/DEC-007: `domain/` (pure), `interfaces/` (ports), `application/` (use cases: domain + ports only) and `infrastructure/` (repositories in IN-07, `extraction/` in IN-03).

## Formal model

Let a *source* be `s = (id, kind, text, h, f, tr, sus)`: `kind` in {pr_body, pr_title, issue, commit_message, spec_file, agent_prompt, comment}, `text` the sanitized string, `h` the SHA-256 of the raw fetched text, `f` the caller-supplied fetch time, `tr` / `sus` booleans recording truncation and removal of hidden or suspicious content (IN-02).

A *span* is `(s.id, a, b)` with `0 <= a < b <= len(s.text)`; the half-open range `[a, b)` of characters.

*Provenance* is `(ref(s), retrieved_at, method, extractor_version)` with `method` in {deterministic, llm, human}. All times are caller-supplied and timezone-aware; the domain never reads a clock.

A *criterion* is `c = (id, text, norm, origin, span, w, t, r, st, h)` where `h = (paths, tests, label)` are optional author hints (`CriterionHints`, IN-03) that never affect the id:

- `norm = normalize(text)`: Unicode NFKC, drop format characters (category Cf, e.g. zero-width and bidi controls), casefold, collapse whitespace; non-empty and idempotent.
- `id = "crit_" + sha256("crit-id-v1" NUL "<kind>:<source id>" NUL norm)[:32]`. Fixed at creation, stable under edits, re-weighting, rating and state changes; independent of the source hash, so unrelated edits to a source keep ids. Changing the derivation requires bumping `CRITERION_ID_ALGO` (plan 1.6).
- `w` in (0, 1]; `t` in {unrated, behavioral_testable, structural_checkable, non_functional_measurable, subjective_or_vague, untestable_external} (IN-05; the IN-01 names `testable`, `vague`, `non_functional` remain as aliases and still parse); `r` optional non-blank rationale.
- `st` in {proposed, confirmed, rejected, edited, needs_reconfirmation, orphaned} with allowed transitions: proposed -> {confirmed, rejected, edited}; edited -> {confirmed, rejected, edited, needs_reconfirmation, orphaned}; confirmed -> {edited, rejected, needs_reconfirmation, orphaned}; needs_reconfirmation -> {confirmed, rejected, edited, orphaned}; orphaned -> {rejected}; rejected -> {proposed}. `needs_reconfirmation` and `orphaned` are set only by the IN-06 service (below); state is a plain string column, so no migration was needed.

An *intent snapshot* is `(id, analysis_id, version, created_at, [c1..cn], refs, parent)`: ordered criteria with pairwise distinct ids, every criterion citing a source ref present in `refs` at the same hash; `version = 1` iff no parent. `diff(old, new)` matches by id: `added = new \ old`, `removed = old \ new`, `changed = {id : old[id] != new[id]}` (any field).

## Invariants and errors

Enforced in constructors; all raise subclasses of `IntentDomainError` (a `ValueError`): `InvalidSpanError`, `InvalidProvenanceError`, `InvalidSourceError`, `InvalidCriterionError` (+ `InvalidWeightError`), `InvalidStateTransitionError`, `InvalidSnapshotError` (+ `DuplicateCriterionError`). `Criterion.create(source, span, ...)` additionally checks that the span names that source and lies within its text.

## Ports (`radius_intent.interfaces`)

`IntentSourceFetcher.fetch(analysis_id, kind, reference) -> IntentSource | None` (absent is `None`, not an error), `CriterionExtractor.extract(source) -> tuple[Criterion, ...]`, `TestabilityRater.rate(criterion) -> TestabilityAssessment`.

## Persistence (IN-07)

Port: `radius_intent.interfaces.IntentRepository` (plus `CriterionStateChange` and the `IntentPersistenceError` family). Adapters in `radius_intent.infrastructure`: `SqlAlchemyIntentRepository(session)` (PostgreSQL and SQLite; flushes, caller commits) and `InMemoryIntentRepository` (tests/dev, `STORAGE_BACKEND=memory`). Tables and migration: `docs/DATABASE_DESIGN.md`, `radius_shared.database.intent`, revision `20261102_0011`.

- Every method takes `organization_id` first and filters by it; another organization's data behaves like missing data (`None`/empty/`NotFound`). SQL writes also check the analysis belongs to the organization (`AnalysisNotFoundError`).
- `save_sources(org, analysis_id, sources)`: idempotent per `(kind, source_id, raw_text_hash)`; text over 64 KiB UTF-8 or containing NUL raises `SourceTooLargeError` (ingestion should truncate first and set `truncated`).
- `save_snapshot(org, snapshot)`: sources must be saved first (`SourceNotFoundError`). Idempotent on a content hash (analysis, version, parent, sources, criteria and their fields; not the snapshot id or `created_at`): saving the same content again returns the stored snapshot, with any later confirmations. Different content under the same id or `(analysis, version)` raises `SnapshotConflictError`. The parent must exist in the same analysis.
- `get_snapshot`, `get_latest_snapshot` (highest version), `list_snapshots` (version ascending). Criteria and sources keep their saved order.
- `record_state_change(org, snapshot_id, criterion_id, new_state, actor=, changed_at=, new_text=, reason=)`: applies the domain transition rules, updates the criterion (state, and wording for `EDITED`, which requires `new_text`) and appends an audit row; `list_state_changes` reads the trail ordered by `(changed_at, criterion_id, sequence)`.
- `analysis_id`, `snapshot_id` and `parent_snapshot_id` must be canonical lowercase UUID strings (they are UUID foreign keys); IN-06 must mint snapshot ids with `uuid4()`. Datetimes must be timezone-aware and come back in UTC.
- Test the SQL adapter against PostgreSQL with `INTENT_TEST_POSTGRES_URL=postgresql+psycopg://... pytest packages/intent/tests/test_persistence.py` on a database migrated with `alembic upgrade head` (rolled back after each test).

## Snapshots and versioning (IN-06)

Pipeline order (wired by default in the API): sources -> extractors (manual, deterministic, optional LLM) -> merge (`select_criteria`) -> testability (`TestabilityRater`, default `DeterministicTestabilityRater`) -> carry-over (`plan_merge`) -> persist. Rating is a pure function of the criterion, so it is deterministic and a rebuild with unchanged inputs still returns the existing snapshot; a criterion that arrives already rated keeps its rating, a rater failure becomes a `rater_failed` diagnostic and leaves it `unrated`. Without a `rater` the service leaves criteria `unrated`.

`radius_intent.application.IntentSnapshotService(repository, extractors, fetcher=None, *, rater=None)` turns sources plus extracted criteria into immutable, versioned snapshots. It depends only on the domain and ports (import-linter contract `application-uses-domain-and-ports-only`), reads no clock (`now` is an argument) and does no HTTP or LLM calls.

```
sources (IntentSource | SourceRequest -> IntentSourceFetcher)      absent -> diagnostic, not an error
        |
        v   each CriterionExtractor, per source (a failure is isolated + reported)
   candidates --select_criteria--> live criteria (dedupe, total order)
        |
        v   rater.rate(c) for every criterion still `unrated` (never overrides a rating)
   live criteria with testability + rationale
        |
        v   plan_merge(live, latest snapshot)   carry-over table below
   seeds + planned state changes
        |
        +-- same signature as latest? --yes--> return latest (created=False, no new version)
        |
        v   save_sources, save_snapshot(version = latest+1, parent = latest)
   SnapshotConflictError -> re-read latest, re-plan, retry (max_attempts)
   identical content already stored (racing builder) -> return it (created=False)
        |
        v   replay planned changes via record_state_change (actor system:intent-snapshots)
   BuildResult(snapshot, created, report{diagnostics, carry_events, absent_sources})
```

API: `build_snapshot(analysis_id, organization_id, sources, now)`, `on_sources_changed(..., trigger="pull_request.edited")` (same pipeline; `trigger` goes into audit reasons), `latest`, `history`, `diff_snapshots(org, older_id, newer_id)`; `diff_snapshot_pair(a, b)` is the pure form. `SnapshotDiffResult.to_dict()` is JSON-serializable and sorted by criterion id (`added`, `removed`, `changed` with field names, `state_changed`, `moved` for span-only shifts, and source changes).

### Versioning rules

- Version 1 has no parent; each new version is `latest + 1` with `parent = latest`. Snapshots are never modified except by human state changes (existing IN-07 behavior), so an older assessment keeps pointing at its original snapshot.
- Idempotency: a rebuild creates no version when sources (kind, id, hash) and criteria (id, text, origin, span, weight, testability, state; `retrieved_at` ignored) equal the latest. Any source hash change creates a new version even if the criteria are unchanged.
- Determinism: sources are ordered by (kind in enum order, source id); criteria by (source kind order, source id, span start, span end, id); retained criteria follow live ones. Same inputs give the same `snapshot_content_hash`.
- Concurrency: two builders racing for the same analysis cannot create duplicates. Identical content hits the repository's idempotent save (the loser returns the winner's snapshot and skips the replay); different content for the same version raises `SnapshotConflictError`, and the loser re-reads and builds the next version. After `max_attempts` (default 5) `SnapshotBuildConflictError` is raised. The SQL adapter flushes without committing, so commit per request: a failure during the replay then rolls the whole version back.

### Merge priority (same normalized text)

Rank: `spec_file` source (0) > `human` (1) > `deterministic` (2) > `llm` (3). Same criterion id from several extractors: lowest `(rank, extractor registration index, extractor_version, span start)` wins. Same normalized text in different sources: lowest `(rank, source kind order, source id, span start, id)` wins and the rest are reported as `deduplicated`.

### State carry-over on edit (previous = latest snapshot)

| Previous criterion | Now | Result in the new version |
|---|---|---|
| any state, same id | still extracted | `confirmed`, `rejected`, `edited` (with the human wording) are replayed through `record_state_change` (audit row, reason `carried from vN (trigger)`); `proposed` stays proposed; span, weight, rating come from the fresh extraction |
| `needs_reconfirmation` | same id still extracted | stays `needs_reconfirmation` |
| `orphaned` | same id extracted again | `needs_reconfirmation` (event `restored`) |
| `confirmed` / `edited` / `needs_reconfirmation` / `orphaned` | gone, identical normalized text under a new id (moved between sources) | state carried unchanged (event `moved`) |
| `confirmed` / `edited` / `needs_reconfirmation` | gone, a new criterion in the same source with text similarity >= 0.6 (difflib ratio, best pair first, one to one) | new criterion is `needs_reconfirmation` (audit row from `confirmed`/`edited`, reason names the old id and text); the old id is `removed` in the diff |
| `confirmed` / `edited` / `needs_reconfirmation` | gone, no successor | kept as `orphaned` (audit row), citing the source's current ref, or its last known ref when the source itself vanished; stays until a human rejects it, after which it drops out |
| `orphaned` | still gone | stays `orphaned` |
| `proposed` / `rejected` | gone | dropped (nothing to protect) |
| any state | the source fetch or an extractor failed | kept untouched (re-pointed to the new source hash); never orphaned by an outage |
| `human`-authored (extraction method) | not re-extracted | kept as is; humans' own criteria are not derivable from sources |

Why a changed text is a new criterion: the id hashes the normalized text, so rewording yields a new id by design (plan 1.6). Matching the reworded successor is the service's job, hence the similarity rule above. A pure case or whitespace change normalizes to the same id and is simply carried.

Orphan choice: the domain gained two states instead of a side table so the fact survives in the snapshot, the audit trail and diffs. A confirmed criterion is never silently dropped; the human decides by rejecting the orphan.

Limits: the report (diagnostics, carry events) is returned but not persisted; fetch failures are attributed per source kind, extractor failures per source, and both conservatively retain the previous criteria.

## Domain purity

`radius_intent.domain` may import only the standard library and `radius_intent.domain`. Enforced by `tests/test_architecture.py` (AST check, runs under pytest) and by the import-linter contract `.importlinter` (CI step; locally `PYTHONPATH=packages/intent/src lint-imports --config packages/intent/.importlinter`).

## Tests

`python -m pytest packages/intent/tests --cov=radius_intent --cov-branch`

## Deterministic extraction (IN-03)

`radius_intent.infrastructure.extraction.DeterministicCriterionExtractor` implements the `CriterionExtractor` port with fixed rules: no LLM, network, clock or randomness. The output is a pure function of `(source, ExtractionConfig)`; the same input gives byte-identical criteria, ids and diagnostics. Rule set version: `DETERMINISTIC_EXTRACTOR_VERSION = "det-extract-v1"` (bump on any rule, default or tie-break change).

```python
extractor = DeterministicCriterionExtractor()  # or (ExtractionConfig(...))
criteria = extractor.extract(source)  # port method
report = extractor.extract_report(source)  # + traces, diagnostics, merges
report = extractor.extract_sources(
    [body, issue, spec]
)  # cross-source dedupe, order independent
```

An `ExtractionReport` holds `criteria`, one `CriterionTrace` per criterion (rule name, section, checkbox state, nesting depth), `diagnostics` (skipped regions with a reason code, parse errors with line numbers, suspicious-content flags, limits) and `duplicates` (the kept criterion and every merged origin with source, span and similarity). It contains no timestamps; provenance times come from `source.fetched_at`.

### Rules (markdown sources)

Everything is one linear pass over lines. HTML comments are blanked (same length) before parsing so spans stay valid in the original text. Content under a code fence is never extracted unless the fence is Gherkin.

| Rule | Fires on | Notes |
|---|---|---|
| `task_item` | `- [ ]` / `- [x]` items anywhere | Outside criteria sections, PR-template boilerplate is skipped (`I have ...`, `Tests added`, `Docs updated`, `Follows ... CONTRIBUTING`, ...). State goes in the trace, not the criterion. |
| `section_item` | any bullet (`- * +`) or numbered (`1.` `1)`) item under a criteria heading | Default headings (full match on the cleaned, lowercased title): Acceptance Criteria, Acceptance, Success Criteria, Requirement(s), Expected (Behavior/Behaviour/Result(s)/Outcome(s)), Definition of Done, DoD, Done When, Scope, Steps to Verify/Test. Setext headings, `**Bold**` lines and `Title:` lines count as headings; sub-headings inherit the section; it ends at the next heading of the same or higher level. Configurable via `ExtractionConfig.section_pattern`. |
| `table_row` | rows of a table whose header has a criteria column (Criterion/Criteria, Acceptance (Criteria), Requirement(s), Expected ...) | One criterion per matching cell; `<br>` becomes a space. Tables without such a column are skipped (`table_no_criteria_column`). |
| `gherkin` | `Scenario:` / `Scenario Outline:` blocks in `gherkin`/`feature`/`cucumber` fences, in unlabeled fences that start with Gherkin, or in plain text; also an unlabeled run of `Given/When/Then` lines | One criterion per scenario: `Scenario: <title>: <step>; <step>`. Needs two steps or a `Then`. `Background:` steps and `Examples:` rows are not part of the text. |
| `modal` / `when_then` / `so_that` / `user_story` | single sentences in prose paragraphs, and in list items outside criteria sections | Precision first, English only. `must`, `shall`, `needs/has/have to`, `required to` always count; `should` counts unless the subject is `we/you/I`; `When/If ... then ...`; `As a ..., I want ...`; `... so that ...` only with a capability verb (`can`, `will`, `ensure`, ...). Rejected: questions, hedges (`maybe`, `probably`, `could`, `ideally`, `I think`), first-person narration, reader directives (`you must`, `please`), sentences over 400 characters. |

**Nesting.** A child bullet is a separate criterion with its own span. A parent that ends with `:` and has children is a lead-in: it is not emitted and each child becomes `"<lead-in>: <child>"`. Any other parent is emitted as its own criterion (its own lines only) next to its children. Continuation lines (indented or lazy) join the item. Items nest when indented deeper than their parent's marker (a tab counts as 4 columns). Depth is capped (`max_list_depth`, 64).

**Never extracted.** Content of non-Gherkin code fences (also unterminated ones), block quotes, HTML comments and standalone block-level HTML tag lines, links or images only, placeholders (`N/A`, `TBD`, `_No response_`), empty checkboxes, and everything under excluded headings (Checklist, Type of change, Screenshots, Notes, Testing/Test plan, Related issues, Changelog, ...; `ExtractionConfig.excluded_pattern`). Plain bullets in neutral sections such as "Changes" are not criteria unless they carry a modal.

**Suspicious content.** A comment is flagged (`hidden_comment_content`, warning) only when its text looks like criteria or instructions (`- [ ]`, `must`, `ignore previous instructions`, ...); ordinary template hints are an info-level `html_comment`. Also flagged: unterminated comments, zero-width and bidi characters (`invisible_characters`), and sources that ingestion marked `suspicious_content_removed` or `truncated`. Hidden text is never turned into a criterion.

**Limits.** 500 criteria per source, 1000 diagnostics per source (then a `diagnostics_truncated` note), 2000 characters per item. Regexes are single-pass and non-nested (a test guards this); a 1 MB body takes about a second.

### Near-duplicate merging

Criteria are merged within a source and across sources. Two criteria merge when their normalized text is equal as a word sequence ignoring punctuation, or when the token-set Jaccard `|A and B| / |A or B|` over content words (stopwords and modal verbs removed) is at least `similarity_threshold` (default 0.8; statements with fewer than 3 content words merge only when exact). Entries are processed by `(source priority desc, source key, span, id)` and each joins the most similar earlier group (ties: the earliest), so the result does not depend on input order. Priority: spec_file 100, agent_prompt 90, issue 70, pr_body 60, pr_title 40, commit_message 30, comment 20. The kept criterion is the highest-priority one; merged origins are listed in `report.duplicates`. Ids are the domain's `criterion_id(normalized_text, source.ref.key)`, so they survive edits to unrelated text.

### `.radius/intent.yml` (source kind `spec_file`)

```yaml
version: 1                      # required, must be 1
criteria:                       # required list
  - id: C1                      # optional label [A-Za-z0-9_.-]{1,64}, unique; kept in hints.label
    text: "Users can reset their password via email link"   # required, <= 2000 chars
    weight: 1.0                 # optional, number in (0, 1], default 1.0
    paths: ["src/auth/**"]      # optional hints (relative globs), at most 50
    tests: ["tests/auth/test_reset.py::test_reset_flow"]    # optional explicit evidence, at most 50
```

Explicit criteria become `Criterion` objects with origin `spec_file` and `hints = CriterionHints(paths, tests, label)` (the only domain addition in IN-03; hints never change the id). The span is the `text` value (inside the quotes). A sample is in `docs/intent/intent.example.yml`.

PyYAML is only a transitive dependency of Radius (not declared), so the spec is read by a small strict parser (`spec_file.py`) instead of `yaml.safe_load`; no new dependency was added. Supported: mappings, `- ` sequences, plain, single and double-quoted scalars, single-line `[a, b]` lists, `|` and `>` block scalars, `#` comments, an optional leading `---` and trailing `...`. Rejected with an error: tabs, anchors, aliases, tags, flow mappings, multi-line flow scalars, a second document, an unquoted `: ` inside a value, bad escapes, absolute or `..` paths. Errors are diagnostics with a `code` and 1-based `line` (`spec_syntax`, `spec_unsupported_version`, `spec_missing_text`, `spec_invalid_weight`, `spec_duplicate_id`, ...). A bad criterion is skipped and the others are still read; a bad spec never stops other sources. Unknown keys are warnings (`spec_unknown_key`). A structural syntax error stops reading that file.

### Metrics hook for IN-10

IN-09's gold set does not exist yet. `score_extraction(predicted_texts, gold_texts, fuzzy_threshold=None)` returns `PrecisionRecall` (one-to-one greedy matching on normalized text, optionally fuzzy by content-token Jaccard) and `score_by_source_kind(cases)` micro-averages over `GoldCase(kind, predicted, gold)` per source kind. No CLI, no I/O. The full harness (IN-10) is described below.

### Limitations

English-only modal rules (other languages extract only via lists, tables, Gherkin and spec files). One criterion per list item or sentence: compound statements are not split (IN-04). Markdown handling follows GitHub loosely, not CommonMark exactly (child lists need only a deeper marker; indented code blocks are not recognised; a `---` rule does not end a section). `Steps to Verify` steps and `Scope` bullets are taken as criteria, which can lower precision. Checkbox state is trace-only. Sources over the ingestion limit are read as given (IN-02 truncates).
`python -m pytest packages/intent/tests --cov=radius_intent.domain --cov=radius_intent.application --cov-branch`


## LLM-assisted extraction (IN-04, optional, off by default)

`radius_intent.infrastructure.llm.LlmCriterionExtractor` implements the `CriterionExtractor` port and asks an LLM to *propose* extra criteria (split compound statements, normalize wording, find implicit ones). The deterministic extractor and the evidence stay authoritative (DEC-009). Prompt version `intent-extract-llm-v1`.

```python
cfg = LlmExtractionConfig.from_env()  # RADIUS_LLM_INTENT_*; everything off by default
llm = LlmCriterionExtractor(AnthropicProvider(cfg.model), organization_id=org, config=cfg)
out = AssistedCriterionExtractor(DeterministicCriterionExtractor(), llm).extract_report([body, issue])
out.criteria  # deterministic criteria first, unchanged; then surviving LLM proposals
```

- **Gate (DEC-015).** `EgressPolicy.egress_allowed(org)` is checked before every provider call, including each retry. The default `EnvEgressPolicy` needs `RADIUS_LLM_INTENT_ENABLED=true` and the org in `RADIUS_LLM_INTENT_ORGS` (or `*`). Off means the provider is never called and the result is empty. Only intent text (after `radius_shared.llm_guard.sanitize_untrusted`, which redacts known env secrets and strips hidden content) is sent, never repository code.
- **Prompt.** Built only through `llm_guard.build_prompt`: untrusted text sits in nonce-delimited data blocks, the model has no tools. The nonce is random per call and masked when hashing, so `prompt_hash` (SHA-256 of version, model, max tokens and the masked prompt) is stable and is the cache key (scoped per org).
- **Output.** Validated by `llm_guard.validate_criteria_output` (strict schema, exact `quote == source[start:end]`, no URLs, commands, verdict-like keys or text, no secrets or nonce, count and length caps). A document-level violation (bad JSON, any verdict-like key, a leak) drops the whole answer; item-level violations drop just that item. The extractor then also requires a quote of at least 8 characters, that the quote occurs verbatim in the stored source text, and that at least 60% of the restated text's words occur in the quote. Every drop is a `Diagnostic` with code `dropped_<reason>`; nothing from the model is echoed into diagnostics or logs. Offsets must be exact: a correct quote with wrong offsets is dropped (no repair, see Limitations).
- **Provenance.** `method=llm`, `extractor_version = "intent-extract-llm-v1;model=<id, 18 chars>;sha=<12 hex of the prompt hash>"` (at most 64 characters, the storage limit; the full hash is in the trace), state `proposed`, weight `0.4` (`llm_weight`). Never auto-confirmed.
- **Merge policy** (`merge_proposals`, used by `AssistedCriterionExtractor`). Existing criteria (deterministic, human, confirmed) are returned unchanged and first. A proposal is dropped if it has the same id, the same word sequence, or Jaccard >= 0.8 with an existing or earlier criterion (IN-03's rule), so the deterministic one wins. IN-06's merge priority ranks `llm` last; IN-06 was not merged when this was written, so the documented order is enforced locally.
- **Cost and resilience.** Per-analysis and per-org token caps (estimate before the call, provider-reported usage after; org usage lives in a `UsageLedger`, in-memory by default), response cache (`ResponseCache` protocol, in-memory LRU; only fully valid answers are cached and entries are re-validated on every use), timeout, bounded retries with deterministic exponential backoff (0.5 s, 1 s, ... capped at 8 s; `sleeper` and `clock` injectable), circuit breaker (5 consecutive failures, 60 s cooldown, one half-open trial). `extract*` never raises into the pipeline.
- **Logging.** One structured `llm_call` record per attempt on logger `radius.intent.llm` (org, prompt hash, version, model, attempt, outcome, tokens, latency). Never prompts, source text or model output; the F-10 formatter also redacts secrets. Persisting to an `llm_call_log` table is a follow-up.
- **Providers.** `LlmProvider` is a Protocol (`complete(LlmRequest) -> LlmResponse`, errors as `ProviderError` subclasses). `FakeProvider` is deterministic and used by all tests. `AnthropicProvider` (optional extra `llm`: `anthropic>=2.0,<3`; 2.3.0 is Apache-2.0 and pip-audit reports nothing for it) imports the SDK lazily, reads `ANTHROPIC_API_KEY` from the environment only, sets SDK `max_retries=0` and sends no tools. Default model `claude-haiku-5-5`: the task is short, schema-bound extraction whose every output is verified against the source, so the cheapest tier fits; set `RADIUS_LLM_INTENT_MODEL=claude-sonnet-5-5` if recall needs it. Current Claude models reject non-default sampling parameters and the Messages API has no seed, so temperature is only sent if explicitly configured and `seed` is not sent: determinism on the real adapter is best-effort (low effort plus the response cache); the fake provider is fully deterministic.
- **Import contract.** Only `anthropic_provider.py` may touch a provider SDK, and only lazily; the other `llm` modules are covered by an import-linter contract and an AST test.
- **Injection suite.** Registered as `intent-extract-llm (IN-04)` in `tests/security/prompt_injection/pi_registry.py`.

### Limitations (IN-04)

No quality numbers exist yet: the gold set (IN-09) and metrics (IN-10) come later, so nothing is claimed about recall or precision. Models are poor at counting characters, so correct quotes with wrong offsets are dropped rather than repaired (repairing would let an injected sentence pass as a quote); a quote-only schema needs a guard change and is a follow-up. The grounding check is word-based and English-oriented. A malicious but verbatim-quoted, URL-free proposal is still accepted as `proposed` (bounded: low weight, human confirmation required). The org cap is per process, not per billing period.


## Testability rating (IN-05)

`radius_intent.infrastructure.testability.DeterministicTestabilityRater` implements the `TestabilityRater` port with fixed rules: no LLM, network, clock or randomness. The result is a pure function of `(criterion text, hints, source kind, word lists)`. Rule set version: `TESTABILITY_RULES_VERSION = "testability-rules-v1"` (bump on any rule, weight, threshold or default word-list change).

```python
rater = DeterministicTestabilityRater()  # or DeterministicTestabilityRater(load_wordlists("my.json"))
assessment = rater.rate(criterion)  # port: rating + rationale
result = rater.explain(criterion)  # rating, confidence, reasons, rewrite_hints
rated = rate_criteria(extractor.extract(source))  # pipeline step for IN-06
```

### Categories (`Testability`)

| Rating | Meaning | Evidence it can get |
|---|---|---|
| `behavioral_testable` | Observable behavior with inputs/outputs or conditions | tests |
| `structural_checkable` | refactor, rename, move, config, dependency, docs: checkable by diff or static analysis | diff, AST or lockfile checks (EV-13) |
| `non_functional_measurable` | performance, security, accessibility with a threshold or a named tool | benchmark or scanner output |
| `subjective_or_vague` | "clean", "intuitive", "better", "robust" without a measure; TBD; no cue found | none: ask the author |
| `untestable_external` | needs human, product or legal judgment, or a live external system | none: a person decides |
| `unrated` | not rated yet (IN-01 default) | |

### Output

`TestabilityResult`: `rating`, `confidence` (`high`/`medium`/`low`, derived from rule margins, not a probability), `reasons` (ordered: rules supporting the rating first, then by weight and position; each has `rule_id`, group, weight and the matched `spans`), `summary` (one human line), `rewrite_hints` (for vague and external ratings, for example "Add a measurable threshold (for example 'p95 latency under 200 ms') or name the tool and standard that checks it."), `scores` and `rules_version`. `rationale()` is stored in `Criterion.testability_rationale`: the summary, the first hint ("Try: ..."), and a tag such as `[testability-rules-v1; confidence=medium; rules=http_status,observable_verb]`. `to_dict()` is JSON-serializable.

### Rules (`testability-rules-v1`)

Each fired rule adds its weight to a group; a fixed precedence then decides. Word lists live in `infrastructure/testability/wordlists.json` (schema `testability-wordlists-v1`, checked by `validate_wordlists`; entries are lowercased, de-duplicated and sorted, so file order never matters). A custom file can be passed to `load_wordlists(path)`.

| Group | Rule ids (weight) |
|---|---|
| behavioral | `gherkin_scenario` (3), `explicit_test_hint` (3, `tests` in `.radius/intent.yml`), `path_hint` (1), `spec_file_origin` (1), `http_status` (3), `observable_verb` (2), `error_wording` (2), `quantity_threshold` (2), `code_reference` (2), `condition_clause` (1), `result_clause` (1), `modal_verb` (1), `passive_requirement` (1), `comparator` (1), `negation` (1), `literal_value` (1) |
| structural | `structural_verb` (3), `docs_config_edit` (3: a leading imperative such as "Update the README"), `version_number` (2, only with a structural verb), `structural_noun` (1) |
| non_functional | `nfr_term` (3), `time_budget` (3), `measure_tool` (3) |
| vague | `placeholder` (4), `vague_adjective` (3 per distinct word, at most 2 counted), `weasel_word` (2 per distinct word, at most 2), `too_short` (2) |
| external | `external_judgment` (3), `live_system` (3) |
| meta (weight 0) | `non_english_fallback`, `text_truncated`, `no_testable_signal`, `nfr_without_threshold` |

Decision, first match wins (b/s/n/v/x are the group scores): (1) `placeholder` and no explicit evidence -> vague; (2) `x >= 3`, `x + 1 >= b` and no linked test -> `untestable_external`; (3) `n >= 3` and no explicit evidence (HTTP status, Gherkin, linked test): with a quantity, time budget or named tool -> `non_functional_measurable`, otherwise behavioral at low confidence if `b >= 4` and `b > v`, else vague (`nfr_without_threshold`); (4) `s >= 3`, `s >= b`, `s - v >= 2` and not a when/then frame -> `structural_checkable`; (5) `b >= 2` and `b > v` -> `behavioral_testable`; (6) otherwise vague. Confidence is `high` only for large margins (for example `b >= 6` with margin >= 3), `low` for a single weak cue, for no cue at all, and always for non-English text; truncated text caps at `medium`.

Origin and hints: a Gherkin scenario (the extractor's `Scenario: ...` text), a linked test in `.radius/intent.yml` and a `spec_file` origin raise the behavioral score. A linked test does not rescue placeholder text.

### Pipeline integration point (IN-06)

`rate_criteria(criteria, rater=None) -> tuple[Criterion, ...]` and `rate_criteria_report(...) -> RatingReport` (criteria plus per-criterion `TestabilityResult`, `counts()`, `needs_clarification()`). They only call `Criterion.with_testability`, so ids, text, spans, weights, hints and confirmation state are untouched, order is preserved and re-rating is idempotent. The snapshot service applies the rater through the `TestabilityRater` port (`IntentSnapshotService(..., rater=)`) after the merge and before persistence; `testability` and `testability_rationale` are already persisted by IN-07 (plain strings, no migration). Changing rules requires bumping `TESTABILITY_RULES_VERSION` and re-rating.

### How other tasks use it

- IN-12 (missing intent and author prompts): `subjective_or_vague` and `untestable_external` criteria are the ones to ask about; `rewrite_hints` is the clarification text and the rule ids are the reason codes.
- EV-13 (non-behavioral evidence): `structural_checkable` routes a criterion to diff, AST or lockfile evidence instead of tests; `non_functional_measurable` routes it to benchmark or scanner evidence. Radius should report `subjective_or_vague` and `untestable_external` criteria as "not mechanically testable" instead of looking for test evidence.
- IN-10: `evaluate(cases, rater) -> AccuracyReport` (accuracy, per-label precision and recall, confusion, accuracy per confidence band, mistakes) and `load_labeled(path)` read JSONL lines `{"id","text","label","source"?,"tests"?,"lang"?}`.

### Limitations

English word lists only; other languages get language-neutral cues (code references, quantities, HTTP status codes) at low confidence and otherwise land in `subjective_or_vague` with the hint to add an English summary or a linked test. Rule-based: ambiguous words ("remove", "update", "secure", "split") can mislead, an imperative "Update ..." or "Remove ..." about runtime data may be read as a structural edit, and a criterion that mixes behavior and a vague adjective is rated by the larger score. Only the first 4000 characters are analysed. Weights and thresholds were set by hand and checked on `tests/fixtures/testability/labeled.jsonl` (122 criteria, developed against it) and `labeled_holdout.jsonl` (30 criteria written afterwards by the same author, not used for tuning). These are development sanity checks by one author, not a research result: the gold set is IN-09 and the measurement is IN-10. The documented known misses are listed in `tests/test_testability_cases.py`.

## Extraction metrics harness (IN-10)

Harness ready; real numbers pending the IN-09 gold set. Everything run so far is synthetic or F-14-derived and labelled `SYNTHETIC - not a research result`. Full documentation: `docs/research/evaluation/INTENT_EVAL.md`.

```bash
python scripts/intent_eval.py list-extractors
python scripts/intent_eval.py run --config benchmarks/configs/intent_synthetic.json   # writes benchmarks/results/intent/<run-id>/
python scripts/intent_eval.py report benchmarks/results/intent/<run-id>
python scripts/intent_eval.py compare RUN_A RUN_B --a-extractor combined --b-extractor deterministic
```

- **Where.** `radius_intent.evaluation` (`python -m radius_intent.evaluation` works too). Pure computation (`gold`, `matching`, `stats`, `metrics`, `config`, `compare`, `report`) is fenced by an import-linter contract; file reading is confined to `loader` and `provenance`; `extractors`/`runner`/`cli` call the production extractors, merge and testability rater. Product code must not import it (second contract).
- **Gold contract.** `radius.intent.gold/1` (schema in `docs/research/evaluation/intent_gold.schema.json`): per PR, `sources` (kind + text), `criteria` (code-point `span`, optional `alt_spans`, `testability`, `text`), `well_specified`, `author_type`. IN-09's files plug in through an adapter selected as `--adapter module:function` that returns this dict.
- **Matching and metrics.** One-to-one greedy span matching at IoU >= 0.5 (configurable; PREREGISTRATION 5.1), plus normalized-text and token-Jaccard modes; micro and per-PR macro P/R/F1 overall, per source type, per well-specified slice and per author type; testability accuracy, macro-F1, Cohen's kappa and confusion matrix; abstention, coverage and false-positive rate on PRs without gold. Percentile 95% intervals from a seeded PR-cluster bootstrap (default 10,000 resamples, seed 20261102); `compare` is the paired bootstrap.
- **Extractors.** `deterministic` (`det-extract-v1`), `llm` and `combined` (prompt `intent-extract-llm-v1`) over a `fake-lines`, `replay` or `anthropic` provider, and `oracle`/`null` sanity baselines. The real provider needs `--allow-real-llm` and `RADIUS_EVAL_ALLOW_REAL_LLM=1`; tests never use it.
- **Reproducibility.** Every `run.json` records the config hash, seeds, dataset hash, git commit, extractor/prompt/testability versions, timings and LLM token usage.

## API integration (IN-08)

The REST surface is documented in `docs/API_CONTRACTS.md` (Intent APIs); code is in `apps/api` (`routes/intent.py`, `intent_management.py`, `intent_presenter.py`, `schemas/intent.py`).

- **Wiring.** `AppContainer` (`radius_api.dependencies`) owns `intent_repository` (memory), `intent_extractors`, `intent_rater` (default `DeterministicTestabilityRater`, applied on memory and sql), `llm_config`, `llm_provider_factory` and `clock`. `get_intent_service` builds an `IntentManagementService(repository, IntentSnapshotService(repository, extractors))` per request: with `STORAGE_BACKEND=sql` it uses `SqlAlchemyIntentRepository` on the request-scoped session (one commit per request, rollback on any error, shared with the analysis and repository services).
- **LLM extractor (IN-04).** `AppContainer.llm_extractor_for(org)` returns an `LlmCriterionExtractor` only when `RADIUS_LLM_INTENT_ENABLED` is on AND the org is in `RADIUS_LLM_INTENT_ORGS` (or `*`); it is appended after the static extractors for that org's builds only. Default: off, nothing is registered and no provider is built. The provider is built lazily on first use (`llm_provider_factory`, default `AnthropicProvider`); a missing `anthropic` package or `ANTHROPIC_API_KEY` logs a warning and the extractor stays unregistered (fail closed, requests unaffected). The extractor's own per-call egress gate still applies. Tests inject `FakeProvider` through `llm_provider_factory`.
- **Adding an extractor (IN-04).** Append it to `AppContainer.intent_extractors` (default: `ManualCriterionExtractor`, `DeterministicCriterionExtractor`). Order is the tie-break index of `select_criteria`. Nothing else in the API changes; `tests/test_intent_api.py::test_extractors_are_wired_through_the_container` shows the pattern.
- **Source model.** The API never stores "the current text" outside the repository: the current sources are the refs of the latest snapshot resolved against `get_sources`. A submit replaces the source with the same `(kind, source_id)` and passes the complete current set to `on_sources_changed` (a source missing from that set would be orphaned). The `trigger` written to audit reasons is `api.sources_submitted`, `api.rebuild` or `api.manual_criterion`.
- **Manual criteria.** `ManualCriterionExtractor` (`radius_intent.infrastructure.manual`) turns a source of kind `comment` and id `manual:<hash of normalized text>` into one `human` criterion. Because it is an ordinary source, rebuilds re-derive it, `human` outranks `deterministic` in the merge, and its id is stable. The API confirms it on creation (audit actor = caller).
- **Spec validation.** `.radius/intent.yml` is checked with `DeterministicCriterionExtractor.extract_report` before storage; any `error` diagnostic returns 422 `INTENT_SPEC_INVALID` listing `line N: message [code]` (first 10). Line numbers refer to the text as submitted, so the check runs before sanitization (and again after it if sanitization changed the text).
- **Sanitization.** Submitted text goes through `radius_shared.llm_guard.sanitize_untrusted` (hidden characters, comments, secrets removed). `raw_text_hash` is the hash of what the client sent; `suspicious_content_removed` is set when hidden content was stripped. Flag-only findings (injection phrases) are returned as codes and never alter the text.
- **Concurrency.** The ETag is a hash of the snapshot id and every criterion's `(id, state, text)`; `If-Match` is checked against the latest snapshot before a write. The service's own version-conflict retry handles two writers racing without `If-Match`.
- **Hints.** `SqlAlchemyIntentRepository` now persists `CriterionHints` in the existing `intent_criteria.hints` JSON column (no migration); previously they were dropped on the SQL backend.

## Source ingestion from GitHub (IN-02)

Intent now comes from the pull request itself, not only from `POST .../intent/sources`. **Status: validated against recorded/hand-built fixtures and a stateful fake GitHub API; live validation is pending F-06** (see `docs/github-app-validation/RUNBOOK.md`, section "Intent ingestion"). The code lives outside this package so the import-linter contracts stay untouched: `radius_github.intent_*` (GitHub-specific; `GitHubIntentSourceFetcher` implements the `IntentSourceFetcher` port), `radius_worker.intent_ingestion` (composition) and `radius_api.github_intent` (webhook payload capture). This package only gained `radius_intent.infrastructure.defaults.default_extractors()` so the API and the worker run the same extractors.

### Who does what

| Where | Network | What it stores |
|---|---|---|
| API webhook handler, `pull_request` opened / reopened / synchronize / ready_for_review | none | `pr-title`, `pr-body` from the payload (`title`, `body`) for the new analysis; skipped when the payload has no `body` key (the worker then uses the REST API) |
| API webhook handler, `pull_request.edited` | none | refreshes `pr-title` / `pr-body` of the PR's latest analysis and rebuilds (`trigger=pull_request.edited`) |
| API webhook handler, `issues.edited` | none | refreshes `issue:<n>` from the payload in the latest analysis of each of the 20 newest PRs of that repository that already stores it (`trigger=issues.edited`); cross-repository issues wait for the next analysis |
| Worker, start of every job (`trigger=analysis.started`) | GitHub REST with the installation token | everything in the next table; skipped for inactive installations, unless `RADIUS_FEATURE_INTENT_INGESTION=true` (**default off until the live F-06 validation**), or without App credentials; any error is logged and swallowed |

The API holds no GitHub credentials and makes no GitHub calls. `synchronize` creates a new analysis (new head SHA) and the worker fetches its commit messages and spec file, so new commits are covered. Commits pushed after an analysis ran do not alter that analysis' intent (an analysis is pinned to a SHA; `head_moved` is reported if the PR head differs).

### Sources, ids and provenance

| Source | Kind | `source_id` | Fetched from |
|---|---|---|---|
| PR title | `pr_title` | `pr-title` | payload, else `GET /pulls/{n}` |
| PR body | `pr_body` | `pr-body` | payload, else `GET /pulls/{n}` |
| Spec file | `spec_file` | `intent.yml` | `GET /contents/.radius/intent.yml?ref=<analysis commit>` (404: absent) |
| Commit messages | `commit_message` | `commits` | `GET /pulls/{n}/commits?per_page=50` |
| Linked issue | `issue` | `issue:<n>`; cross-repo `issue:<owner>:<repo>:<n>` (hashed owner/repo if over 64 chars) | `GET /repos/{o}/{r}/issues/{n}` |
| Maintainer comments (opt-in) | `comment` | `issue-comments:<n>` | `GET .../issues/{n}/comments` |
| Agent task prompt, manual criteria | `agent_prompt`, `comment` | `agent-prompt`, `manual:<hash>` | the intent API (IN-08); ingestion never touches them |

Ids contain no SHA, delivery id or timestamp, so criterion ids (a hash of `<kind>:<source id>` and the normalized text) are stable across edits, force-pushes and re-runs. `pr-title`, `pr-body` and `intent.yml` equal the IN-08 defaults on purpose: GitHub's value replaces an API-submitted source with the same default id (use another `sourceId` to keep both). The commits are one source with a `Commit <sha7>:` section per commit, so a rebase changes one source instead of fifty (and stays well below the 50-source API limit). Provenance of a criterion is `(kind, source_id, raw_text_hash)` plus its span; the fetch origin (`webhook_payload` / `rest_api`), the pointer (`owner/repo#n`, `.radius/intent.yml@<sha12>`) and the status are in the ingestion report and the `Intent ingestion` log record.

### Linked issues

`radius_github.intent_links.parse_closing_references`: keywords `close(s|d)`, `fix(es|ed)`, `resolve(s|d)` (GitHub's nine forms), case-insensitive, optional colon; one reference per keyword (`Fixes #1, #2` links only `#1`, as on GitHub); references `#n`, `owner/repo#n` and `https://github.com/owner/repo/issues/n` (pull-request URLs are ignored). Ignored regions: fenced code (backtick and tilde, any length; an unterminated fence runs to the end), inline code, HTML comments, blockquotes, `<code>` / `<pre>`. Not detected: indented code blocks (an indented `- fixes #1` is usually a nested list). Links are read from the stored PR body and the non-merge commit messages, deduplicated case-insensitively (`#5` equals `owner/repo#5` in the PR's repository) and capped at 10 issues (`linked_issues_truncated:<n>`). References to other repositories are not fetched unless `RADIUS_INTENT_ALLOW_CROSS_REPO=true` (default false: the installation token reads every repository of the installation); they are recorded absent with reason `cross_repo_disabled` and no request is made. A number that is a pull request is recorded absent (`is_pull_request`). Maintainer comments (`RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS=true`) keep only comments whose `author_association` is OWNER, MEMBER or COLLABORATOR and whose author is not a bot (at most 5, 4000 characters each), rendered as `Comment by @login (ROLE):` so the label survives into the text.

### Outcomes: present, absent, unavailable

Every source gets an explicit outcome; none is an exception.

| Status | Meaning | Examples | Effect on stored intent |
|---|---|---|---|
| `present` | text fetched | | replaces the stored source with the same `(kind, id)` |
| `absent` | not there for this App | empty body (`empty`), 404 `not_found`, 410 `gone`, 403 without rate-limit markers `forbidden` (for example no `issues: read`), 451, `is_pull_request`, `no_maintainer_comments`, a spec that is `not_a_file` / `too_large` / `unreadable` | removes an *owned* source (PR title/body, commits, issues, comments), retiring its criteria by IN-06's rules; the spec file is not owned and an absent repo file never removes a spec submitted through the API |
| `unavailable` | could not be determined | `rate_limited`, 401, 5xx, timeout, redirect, bad JSON, `budget_exhausted`, `deadline_exceeded`, `token_error` | nothing changes; stored sources are kept (an outage never orphans a confirmed criterion) |

On a *complete* pass (PR body known, commit list fetched or absent) owned `issue:*` / `issue-comments:*` sources that are no longer linked, or whose option was switched off, are dropped. Payload-only updates never drop anything they did not look at.

### Change detection and idempotency

`raw_text_hash` is the SHA-256 of the text exactly as fetched (before normalization), so any upstream edit changes it. `IntentIngestionService.apply` merges the outcomes into the current sources (anything not mentioned, such as the agent prompt and manual criteria, is kept) and calls `IntentSnapshotService.on_sources_changed(trigger=...)`. Unchanged hashes and criteria create no version (tested: repeated ingestion, repeated webhook deliveries and a retried job leave the version count alone); a changed source creates version `n+1` with IN-06 carry-over of confirmations. Conditional requests: an in-process `EtagCache` (per worker process and installation, 256 entries) sends `If-None-Match`; a 304 reuses the parsed body. After a worker restart the first request is unconditional.

### Limits and hygiene

64 KiB of UTF-8 per source (marker `[...truncated by Radius: source exceeds 64 KiB...]`, `truncated=true`; the hash still covers the full text; input is cut at 512 Ki characters before any processing). `radius_github.intent_text.prepare_text` per text: lone surrogates replaced; leading BOM removed, newlines normalized, NFC; elements hidden by the `hidden` attribute or an inline `display:none` / `visibility:hidden` / `font-size:0` / `opacity:0` / `height:0` / `width:0`, and Markdown comment links (`[//]: # (...)`), removed; then `radius_shared.llm_guard.sanitize_untrusted` (NUL, ANSI, zero-width, bidi, Unicode tag and control characters, HTML comments, secrets). `suspicious_content_removed` is set when any hidden-content finding removed something (PR templates' own HTML comments set it too). Injection phrases are flagged in the report and never rewritten or executed. Commit messages lose trailing `Co-authored-by`, `Signed-off-by`, `Change-Id`, `Reviewed-by`... trailers and "Generated with ..." signature lines; their text is kept. Merge commits (more than one parent) are skipped; at most 50 commits are read. Arabic, Hebrew and CJK text is preserved; RLM/LRM and bidi override characters are removed.

Budget per analysis: at most `RADIUS_INTENT_MAX_API_CALLS` (default 15) REST calls and `RADIUS_INTENT_DEADLINE_SECONDS` (default 30) seconds; each call's timeout is `GITHUB_TIMEOUT_SECONDS` capped by the time left. Order: PR, commits, spec file, issues (up to 10), comments. The installation token is minted once and not counted. A rate-limit response (403 with `x-ratelimit-remaining: 0`, `retry-after` or a "rate limit"/"abuse" message, or 429) or a 401 stops all further calls. With 15 calls: 3 fixed, 10 issues, 2 comment fetches.

### Diagnostics and research hook

One structured log record per ingestion (`Intent ingestion`, logger `radius_github.intent_ingestion`): `intent_sources` (`{source_id: status}`), call count, snapshot version and whether it was created, stop reason and diagnostics (`head_moved`, `merge_commits_skipped:n`, `commits_capped_at:50`, `linked_issues_truncated:n`). That is the RQ1 "which sources exist per PR" data; no text is logged. `IngestionReport.to_dict()` adds per-source origin, reference, hash and flags. Reports are not persisted (no migration was added).

### Tests

`packages/github/tests/test_intent_{links,text,rest,sources,ingestion}.py`: a parser table of 80 cases (code fences, quotes, comments, hostile-input timing), hygiene, REST classification, the collector against `fixtures/api/*.json` through `radius_github.fake_api.FakeGitHub`, snapshot idempotency, permission-denied and rate-limit paths, injection inertness with a registered but disabled LLM extractor that must not be called, and the call budget. `apps/worker/tests/test_intent_ingestion.py` runs the worker end to end on SQLite (best-effort guarantees, inactive installation). `apps/api/tests/test_github_intent_webhooks.py` covers payload capture, edits, issues and savepoint isolation. The fake reproduces ETag/304, auth, `per_page`, 403/404/410/5xx and both rate-limit shapes; it is not GitHub.

### Follow-ups

- Persist ingestion reports (source presence and reasons) in a table for RQ1 and the dashboard.
- `issue_comment` webhooks and cross-repository `issues.edited` refresh.
- Fetch a newly linked issue right after `pull_request.edited` (today the next analysis does; needs App credentials in the API or a durable refresh job).
- Carry human decisions across analyses of the same PR (a new head SHA is a new analysis with a new intent).
- Pagination for more than 50 commits or 30 comments; compare the parser with GraphQL `closingIssuesReferences` on live PRs.
- Tracker integrations (Jira, Linear...) are IT-07.
- Security note: enabling `RADIUS_INTENT_ALLOW_CROSS_REPO` lets a PR author pull issue text from any repository of the installation into this analysis' intent; it is off by default.
