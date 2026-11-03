# Response to code review B (Verdict v2 core)

Branch `fix/verdict-v2-review-b`, based on `origin/develop` 45a9bcf. Decision record: DEC-037 (`docs/decisions.md`). Review: [CODE_REVIEW_B_VERDICT_V2.md](CODE_REVIEW_B_VERDICT_V2.md).

Commits: **S** = `10caf98` (shared packages, API model, dashboard, schema), **W** = `c67f5e3` (worker). Documentation, DEC and changelog fragments are in the third commit of the branch.

Status words: FIXED (code and regression test), PARTIAL (fixed in part, remainder named), INVALID (none; every finding was reproduced or confirmed by reading the cited lines).

How each finding was checked: B-01 and B-05 were reproduced as failing tests on the unchanged code first (B-01 raised `ValueError: justification invariants violated: R1a.refs.evidence_ids: unknown id 'ev_f000,ev_f001'`; the B-05 test fails when `effective_criteria` is disabled). For the other findings the cited code was re-read and the new test exercises the described scenario, but "fails before, passes after" was **not** run for each one.

| Id | Status | Commit | Tests |
|---|---|---|---|
| B-01 | FIXED | S, W | `packages/confidence/tests/test_verdict_v2_review_b.py` (1, 2, 3, 7, 60 failing tests: no crash, `failed`, `evidence_ids` one per element, sorted); `packages/evidence/tests/test_states.py::test_row2_lists_all_failing_ids_sorted`; `apps/worker/tests/test_verdict_v2_intent_refresh.py::test_recompute_failure_after_a_stored_verdict_replaces_it_with_an_error_row`; `apps/worker/tests/test_verdict_v2_publish.py::test_recompute_failure_marker_replaces_a_published_verdict_with_unavailable` |
| B-02 | FIXED | S, W | `apps/worker/tests/test_verdict_v2_review_b.py` (real LK-01 change sets: sh, Dockerfile, go, sql, yml, tf, vendored path block; inert files and tamper-analysed manifests do not); `test_verdict_v2_collect.py::test_b02_*`; `packages/confidence/tests/test_verdict_v2_rules.py` (R2e/R2d/R2p) |
| B-03 | FIXED | S, W | `test_verdict_v2_review_b.py::test_b03_*` (real tamper engine: a removed assertion in a test file over `max_file_bytes` yields no finding and now `tamper_unanalyzed:files=1`; engine notes; unanalysable docs do not block); `test_verdict_v2_collect.py::test_b03_*` |
| B-04 | FIXED (Stage A column not split) | S, W | `packages/shared/tests/test_verdict_v2_store.py::test_b04_*`; recompute failure test above. Stage A is kept whole up to 8 MB; beyond that the verdict becomes "unavailable" (`stage_a_not_stored`) instead of sticking |
| B-05 | FIXED | W | `test_verdict_v2_review_b.py::test_b05_*` (fixture 08 with tiny author weights: same UIM and verdict as weight 1.0; trusted weights kept) |
| B-06 | FIXED | W | `test_verdict_v2_review_b.py::test_b06_*` (cap, coverage, trusted provenance untouched, one glob hint no longer gives coverage 1.0 on fixture 05) |
| B-07 | PARTIAL | S, W | `test_verdict_v2_intent_refresh.py::test_b07_*`. Done: `confirmed_by` recorded and shown; a label equal to the PR author is not counted; replaceable policy hook; dashboard confirm flow unchanged (a different or missing label still lifts the block). Not done: the label is an unverified header, so an author holding the organisation's API key can confirm under another label (threat model); hints are not confirmed separately; `edited` still keeps the old links |
| B-08 | FIXED | W | `test_verdict_v2_suggested_tests.py::test_b08_*` (the three review bypasses plus reflection, lambdas, loops, `with open`, `__builtins__`; the documented good shapes still pass) |
| B-09 | FIXED | S, W | `test_verdict_v2_publish.py::test_b09_*` (sweep recovers a lost enqueue, is not repeated, ignores analyses without a verdict); `test_verdict_v2_intent_refresh.py::test_b09_*` (manual criterion adds `intent_not_in_analysis:<n>`); `add_criterion` now enqueues (`apps/api/src/radius_api/routes/intent.py`, existing API intent tests pass; no new API test) |
| B-10 | FIXED | S | `packages/github/tests/test_verdict_v2_honesty.py::test_b10_conclusion_table` (17 rows); `packages/confidence/tests/test_verdict_v2_review_b.py::test_b10_*`. Choice: unusable policy gives `action_required` (not `failure`, not `neutral`); docs-only in blocking mode is `neutral`; R2p no longer fires when nothing is in scope |
| B-11 | PARTIAL | S | `packages/intent/tests/test_llm_extraction.py::test_b11_*` (negation, added limiter, swapped roles, word order). Not done: showing the quote next to the text in the confirm UI. Modal words (must/can) may still differ in a paraphrase |
| B-12 | FIXED | S | `packages/confidence/tests/test_verdict_v2_rules.py::test_is_inert_path` (all review examples). The vacuous "inert" of a change with only ignored paths is covered by B-02's marker. `uv.lock` is now inert by owner request (the old test said not inert) |
| B-13 | FIXED | W | `test_verdict_v2_suggested_tests.py::test_b13_*` |
| B-14 | FIXED | S | `packages/testing/tests/test_mutation_measure.py::test_b14_*` (csv, sql, xml, md, bin, lock change the hash; tool directories do not). Over 20000 files or 40 MB the cache is off |
| B-15 | FIXED | W | `test_verdict_v2_publish.py::test_b15_*` (direct `GET /pulls/{n}`; unknown head: `live_head_unknown`, nothing written) |
| B-16 | FIXED (SQLite and memory only) | S | `packages/shared/tests/test_verdict_v2_store.py::test_b16_*`. The Postgres variants of the store tests were skipped (no Postgres here) |
| B-17 | FIXED | S | `test_verdict_v2_store.py::test_b17_*` |
| B-18 | FIXED | S | `test_verdict_v2_store.py::test_b18_*` (mode after shadow to on; `verdict.revision` equals the row revision, also when an older digest returns to the top) |
| B-19 | FIXED | W | `test_verdict_v2_suggested_tests.py::test_b19_*` (stored digest differs per suggestion set, scoring digest and verdict are unchanged, deterministic) |
| B-20 | PARTIAL | S | Schema, API model and shared payload now have `suggested_tests`, `degraded`, `confirmed_by`, `reasons[].refs`. The two payload builders (`scoring.build_payload` and `verdict_v2_payload.build_payload`) still exist and still differ in small ways (the worker one has no outcome fallback); only the second is served |

