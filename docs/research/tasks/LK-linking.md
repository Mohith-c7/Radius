# Phase LK: Linking and the Intent-Evidence Graph (Milestone M2) -- RQ1

Goal: connect criteria to the code that implements them, and code to the tests/evidence that exercise them. See `../DESIGN.md` section 6.2. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### LK-01 Symbol-level change extraction   [x]
- Owner type: agent-ok
- Depends on: F-08
- Branch: `feature/analysis-changed-symbols` (implemented on `feature/linking-symbol-changes`)
- Size: M
- Goal: for each diff hunk, list changed symbols (function/method/class) with before/after signatures and a change kind (added/removed/modified/signature/behavior/comment-only/rename).
- Steps: extend `packages/analysis` hunk -> symbol mapping; detect pure renames and formatting-only changes; mark generated files; handle moved code.
- Acceptance: on fixtures, changed-symbol sets match expected; comment-only and whitespace-only changes are flagged non-behavioral.
- Tests: table-driven on fixtures; mutation of formatting must not change the symbol set.
- Done: `radius_analysis.symbol_changes` in `packages/analysis`; contract and change-kind semantics in `packages/analysis/README.md`. Consumers: EV-02 reads `change_kind`, `is_behavioral`, `old_range`, `hunks`, `notes`; LK-02/LK-03 read `symbol_id`, `key`, `new_range`, `old_symbol_id`, `new_body_hash`.

### LK-02 Criterion-to-symbol linkers   [x]
- Owner type: pair
- Depends on: IN-03, LK-01
- Branch: `feature/linking-criterion-symbol`
- Size: L
- Goal: produce ranked candidate symbols for each criterion, only among changed symbols plus the blast radius.
- Steps:
  1. `explicit_ref`: file paths, symbol names, endpoint paths, error messages, stack traces in the criterion/source text; `.radius/intent.yml` `paths` hints.
  2. `bm25`: lexical retrieval over symbol names, docstrings, comments, paths.
  3. `embedding`: sentence embeddings (local model by default; provider optional), cached per symbol hash.
  4. `llm_verified` (flagged): LLM must quote the code span supporting the link; link rejected if quote not found.
  5. Each link stores method, confidence, and `cited_evidence`.
- Out of scope: deciding if the code is correct.
- Acceptance: Top-k hit rate and MRR measured on the gold set (LK-07); every non-explicit link has provenance; links outside changed+blast set are not created.
- Tests: per-method unit tests; determinism tests (same inputs, same ranking); embedding cache tests.
- Done: `packages/linking` (`radius_linking`, DEC-026). Deterministic linkers `explicit`, `lexical` (BM25), `identifier`, `structural`, the `change_prior` modifier, a noisy-OR combination and an optional default-off, guarded LLM re-ranker that can only re-order existing candidates. Contract and limits in `packages/linking/README.md`. Consumers: LK-05 persists `LinkSet.links` / `by_linker` (`criterion_id`, `symbol_id`, `linker`, `score`, `rank`, `evidence`, `algo_versions`) into `criterion_symbol_link`; LK-06 replaces `combine_scores` (it receives per-linker scores and reasons in `by_linker`); LK-07 uses `radius_linking.application.evaluate` and `scripts/link_eval.py`. Not done (follow-ups in the README): embedding linker, quote-verified `llm_verified` method, blast-radius candidates beyond the changed set.

### LK-03 Symbol-to-test linkers (incl. dynamic coverage contexts)   [~]
- Owner type: pair
- Depends on: LK-01, F-07
- Branch: `feature/linking-symbol-test`
- Size: XL (split: static; naming; dynamic coverage; semantic)
- Goal: for each symbol, which tests could detect a defect in it.
- Steps: static call/import reachability (exists); naming conventions (exists); **dynamic per-test coverage** via coverage.py dynamic contexts (run the selected tests in the sandbox, record which test executed which lines/symbols); semantic similarity (last resort, low weight). Store method + confidence.
- Acceptance: dynamic links recover tests missed by static analysis on fixtures; link precision/recall vs dynamic truth reported.
- Tests: fixtures with indirect calls, fixtures/parametrized tests, monkeypatching; coverage context merge tests.
- Research hook: compares static vs dynamic linking quality (RQ1/RQ2 context). Cost recorded (time).
- Risks: dynamic coverage needs execution; cache by (symbol hash, test hash).
- Done (static+naming+dynamic done; semantic pending): `radius_testing.linking` in `packages/testing` (README there): `StaticLinker` (import-aware Python, fixtures/conftest, parametrize, inheritance, depth-3 decay, F-08 name layer, partial TS/JS), `NamingLinker`, `DynamicCoverageLinker` (coverage.py per-test contexts, F-07 sandbox only, flag `RADIUS_FEATURE_COVERAGE_CONTEXTS`, offline `.coverage` parsing), monotone `combine_links`, and `scripts/test_link_eval.py` (fixture sanity numbers only). Remaining: semantic/embedding linker, TS depth, `(symbol hash, test hash)` cache (LK-09), persistence (LK-05).

