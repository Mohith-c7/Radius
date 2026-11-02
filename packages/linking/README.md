# Radius Linking Package

Owns criterion -> symbol linking (`docs/research/DESIGN.md` 6.2, RQ1; task LK-02). For each confirmed or proposed criterion it ranks the **changed symbols** (LK-01) that plausibly implement it, with a score in [0, 1] and a list of reasons per link. Package decision and egress rules: DEC-026.

Layout follows DEC-003/DEC-007: `domain/` (pure, stdlib only), `application/` (domain only), `infrastructure/` (linkers, symbol documents, call-graph neighbours, rerankers, wiring). Boundaries are enforced by `.importlinter` (run `lint-imports --config packages/linking/.importlinter`) and `tests/test_architecture.py`. No persistence, no HTTP, no clock, no tenant data: linking is a pure function of its inputs. Persistence is LK-05.

## Model

- `CriterionInput(criterion_id, text, rationale, paths, tests, weight, state)`: what the linkers need. `radius_linking.infrastructure.pipeline.criterion_input(criterion)` adapts an IN-01 `Criterion` (rationale = testability rationale; `paths`/`tests` = `.radius/intent.yml` hints).
- `SymbolDoc`: a changed symbol and its searchable text (qualified name, path, kind, change kind, `is_behavioral`, signature, docstring, comments, body identifiers, string/number literals, decorators). `ref = path::qualified_name` is the id used by the benchmark gold links. `build_symbol_docs(changeset, head, base)` builds them from an LK-01 `SymbolChangeSet` and `SnapshotReader`s (Python through `ast`, other languages by regex; a class document excludes its nested definitions; failures degrade to a name/path-only document).
- `Reason(linker, kind, detail, score)` and `Link(criterion_id, symbol_id, linker, score, evidence, rank)`. A per-linker link carries that linker's name; the final edge has `linker == "combined"`. Scores are rounded to 6 decimals at construction so JSON round-trips exactly.
- `LinkSet(snapshot_id, changeset_ref, links, by_linker, algo_versions, config, diagnostics, algo_version)`: `links` are the combined ranked edges (top `top_k` per criterion), `by_linker` every linker's own ranked edges (for ablation and "why"). Ordering and JSON (`to_json`) are deterministic (sorted keys); `from_json` restores it.
- Ports: `LinkerPort.link(criteria, symbols, context) -> list[Link]` (pure; only `score > 0`, each with at least one reason, only for given symbols), `NeighborPort.neighbors(ref) -> {ref: hops}`, `PriorPort`, `Reranker.rerank(criterion, candidates) -> RerankResult`.

## Candidate set

Only the changed symbols passed in. Test symbols (`tests/`, `test_*.py`, `*.spec.ts`, ...) are excluded by default (`exclude_test_symbols`) because tests are evidence, not implementation. At most `max_symbols` (5000) are kept, behavioural first, with a diagnostic when truncated. Links outside this set are never created: the service drops any link a linker returns for another symbol. Blast-radius symbols are not candidates yet (follow-up).

## Linkers

Each is independent, versioned (`version`), explainable (reasons), and returns nothing rather than guessing.

| Linker | Evidence | Score |
| --- | --- | --- |
| `explicit` (`explicit-v1`) | `paths` hint globs (`path::symbol` 0.95, exact file 0.85, wildcard 0.7, directory or `**` 0.5), file paths written in the criterion text (0.9), `tests` hints matched by test naming (file stem 0.35 + name tokens 0.45, max 0.8) | max over hints; all hints kept as reasons |
| `lexical` (`lexical-bm25-v1`) | Pure-Python Okapi BM25 (k1 1.2, b 0.75, Lucene idf) between criterion text (+ testability rationale at half weight) and symbol documents. Fields counted as weights: name x3, docstring x2, decorators x2, path, signature, comments, identifiers, literals x1. Identifiers are split on camel/snake/kebab case and Unicode-normalised; light stemming; prose and code stopwords removed | `0.9 * min(1, raw / ceiling) * (0.5 + 0.5 * coverage)` (see module docs) |
| `identifier` (`identifier-v1`) | Anchors in the criterion: code names, endpoints, HTTP status, quoted error strings, CLI flags, config keys, exception names, numbers; matched exactly or fuzzily (token containment, difflib >= 0.8) to symbol names, literals, route decorators and body identifiers | `weight(kind) * match / (1 + 0.5 (m - 1))`, noisy-OR per symbol, cap 0.92 |
| `structural` (`structural-v1`) | Seeds = symbols with explicit score >= 0.6. Others by proximity: same file 0.6, same dir 0.35, adjacent dir 0.2, call-graph neighbour `0.7 * 0.6^(hops-1)` up to 3 hops (callers and callees via `radius_graph.PythonSymbolGraph`, Python only) | `seed score * proximity`, cap 0.7; silent without hints |
| `change_prior` (`change-prior-v1`) | LK-01 `change_kind` / `is_behavioral`: added 1.0, body/signature 0.95, removed 0.8, decorator 0.8, renamed 0.7, moved 0.5, docstring/comment-only 0.25, formatting-only 0.1 (non-behavioural capped at 0.25) | a modifier, not evidence |

