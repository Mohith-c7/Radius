# Radius Intent Package

Owns the intent layer: what a change is supposed to do, as confirmable, testable criteria with provenance (`docs/research/DESIGN.md` 6.1, RQ1). IN-01 delivers the pure domain model and ports only. No persistence, HTTP or LLM calls.

Layout follows DEC-003/DEC-007: `domain/` (pure), `interfaces/` (ports), `application/` and `infrastructure/` (empty until IN-02+).

## Formal model

Let a *source* be `s = (id, kind, text, h, f, tr, sus)`: `kind` in {pr_body, pr_title, issue, commit_message, spec_file, agent_prompt, comment}, `text` the sanitized string, `h` the SHA-256 of the raw fetched text, `f` the caller-supplied fetch time, `tr` / `sus` booleans recording truncation and removal of hidden or suspicious content (IN-02).

A *span* is `(s.id, a, b)` with `0 <= a < b <= len(s.text)`; the half-open range `[a, b)` of characters.

*Provenance* is `(ref(s), retrieved_at, method, extractor_version)` with `method` in {deterministic, llm, human}. All times are caller-supplied and timezone-aware; the domain never reads a clock.

A *criterion* is `c = (id, text, norm, origin, span, w, t, r, st)`:

- `norm = normalize(text)`: Unicode NFKC, drop format characters (category Cf, e.g. zero-width and bidi controls), casefold, collapse whitespace; non-empty and idempotent.
- `id = "crit_" + sha256("crit-id-v1" NUL "<kind>:<source id>" NUL norm)[:32]`. Fixed at creation, stable under edits, re-weighting, rating and state changes; independent of the source hash, so unrelated edits to a source keep ids. Changing the derivation requires bumping `CRITERION_ID_ALGO` (plan 1.6).
- `w` in (0, 1]; `t` in {unrated, testable, vague, non_functional}; `r` optional non-blank rationale.
- `st` in {proposed, confirmed, rejected, edited} with allowed transitions: proposed -> {confirmed, rejected, edited}; edited -> {confirmed, rejected, edited}; confirmed -> {edited, rejected}; rejected -> {proposed}.

An *intent snapshot* is `(id, analysis_id, version, created_at, [c1..cn], refs, parent)`: ordered criteria with pairwise distinct ids, every criterion citing a source ref present in `refs` at the same hash; `version = 1` iff no parent. `diff(old, new)` matches by id: `added = new \ old`, `removed = old \ new`, `changed = {id : old[id] != new[id]}` (any field).

## Invariants and errors

Enforced in constructors; all raise subclasses of `IntentDomainError` (a `ValueError`): `InvalidSpanError`, `InvalidProvenanceError`, `InvalidSourceError`, `InvalidCriterionError` (+ `InvalidWeightError`), `InvalidStateTransitionError`, `InvalidSnapshotError` (+ `DuplicateCriterionError`). `Criterion.create(source, span, ...)` additionally checks that the span names that source and lies within its text.

## Ports (`radius_intent.interfaces`)

`IntentSourceFetcher.fetch(analysis_id, kind, reference) -> IntentSource | None` (absent is `None`, not an error), `CriterionExtractor.extract(source) -> tuple[Criterion, ...]`, `TestabilityRater.rate(criterion) -> TestabilityAssessment`.

## Domain purity

`radius_intent.domain` may import only the standard library and `radius_intent.domain`. Enforced by `tests/test_architecture.py` (AST check, runs under pytest) and by the import-linter contract `.importlinter` (CI step; locally `PYTHONPATH=packages/intent/src lint-imports --config packages/intent/.importlinter`).

## Tests

`python -m pytest packages/intent/tests --cov=radius_intent.domain --cov-branch`
