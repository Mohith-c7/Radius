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

## Combination of linkers (`noisy-or-prior-v1`)

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

## Chains and link confidence (LK-06, `link-chain-v1`)

Unifies the criterion -> symbol family (this package) and the symbol -> test family (`radius_testing.linking`, LK-03) into one chain `criterion -> symbol -> test`. `radius_linking` never imports `radius_testing` (import-linter): the second hop enters through the plain-data port `SymbolTestEdge` (`symbol_id, test_id, score, kind, linker, low_confidence, evidence, components`). The composition layer converts LK-03 links with `SymbolTestEdge.from_object(link)` (duck typed, so `SymbolTestLink`, its enum `kind` and `components` work unchanged); `scripts/link_chain_eval.py` is the reference composition.

Entry point: `radius_linking.application.build_support_links(criterion_ids, c2s_links, s2t_edges, *, symbols=None, test_status=None, hinted_tests=None, config=ChainConfig(), criterion_calibration=None, chain_calibration=None) -> SupportLinkSet`. Pure, deterministic, offline; input order does not matter (tested). Only `combined` criterion -> symbol links (`LinkSet.links`) are used.

### Domain

- `ChainLink(criterion_id, symbol_id, test_id, c2s: Link, s2t: SymbolTestEdge, chain_score, reasons, raw_chain_score, specificity, test_status, score_kind)`; `support_score = raw_chain_score * specificity`.
- `CriterionSupportLinks(criterion_id, chains, link_confidence, unlinked_reason, reasons, raw_link_confidence, score_kind, suspicious, algo_version)`. `link_confidence` answers "how sure are we that relevant tests are wired to this criterion's code"; it is not test quality and not a verdict.
- `SupportLinkSet(criteria, algo_version, score_kind, config, calibration, diagnostics)`: criteria in id order, chains by `(-support, symbol_id, test_id)`, `to_json` with sorted keys, exact `from_json`. `config` records every constant.

### Chain rule

```
a = c2s score     e = highest explicit-linker reason score on the c2s link     b = s2t score
h1 = max(a, 0.95 * e)                       explicit hints dominate hop 1
h2 = max(b, 0.92)      if dynamic coverage evidence (kind or a "dynamic" component)   dominates hop 2
   = 0.85 * b          if the link is flagged low_confidence (and not dynamic)
   = b                 otherwise
base  = h1 * h2                              noisy-AND: both hops must be strong
agree = min(1, (L1 - 1 + L2 - 1) / 3)        L1, L2 = independent linkers per hop (change_prior/rerank ignored)
chain = 1 - (1 - base) * (1 - 0.3 * agree)   only when min(h1, h2) >= 0.5
chain = min(chain, 0.99 if (e >= 0.5 and dynamic) else 0.95)
chain = chain * status_factor(test)          passed/unknown 1.0, flaky 0.5, failed 0.4, skipped 0.1
no chain if min(h1, h2) < 0.05 or chain < 0.01
```

The 0.95 cap for non-explicit evidence is DESIGN 6.2; a chain is only above it when an explicit hint and measured execution both hold.

### Per-criterion aggregation

```
specificity(t) = max(0.5, 1 / (1 + 0.15 * max(0, n_t - 2)))   n_t = criteria with a chain through t scoring >= 0.3
support        = chain * specificity
per test:        best support only (one test reached through two symbols counts once)
confidence     = min(cap, 1 - prod_i (1 - 0.7^i * support_i))   i = 0.., top 5 tests by support
cap            = 0.99 if a counted chain is explicit+dynamic else 0.95
```

Diminishing returns (`0.7^i`) keep a pile of weak tests from outweighing one strong chain. Specificity penalises tests that "cover" many unrelated criteria (typically broad integration tests). It is a corpus-level effect, so it is the one input where evidence added for another criterion can lower this criterion; for a single criterion the rule is monotone (tested). Work is bounded: at most 10 symbols per criterion, 10 tests per symbol and 10 chains kept (`ChainConfig`); 2000 criteria x 50 symbols x 20 tests runs in about 8 s (tested < 30 s).

Properties (seeded random property tests): confidence and chain score are monotone non-decreasing in every link score, in added linkers or components, in added dynamic evidence and in added chains; removing a hop or a chain cannot raise them; no chain exceeds its cap; output is independent of input order.

