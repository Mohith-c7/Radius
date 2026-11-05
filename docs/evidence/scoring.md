# Evidence scoring (Verdict v2 alpha)

Implements EV-08 (`quality.py`), VD-01 (`support.py`) and VD-02 (`states.py`) in `radius_evidence.domain`. Design: `docs/research/design/VERDICT_V2_SLICE.md` sections 3.5 and 3.9; decisions DEC-008 and DEC-027. The formulas are reproduced verbatim in `packages/evidence/README.md` (section "Scoring formulas") so they can be cited.

## Pipeline per criterion

1. For every (evidence item, criterion) pair along its best path `c -> s -> t`, `quality.evidence_quality_row` builds an `EvidenceQuality` row: link strength `l`, quality `q`, `term = lambda * q * l`, and a `status` (`counted` or `gated:<reason>`).
2. `support.compute_support` groups counted rows by the symbol on their path, ranks them by term, applies `rho^k`, combines them with a noisy-OR and caps at `s_cap`.
3. `states.evaluate_criterion` maps the `SupportResult` to a `SupportState` (`proven`, `weak`, `unevidenced`, `contradicted`, `excluded`), reason codes and flags (`tampered` is a flag, not a state).
4. `states.intent_coverage` and `states.compute_uim` give the PR-level signals consumed by rules R2a to R2c (VD-03).

## Gating (status codes)

Checked in order, first match wins: `gated:no_criterion_test_edge` (r_ct = 0), `gated:test_link_below_min`, `gated:criterion_link_below_min`, `gated:outcome_<failed|error|skipped|flaky|not_run|none>`, `gated:zero_quality` (q = 0: tamper, stale, rerun-flaky, a_static = 0), else `counted`. A failed or errored test that clears the link gates makes the criterion `contradicted` whatever its authorship or quality.

## Reproduction of the design's worked numbers (gold mode)

`packages/evidence/tests/test_scoring_fixtures.py` runs the 8 F-14 fixtures through the real functions and compares with `verdict_v2.fixture_expectations.json` (tolerance 0.001): all `S(c)` values, states, UIM and intent coverage agree. Hand values: one strong test 0.432, two 0.604, three 0.688, four 0.734; one truthiness test 0.180, two 0.283.

## Decisions taken where the design leaves room

- UIM counts a non-excluded criterion as unproven when its state is not `proven`. This equals `S(c) < tau_support` except when `S >= tau_support` without a strong item (state `weak`, flag `no_strong_assertion`), which would otherwise count as proven mass.
- Threshold comparisons tolerate 1e-12 of float noise, so `S` computed as `0.1 + 0.4` is `proven` at `tau_support` 0.5.
- Counted rows without a symbol share one correlated group (`<unknown>`), the conservative choice.
- An unknown tamper severity label raises `ValueError` rather than being guessed.
