# Flaky-test handling (F-11)

Goal: a test that passes and fails on the same code must not corrupt evidence. Everything here is deterministic: no wall clock, no randomness in any decision. Code: `packages/testing/src/radius_testing/domain/flakiness.py`.

## 1. Rerun policy (sandbox only)

`WORKER_TEST_RERUNS=N` (default **0 = off**, max 10). With `WORKER_TEST_EXECUTION_MODE=sandbox`, when a pytest command reports failed cases, the failing test files are rerun, each rerun in a fresh hardened container (same limits, timeout, no network). Reruns stop at the first rerun where every failed case passed.

| Per-case outcome | Meaning | Recorded as |
| --- | --- | --- |
| `pass` | never failed | `passed` |
| `flaky` | failed, then passed on at least one rerun | `flaky` (not in `passed`, not in `failed`) |
| `stable_fail` | failed on the first run and every completed rerun | `failed` |

Safety rules:
- A sandbox/runtime error on a rerun (exit 125/126/127/137/152/153, timeout, output cap) aborts the reruns; the original failures stay failures. An error is never evidence of flakiness.
- A first run that ends in an error is never rerun (it stays `error`).
- If the failing cases cannot be identified exactly from the JUnit report, nothing is rerun.
- Only pytest (per-case JUnit) is rerun. Frameworks reporting file-level exit codes only, and the `unsafe_in_process` runner, are not rerun.
- Worst-case time per command is `(1 + N) * WORKER_TEST_TIMEOUT_SECONDS`.
- Each rerun starts from the same read-only snapshot with a fresh `/tmp`, so state cannot carry over between attempts; a test is detected as flaky only if it varies between processes (timing, ordering, randomness, shared services).

## 2. Evidence handling

`TestRunResult` gains `flaky` and `flaky_tests` (`file::name`, sorted). `TestEvidence` carries them. With any flaky test:
- the verdict cannot be `verified`: a verdict gap "N flaky test(s) ... excluded from verification evidence" yields `insufficient_evidence`;
- a `flaky_test` negative evidence item is emitted per test; no `passed` credit is given for it;
- a stable failure still yields `failed`.

`WORKER_FLAKY_POLICY` (default `exclude`):
- `exclude`: as above (flaky is neither pass nor fail).
- `fail`: flaky tests are counted as failures (strictest).

There is deliberately no policy that counts a flaky test as a pass. The v1 heuristic score formula is unchanged; weighting flaky evidence inside `q(e)` is EV-08.

The execution history (`test_execution_histories.status`) records `flaky` for a selected test file with a flaky case when nothing stably failed in the run (otherwise `failed`, as before). No schema change: the column is free text.

## 3. Flakiness score (from history)

Input: a test's samples, oldest first. A sample is `passed`, `failed`, or `flaky` (rerun-detected) plus a `code_key` (the commit sha; a covered-code hash can be supplied instead once available).

Over the last `window` samples (default 20):
- a *comparable observation* is each consecutive pair of `passed`/`failed` samples with the **same non-null `code_key`**; it is a *flip* if the outcomes differ;
- each `flaky` sample is one comparable observation and always a flip.

`score = flips / comparable` in `[0, 1]`, rounded to 4 places. If `comparable < min_comparable` (default 3) there is no score (`None`) and the test is never quarantined. A test is **quarantined** when `score >= threshold` (default 0.2).

Consequences: always-pass and always-fail score 0; a failure fixed by a code change is not a flip (different code key); history on different commits without a shared code key is not comparable. Cross-commit comparison "where the covered code did not change" needs a covered-code fingerprint as the code key; until then comparison is per commit (follow-up).

## 4. Quarantine surface

`GET /analyses/{analysisId}/tests/flaky` (see `docs/API_CONTRACTS.md`) scores every test of the analysis' repository from history. Quarantine is derived, not stored, so it needs no manual state. The dashboard has no natural test-history page yet; the UI is a follow-up.

## Follow-ups
- Dashboard view of quarantined tests.
- Covered-code fingerprint as `code_key` (cross-commit flips).
- Deeper `q(e)` integration, partial weights (EV-08).
- Per-test (not per-file) history rows; persisted manual quarantine/override; auto-excluding quarantined tests from selection.
- Reruns for CI-uploaded results and for jest/vitest (needs per-case reports).