### Unlinked outcomes (`unlinked_reason`, confidence 0)

| Code | Meaning |
| --- | --- |
| `no_symbol_candidates` | no criterion -> symbol link at all |
| `only_non_behavioral_symbols` | every candidate is `formatting_only`, `docstring_or_comment_only` or `is_behavioral=False` (needs `symbols`) |
| `untested_change` | symbols are linked but none has a test link (a coverage gap) |
| `tests_without_symbol` | author hinted tests (`hinted_tests`) but no symbol: `suspicious = True` |
| `only_weak_chains` | chains exist but all fall below the floors, for example only skipped tests |

### Reason codes (`Reason.linker == "chain"`, `Reason.kind`)

Chain: `hop1_criterion_symbol`, `hop1_explicit_dominance`, `hop2_symbol_test`, `hop2_dynamic_dominance`, `hop2_low_confidence`, `chain_noisy_and`, `agreement_bonus`, `chain_cap`, `test_status_discount`, `specificity_penalty`, `calibrated`. Criterion: `aggregate_term` (one per counted test, with its weight), `aggregate_cap`, `excluded_non_behavioral`, `untested_symbol` (a linked symbol without tests), `hinted_test_without_symbol`, `unlinked`, `unlinked_not_calibrated`, `calibrated`. `Reason.score` is the number the step used and `detail` shows the arithmetic; `explain(cs)` renders them.

### Calibration policy