## Contract changes

Optional fields only; `CONTRACT_VERSION` stays `verdict-v2-contract-5`. New or documented: `reasons[].refs`, `criteria[].confirmed_by`, top-level `degraded`, schema entry for `suggested_tests`; new blocking degraded markers `unanalyzed_files:*`, `tamper_unanalyzed:*`, `intent_not_in_analysis:*`; new error reason codes `recompute_failed:*`, `stage_a_not_stored`; new Check Run conclusion value `action_required`. Updated together: `docs/research/design/verdict_v2.schema.json`, `radius_api.schemas.verdict_v2`, `radius_shared.verdict_v2_payload`, `radius_github.verdict_v2` (view, markdown), `apps/dashboard/lib/verdict-v2-model.ts` and panel, `docs/verdict-v2.md`. `docs/api/openapi.json` is unchanged (`export_openapi.py --check` passes). `ALGO_VERSION` is not bumped.

## Fixtures

`python scripts/verdict_v2_make_fixtures.py --check` passes: the 8 bundles are byte-identical (no gold result changed). Fixture 06 stays `needs_review` because `requirements.txt` is analysed by the tamper catalog and does not count as unanalysed. The `refs` and `confirmed_by` fields are omitted from JSON when absent, so no digest moved.

## Not fixed, needs an owner decision, not verified

- Lockfiles are inert (as requested), although a lockfile edit is a supply-chain change; CI workflows, manifests and build configuration are only checked by the tamper catalog, not by a deeper analyser.
- `confirmed_by` rests on an unverified header; per-person identity on the intent API is needed for real separation of duties.
- Verdicts stored before this change keep their old numbers until their inputs change (no `ALGO_VERSION` bump, to avoid rewriting every golden file).
- `DEC-037` may collide with a parallel branch (mutation stage 2 uses DEC-036); renumber on merge if needed.
- Not run: Postgres tests (skipped), the dashboard's TypeScript tests and type check (no `node_modules`), any Docker or live GitHub flow. The dashboard edits are two optional fields and one line of text.
- Merge conflicts are likely in `apps/worker/src/radius_worker/verdict_v2/scoring.py` and `packages/testing/src/radius_testing/mutation/measure.py` with the mutation stage 2 branch.