### LK-04 Test assertion extraction   [ ]
- Owner type: agent-ok
- Depends on: LK-03
- Branch: `feature/linking-test-assertions`
- Size: L
- Goal: for each test, extract assertions and what they check (value equality, exception raised, type/None check, mock called, snapshot, "no assertion").
- Steps: AST visitors for pytest/unittest asserts, `pytest.raises`, `mock.assert_*`, snapshot libs; link assertion operands back to symbols via data flow where feasible (best effort, documented); compute `strength_features` consumed by EV-06.
- Acceptance: fixtures cover each assertion kind; tests with no assertions are detected.
- Tests: property tests on random generated test bodies (no crashes).
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: emits AssertionFeatures (3.2) from radius_testing.assertions)

### LK-05 IEG builder and persistence   [ ]
- Owner type: agent-ok
- Depends on: LK-02, LK-03, LK-04, IN-07
- Branch: `feature/ieg-builder`
- Size: L
- Goal: build the Intent-Evidence Graph per (analysis, head SHA) and persist nodes/edges (`criterion_symbol_link`, `symbol_test_link`, `test_assertion`, plus a view for the full graph). Migration `0011`.
- Acceptance: graph reproducible from stored inputs; versioned per SHA; query "all evidence reachable from criterion c" is fast (indexes; tested on a large synthetic graph).
- Tests: graph invariants (no orphan edges, no cross-tenant edges).
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: alpha scope is the in-memory IEG and JSON (3.4); ieg tables are Beta (migration 0017), not 0011)

### LK-06 Link combination and confidence   [x]
- Owner type: agent-ok
- Depends on: LK-02, LK-03
- Branch: `feature/linking-combination`
- Size: M
- Goal: combine multi-method links into one confidence with caps (`DESIGN.md` 6.2): noisy-or across independent methods, cap 0.95 for non-explicit.
- Acceptance: monotonic (adding evidence never lowers confidence); parameters configurable; sensitivity analysis script included.
- Done (branch `feature/linking-chain-confidence`): chain model and per-criterion link confidence `link-chain-v1` in `packages/linking` (`ChainLink`, `CriterionSupportLinks`, `build_support_links`; noisy-AND per chain, noisy-OR with decay per criterion, specificity penalty, test-status discount, explicit unlinked reasons), default `score_kind=link_confidence_uncalibrated`; pure-Python calibration machinery (binning, Platt, isotonic, ECE/MCE/Brier, checksummed JSON artifact) applied only when a fitted artifact is supplied; `scripts/link_chain_eval.py` (fixture sanity only). Contracts for LK-05 and the verdict layer: `packages/linking/README.md`. Not done: fitted calibrators (need IN-09 / LK-07 gold labels) and the sensitivity sweep over the chain constants (needs gold labels; `ChainConfig` is fully parameterised so LK-07 can run it).

- Follow-up VS-04 (branch `feature/linking-criterion-test-relevance`): criterion-to-test relevance `r_ct` in `packages/linking` (`application/relevance.py`, `scripts/relevance_eval.py`; README section "Criterion-to-test relevance"). Closes the LK-06 follow-up "criterion-test relevance signal"; wiring into the chain is VS-05. Fixture sanity only, not a research result.

### LK-07 Link evaluation harness (RQ1)   [ ]
- Owner type: agent-ok
- Depends on: LK-02, IN-09
- Branch: `feature/bench-link-metrics`
- Size: M
- Goal: measure link quality against gold links: Top-1/Top-3 accuracy, MRR, precision/recall at threshold, per method and combined, per language.
- Steps: extend the gold set with criterion->symbol and symbol->test annotations (subset of >= 60 PRs); script outputs table + JSON.
- Acceptance: reproducible with a seed; results stored with `algo_version`.
- Research hook: core RQ1 result table.

### LK-08 IEG API and viewer   [ ]
- Owner type: agent-ok
- Depends on: LK-05
- Branch: `feature/dashboard-ieg-viewer`
- Size: L
- Goal: `GET /analyses/{id}/ieg` plus a viewer that extends `interactive-graph.tsx`: criterion nodes, symbol nodes, test nodes, evidence nodes; edge styles by link method; click to explain "why linked".
- Acceptance: handles up to 2k nodes smoothly (virtualize/collapse); accessible alternative (table view).
- Product hook: the visual that sells the idea in a demo.

### LK-09 Incremental updates on new commits   [ ]
- Owner type: agent-ok
- Depends on: LK-05
- Branch: `feature/ieg-incremental`
- Size: M
- Goal: avoid recomputing everything when a PR gets a new commit; reuse cached links for unchanged symbols (hash-based).
- Acceptance: second commit with a one-file change recomputes only affected parts (measured); results identical to full recompute (equivalence test).