Calibration maps a score to P(link correct), which needs gold labels (IN-09 / LK-07, not available). Therefore **`score_kind` is `link_confidence_uncalibrated` by default** and the numbers are rank-oriented, not probabilities: 0.8 does not mean "80 percent right". A calibrator is applied only when a fitted `CalibrationArtifact` is passed (`criterion_calibration` for the criterion confidence, `chain_calibration` for chain scores; the artifact's `target` must match or `CalibrationError` is raised). Then `link_confidence` holds the calibrated value, `raw_link_confidence` / `raw_chain_score` keep the original, ordering and aggregation stay on raw scores, `score_kind` becomes `link_confidence_calibrated`, `SupportLinkSet.calibration` records artifact id, method and fit metadata, and a `calibrated` reason is added. Unlinked criteria stay at exactly 0.

Machinery in `radius_linking.domain.calibration` (pure Python, deterministic): `BinningCalibrator`, `PlattCalibrator` (`p = 1 / (1 + exp(A s + B))`, damped Newton on Platt-smoothed targets), `IsotonicCalibrator` (weighted PAV, linear interpolation, clipped), the `Calibrator` protocol (`fit(scores, labels)`, `transform(score)`, `params()`), `reliability_bins`, `expected_calibration_error`, `maximum_calibration_error`, `brier_score`, `reliability_report`, and `CalibrationArtifact` (JSON: version `link-calibration-v1`, method, target, params, fit metadata, SHA-256 checksum verified on load; no clock or host data, so artifacts are reproducible). `fit_artifact(method, scores, labels, target=..., dataset_id=...)` records in-sample before/after ECE and Brier; evaluate on held-out data before trusting a calibrator. Isotonic and Platt were cross-checked against scikit-learn in a throwaway environment outside the repo (isotonic predictions identical to 1e-16, Platt A and B within 2e-6 on 20 random sets); the tests use hand-computed values and do not need scikit-learn.

### Evaluation hook (not results)

`python scripts/link_chain_eval.py [--json] [--out FILE] [--calibrator ARTIFACT.json]`: on the F-14 fixtures (static and naming symbol -> test links; the dynamic linker needs the sandbox and is not run) it reports chain Top-1/Top-3/MRR, recall of gold `(criterion, symbol, test)` triples, whether criteria with a gold symbol but no gold test get confidence 0, and reliability bins, ECE, MCE and Brier when both labels exist. Output is labelled *fixture sanity, not a research result*.

### Contracts for later tasks

- LK-05 (IEG, persistence): persist chains as `(analysis, criterion_id, symbol_id, test_id)` rows with `chain_score`, `raw_chain_score`, `specificity`, `test_status`, `score_kind`, `reasons` and the two hop payloads (`c2s`, `s2t`) as JSON; persist per-criterion `link_confidence`, `raw_link_confidence`, `unlinked_reason`, `suspicious`, `score_kind`; store `SupportLinkSet.algo_version`, `config` and `calibration` for reproducibility. A (symbol, test) pair is shared across criteria; `s2t.components` carries provenance.
- Verdict layer: `l(c, e)` in `S(c) = 1 - prod(1 - lambda * q * l)` (DESIGN 6.4) is `ChainLink.chain_score` for evidence test `e`; `link_confidence` is a criterion-level summary, not a replacement for the per-test `l(c, e)`. Treat `unlinked_reason` as a state input (`untested_change` means no evidence, `tests_without_symbol` is a flag). Never present `link_confidence_uncalibrated` as a probability. A passing test that exercises the code is not evidence that it checks this criterion: evidence quality `q` (LK-04 assertions, mutation) must multiply on top.

## Criterion-to-test relevance `r_ct` (VS-04, `criterion-test-relevance-v1`)

LK-03 links a symbol to its tests, per function. When one function implements several criteria, every test of it would support every criterion (finding F4 of `VERDICT_V2_SLICE.md`: on fixture 08 the untested criterion C4 got credit from three unrelated tests). `radius_linking.application.relevance` estimates, for a `(criterion, test)` pair connected through a changed symbol, how relevant the test is to THAT criterion: `CriterionTestRelevance(criterion_id, test_id, r_ct, reasons, symbol_ids, rank)` in [0, 1]. Deterministic, offline, no LLM.

Entry points: `score_relevance(criteria, test_docs, connections, config)`, `connected_pairs(c2s_links, s2t_edges)` (combined criterion -> symbol links x combined symbol -> test edges, as `build_support_links` uses), `relevance_from_links(...)`, `relevant_tests(set, criterion_id, threshold=0.3)`.

Inputs are plain data (`radius_linking.domain.relevance`): `TestDoc(test_id, name, docstring, param_ids, assertions, literals)` with `AssertionFact(subject, expected, kind, symbol_names, exception_type)`. `AssertionFact.from_assertion_dict` adapts the `to_dict()` shape of an LK-04 `AssertionRecord`; `radius_linking` imports neither `radius_testing` nor `radius_evidence`.

### Signals

| Reason code | Signal |
| --- | --- |
| `lexical_overlap` | normalised BM25 (`sum(term score) / sum(per-term ceiling) * 1.5`, clamped to 1) of the criterion terms against the test document: name x3, docstring x2, assertion expected values x2, exception types x2, parametrize ids, subjects, asserted names, literals x1. Same tokenizer as LK-02, plus synonym and number-word canonicalisation (`raises`/`rejects`/`invalid`, `eight` -> `8`). Terms naming the connecting symbol are removed from the query |
| `assertion_subject` | weighted share of criterion anchors found in what the test asserts: exception names (1.0), HTTP status codes (1.0), quoted tokens (1.0), code identifiers (0.7), numbers (0.5) |
| `exception_match` | the criterion is about an error and the test asserts an exception: 0.4, or 1.0 when the exception type matches |
| `explicit_hint` | a `tests` hint (`.radius/intent.yml`; test id, bare test name, or test file) gives `r_ct = 1.0` and is exempt from every penalty. A hinted test needs no symbol connection |
| `name_convention` | share of the `test_<behavior>` name words (symbol terms removed) that occur in the criterion |
| `specificity_penalty` | factor `max(0.5, 1 / (1 + 0.15 * max(0, n - 2)))`, `n` = criteria the test relates to with `r >= 0.3` (same shape as the LK-06 chain specificity) |
| `behavior_mismatch` | criterion is about an error but the test checks none: x0.25; test checks an error but the criterion states normal behaviour without a constraint word (`needs`, `at least`, `must`, ...): x0.6 |
| `exception_type_mismatch` | the criterion names an exception type and the test expects another specific one: x0.3 |
| `asserts_other_symbols` | the test's assertions name callables, none of which is a connected symbol: x0.3 |
| `no_signal`, `below_floor` | gate outcomes, both give exactly 0.0 |

### Rule

```
fired = signals with 0 < s_i >= signal_floor (0.1)           none fired -> r_ct = 0.0 (reason no_signal)
pos   = 1 - prod_{i fired} (1 - w_i * s_i)                   w: assertion/exception 0.9, lexical 0.7, name 0.6
r0    = pos * prod(negative factors)
r_ct  = r0 * specificity(test)                               r_ct < r_floor (0.05) -> 0.0 (reason below_floor)
hint  -> r_ct = 1.0
```

Monotone non-decreasing in every positive signal and weight, the factors only lower the score, and all constants are in `RelevanceConfig` (recorded in `RelevanceSet.config`). Output is ranked per criterion by `(-r_ct, test_id)`, independent of input order, with exact JSON round trip. The BM25 corpus is the `test_docs` passed in, so `idf` depends on it: pin the corpus (all test functions of the test files touched or exercised).

### Evaluation hook (fixture sanity, not a research result)

`python scripts/relevance_eval.py [--threshold 0.3] [--json] [--out FILE]` builds `TestDoc`s from the F-14 fixtures with a light `ast` extractor, connects every test that calls a criterion's gold symbol to that criterion (the F4 situation) and scores precision/recall of `r_ct >= threshold` against the gold `links[].tests`, next to the symbol-only baseline "every connected test gets credit". On the 8 fixtures (in-sample, constants set while looking at them): 17 of 29 gold pairs found, 0 false pairs, precision 1.0, recall 0.586; the baseline has precision 0.40, recall 0.97. Fixture 08: all 4 gold pairs found, C4 (untested) gets 0.0 from all 4 other tests; fixture 02: C2 (no real test) gets at most 0.077 (below 0.3) from the two weak tests.

### Limits

- Lexical and assertion evidence only: no semantics. Fixture 05 (both criteria) and part of 01 C1, 02 C1, 03 C2 are missed because the criterion words appear neither in the test name nor in its assertions; a `tests:` hint is the fix in practice. Missing credit is preferred to false credit.
- Borderline scores exist (for example 04 C1 at 0.300); the threshold and constants are not tuned on held-out data and not calibrated probabilities.
- Specificity counts criteria, not shared evidence terms. English-centric stemming and synonyms (small hand-written table). Quoted anchors without a letter or digit (`'-'`) cannot be matched.
- Assertion facts are only as good as the supplied extractor; with no `AssertionFact`s the name, docstring and literal signals still work and the assertion-based penalties are off.

## Contracts for later tasks

- LK-05 (IEG, persistence): store `LinkSet.links` (and optionally `by_linker`) as `criterion_symbol_link` rows keyed by `(criterion_id, symbol_id, linker)`; keep `algo_versions`, `config`, `changeset_ref` for reproducibility. `linker` values: `explicit`, `lexical`, `identifier`, `structural`, `change_prior`, `rerank`, `combined`. The design-doc method names (`explicit_ref`, `bm25`, `embedding`, `llm_verified`) map to `explicit`, `lexical`, (not built), `rerank`.
- LK-06 (done): chain model and link confidence on top of this combination, see "Chains and link confidence" below; `combine_scores` is unchanged and still produces the criterion -> symbol score that hop 1 consumes.
- LK-07: gold links are `path::qualified_name`; use `evaluate_*` and `ablation`; results should record `algo_versions`.

## Limitations

- Candidates are changed symbols only; criteria about untouched code get no link, and a criterion no linker recognises gets none (no forced top-1).
- Lexical and identifier evidence is name-based and English-centric (stopwords, stemming); identifiers in other languages work through Unicode splitting only.
- Non-Python languages use regex documents and have no call-graph neighbours.
- `PythonSymbolGraph` is a conservative name-based over-approximation, so call-graph proximity is noisy; it is weighted down.
- Class symbols are scored on their own statements, not their methods.
- Scores are not calibrated probabilities. LK-06 ships the calibration machinery but no fitted calibrator (it needs gold labels, IN-09 / LK-07), so everything is `link_confidence_uncalibrated`.
- Vague criteria rank by weak lexical overlap and can mis-order near-equal candidates (visible on the F-14 vague-intent fixture).

## Follow-ups

Embedding linker with a per-symbol-hash cache; quote-verified `llm_verified` method; blast-radius candidates; code-egress policy for sending code spans to the re-ranker; durable cost ledger; TypeScript call graph; learn linker weights on the LK-07 gold set.

LK-06 follow-ups: fit and ship calibrators on the LK-07 gold set (held-out, split by repo); a criterion-test relevance signal (done in VS-04, `r_ct`; wiring it into `ChainLink` is VS-05); sensitivity sweep of the chain constants on gold labels; learn `status_factors` and `decay` instead of fixing them; temperature scaling and conformal wrappers for RQ3.