## Combination (`noisy-or-prior-v1`; LK-06 will refine)

```
base  = 1 - prod_i (1 - w_i * s_i)         w: explicit 1.0, identifier 0.9, lexical 0.8, structural 0.6
final = base * (1 - k + k * prior)         k = prior_strength = 0.5
final = min(final, 0.99 if explicit evidence else 0.95)
```

Bounded in [0, 1], monotone non-decreasing in every linker score and in the prior, order independent, zero without evidence (the prior never creates a link). Links below `min_score` (0.01) are dropped; ties break on `symbol_id`. All weights are in `CombineConfig` and recorded in `LinkSet.config`. The noisy-OR assumes independent linkers, which they are not (all read the same names), so scores are rank-calibrated at best. The criterion `weight` does not influence linking.

## Optional re-ranker (off by default)

`Reranker` port with two deterministic fakes (`OverlapReranker`, `FixedReranker`) and `LlmReranker` on the IN-04 `LlmProvider` Protocol. It only re-orders and explains the top `rerank_top_n` (5) candidates the deterministic linkers produced: `final = (1 - 0.35) * deterministic + 0.35 * llm`. The pipeline discards any symbol that was not a candidate, so the model can never add a link.

- Gate: `RADIUS_LLM_LINK_RERANK_ENABLED` and `RADIUS_LLM_LINK_RERANK_ORGS` (comma list or `*`), checked before every provider call through the IN-04 `EgressPolicy`; with the defaults the provider is never called.
- Egress (DEC-021/DEC-026): sanitised criterion text and, per candidate, an opaque ref, kind, qualified name, file path and change kind. **No source code, docstrings, comments, literals, signatures or diffs.** Names and paths are code-derived metadata; enabling the re-ranker means accepting that.
- Guard: `radius_shared.llm_guard` (`sanitize_untrusted` with env-secret masking, nonce-delimited `build_prompt`), strict JSON reply (`{"ranking":[{"ref","score","reason"}]}`, exact keys, no duplicate keys or refs, refs among the candidates, score in [0, 1], reasons without URLs/markup/secrets/nonce), fail closed to the deterministic order, retry/backoff and circuit breaker from IN-04, token caps, only valid answers cached, metadata-only logging, never raises.
- Registered in `tests/security/prompt_injection` (`link-rerank-llm (LK-02)`, both stub models, 196 cases) and unit-tested in `tests/test_llm_rerank.py`.

## Evaluation hooks (not results)

`radius_linking.application.evaluate`: `evaluate_rankings` (Top-1, Top-3, MRR against gold in the `expected.json` `links` shape), `evaluate_linkset` (combined and per linker), `ablation` (all, `without:<linker>`, `only:<linker>`), `links_as_expected` (predictions in the same shape). `scripts/link_eval.py` runs them on the F-14 fixtures (`python scripts/link_eval.py [--json] [--out FILE]`, PYTHONPATH as in CI). Its output is labelled *fixture sanity, not a research result*: the fixtures are tiny hand-written PRs. The RQ1 numbers come from the LK-07 gold set.

## Contracts for later tasks

- LK-05 (IEG, persistence): store `LinkSet.links` (and optionally `by_linker`) as `criterion_symbol_link` rows keyed by `(criterion_id, symbol_id, linker)`; keep `algo_versions`, `config`, `changeset_ref` for reproducibility. `linker` values: `explicit`, `lexical`, `identifier`, `structural`, `change_prior`, `rerank`, `combined`. The design-doc method names (`explicit_ref`, `bm25`, `embedding`, `llm_verified`) map to `explicit`, `lexical`, (not built), `rerank`.
- LK-06: replace `combine_scores` (it receives the per-linker scores from `by_linker` and the prior); keep the cap and monotonicity tests.
- LK-07: gold links are `path::qualified_name`; use `evaluate_*` and `ablation`; results should record `algo_versions`.

## Limitations

- Candidates are changed symbols only; criteria about untouched code get no link, and a criterion no linker recognises gets none (no forced top-1).
- Lexical and identifier evidence is name-based and English-centric (stopwords, stemming); identifiers in other languages work through Unicode splitting only.
- Non-Python languages use regex documents and have no call-graph neighbours.
- `PythonSymbolGraph` is a conservative name-based over-approximation, so call-graph proximity is noisy; it is weighted down.
- Class symbols are scored on their own statements, not their methods.
- Scores are not calibrated probabilities (LK-06).
- Vague criteria rank by weak lexical overlap and can mis-order near-equal candidates (visible on the F-14 vague-intent fixture).

## Follow-ups

Embedding linker with a per-symbol-hash cache; quote-verified `llm_verified` method; blast-radius candidates; code-egress policy for sending code spans to the re-ranker; durable cost ledger; TypeScript call graph; learn linker weights on the LK-07 gold set.
