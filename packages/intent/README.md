# Radius Intent Package

Owns the intent layer: what a change is supposed to do, as confirmable, testable criteria with provenance (`docs/research/DESIGN.md` 6.1, RQ1). IN-01 delivered the pure domain model and ports; IN-07 added persistence; IN-03 adds deterministic (LLM-free) criterion extraction; IN-06 adds the snapshot service (versioning, carry-over of human decisions, diffs). No HTTP or LLM calls yet.

Layout follows DEC-003/DEC-007: `domain/` (pure), `interfaces/` (ports), `application/` (use cases: domain + ports only) and `infrastructure/` (repositories in IN-07, `extraction/` in IN-03).

## Formal model

Let a *source* be `s = (id, kind, text, h, f, tr, sus)`: `kind` in {pr_body, pr_title, issue, commit_message, spec_file, agent_prompt, comment}, `text` the sanitized string, `h` the SHA-256 of the raw fetched text, `f` the caller-supplied fetch time, `tr` / `sus` booleans recording truncation and removal of hidden or suspicious content (IN-02).

A *span* is `(s.id, a, b)` with `0 <= a < b <= len(s.text)`; the half-open range `[a, b)` of characters.

*Provenance* is `(ref(s), retrieved_at, method, extractor_version)` with `method` in {deterministic, llm, human}. All times are caller-supplied and timezone-aware; the domain never reads a clock.

A *criterion* is `c = (id, text, norm, origin, span, w, t, r, st, h)` where `h = (paths, tests, label)` are optional author hints (`CriterionHints`, IN-03) that never affect the id:

- `norm = normalize(text)`: Unicode NFKC, drop format characters (category Cf, e.g. zero-width and bidi controls), casefold, collapse whitespace; non-empty and idempotent.
- `id = "crit_" + sha256("crit-id-v1" NUL "<kind>:<source id>" NUL norm)[:32]`. Fixed at creation, stable under edits, re-weighting, rating and state changes; independent of the source hash, so unrelated edits to a source keep ids. Changing the derivation requires bumping `CRITERION_ID_ALGO` (plan 1.6).
- `w` in (0, 1]; `t` in {unrated, testable, vague, non_functional}; `r` optional non-blank rationale.
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

`radius_intent.application.IntentSnapshotService(repository, extractors, fetcher=None)` turns sources plus extracted criteria into immutable, versioned snapshots. It depends only on the domain and ports (import-linter contract `application-uses-domain-and-ports-only`), reads no clock (`now` is an argument) and does no HTTP or LLM calls.

```
sources (IntentSource | SourceRequest -> IntentSourceFetcher)      absent -> diagnostic, not an error
        |
        v   each CriterionExtractor, per source (a failure is isolated + reported)
   candidates --select_criteria--> live criteria (dedupe, total order)
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

IN-09's gold set does not exist yet. `score_extraction(predicted_texts, gold_texts, fuzzy_threshold=None)` returns `PrecisionRecall` (one-to-one greedy matching on normalized text, optionally fuzzy by content-token Jaccard) and `score_by_source_kind(cases)` micro-averages over `GoldCase(kind, predicted, gold)` per source kind. No CLI, no I/O.

### Limitations

English-only modal rules (other languages extract only via lists, tables, Gherkin and spec files). One criterion per list item or sentence: compound statements are not split (IN-04). Markdown handling follows GitHub loosely, not CommonMark exactly (child lists need only a deeper marker; indented code blocks are not recognised; a `---` rule does not end a section). `Steps to Verify` steps and `Scope` bullets are taken as criteria, which can lower precision. Checkbox state is trace-only. Sources over the ingestion limit are read as given (IN-02 truncates).
`python -m pytest packages/intent/tests --cov=radius_intent.domain --cov=radius_intent.application --cov-branch`
