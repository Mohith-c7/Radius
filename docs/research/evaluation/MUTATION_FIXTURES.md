# Mutation on the F-14 fixtures: fixture sanity, not a research result

**What this is.** A smoke test that the mutation prototype (`packages/testing/src/radius_testing/mutation/`, design in `../design/MUTATION_EVIDENCE.md`) produces sensible kill matrices on the eight hand-written F-14 intent fixtures, and a descriptive comparison with the fixtures' labelled test-strength bands and with `a_static`.
**What this is not.** Eight tiny fixtures, 33 labelled tests, labels written by the same team that wrote the fixtures. Nothing here estimates a detection rate, a correlation or an effect, and no threshold was calibrated. Do not cite any number below as evidence for or against RQ2.

## Reproduce

The local runner executes the fixture code on this machine. That is acceptable only because the fixtures are our own trusted code, and it refuses to start unless you opt in.

```bash
# bash, from the repository root (Linux/macOS use ':' instead of ';' in PYTHONPATH)
export RADIUS_MUTATION_ALLOW_LOCAL=1
export PYTHONPATH="packages/testing/src;packages/shared/src;packages/evidence/src;packages/intent/src;packages/linking/src;packages/analysis/src;packages/confidence/src"
python scripts/mutation_fixture_eval.py --json out.json --markdown out.md      # all 8 fixtures, about 6 minutes
python scripts/mutation_fixture_eval.py 03 08                                   # a subset
python scripts/mutation_fixture_eval.py 02 03 --operators ROR,AOR,BOOL,NEG,CON,RET,EXC,CALL,ARG,CRM,CALLX   # exploratory, see below
```

PowerShell: `$env:RADIUS_MUTATION_ALLOW_LOCAL = "1"; $env:PYTHONPATH = "packages/testing/src;..."` then the same `python scripts/mutation_fixture_eval.py ...`. Without the opt-in the script exits with status 2.

Defaults used for the tables below: seed 0, at most 30 mutants per fixture (sampling never triggered: the largest fixture generated 29), 60 s per-mutant timeout, one baseline run and no survivor reruns (to keep the runtime small; flaky handling is covered by unit tests, not by this run). Re-running gives identical kill matrices (checked on fixture 03; ids and order are deterministic). Wall time on a Windows dev box: 352 s for 105 mutants, about 3 s per pytest invocation, mostly interpreter and pytest start-up.

## Method

1. LK-01 (`extract_symbol_changes`) over `base/`, `head/` and `pr.patch` gives the changed behavioural symbols in non-test Python files. The mutants are generated over each symbol's `new_range` only. Module-level changes (for example a constant) appear as `<module>`.
2. The fixture tests run against the HEAD tree once (baseline; tests failing at HEAD are excluded) and then against each mutant in a temp copy (never the fixture directory). A test "kills" a mutant if it passes at baseline and fails on the mutant.
3. Strength measures per test: `d_mut` = kills / all non-equivalent mutants of the changed symbols (EV-05 literal), and `d_reach` = kills / the mutants whose line the test executes (a `sys.settrace` plugin run once per fixture). `a_static` is the real EV-06 value computed from LK-04 assertions (`features_from_assertion_set` then `a_static`).
4. Bands, **fixed before looking at any result** (arbitrary, not calibrated): `none` = 0 kills; `strong` = `d_reach >= 0.5` (headline) or `d_mut >= 0.20`; otherwise `weak`; `n/a` if the sample guard fails (fewer than 3 reached or 5 total mutants). `a_static`: strong >= 0.6, weak in (0, 0.6), none = 0.
5. Criteria use the fixture's gold links (`expected.json` `links`). `D(c)` is the union of kills by the criterion's linked tests over all non-equivalent mutants of the linked symbol; `lcb` is its Wilson lower bound.

## Summary per fixture

"Expected" is the band in `expected.json` `evidence_quality`. Agreement counts tests with a label and a defined measured band. `d_reach`/`d_mut` columns use the thresholds above.

| fixture | tests labelled (strong / weak / none) | mutants (killed / survived / suspect) | measured strong (`d_reach`) | `a_static` agrees with label | `d_reach` agrees | `d_mut` agrees | note |
|---|---|---|---|---|---|---|---|
| 01 correct, strong tests | 6 / 0 / 0 | 19 (18 / 0 / 1) | 4 of 6 | 6 of 6 | 4 of 6 | 6 of 6 | two strong boundary tests score 0.47 and 0.35; C1 `D` 0.667, C2 `D` 0.389 |
| 02 correct, weak tests | 0 / 2 / 1 | 7 (4 / 2 / 1) | 2 of 3 (both labelled weak) | 2 of 3 | 0 of 2 (+1 n/a) | 1 of 3 | weak tests kill 4 of 6 mutants; irrelevant `test_domain_of` kills 0 |
| 03 incorrect, passes weak tests | 0 / 2 / 2 | 5 (4 / 1 / 0) | 1 of 3 | 2 of 4 | 1 of 3 | 1 of 4 | 5 mutants only; C2, C3 `D` 0.2 (lcb 0.04) |
| 04 test tampering | 2 / 1 / 3 | 2 (1 / 1 / 0) | n/a | 4 of 4 | n/a | n/a | 2 mutants, below every guard; 2 labelled tests do not pass at HEAD |
| 05 scope creep | 4 / 0 / 0 | 9 (7 / 2 / 0) | 3 of 4 | 4 of 4 | 3 of 4 | 3 of 4 | unlinked `config` constant mutant survives (1 of 1): the scope-creep change has no test |
| 06 hallucinated dependency | 5 / 0 / 0 | 29 (26 / 3 / 0) | 3 of 5 | 5 of 5 | 3 of 5 | 3 of 5 | two reject-input tests score 0.27; C2 `D` 0.308 (lcb 0.13) |
| 07 vague intent | 1 / 1 / 0 | 6 (5 / 1 / 0) | 1 of 2 | 2 of 2 | 0 of 1 (+1 n/a) | 1 of 2 | no linked tests for C1, C2; `summarize` reaches only 2 mutants |
| 08 multi-criterion, partial evidence | 3 / 1 / 1 | 28 (20 / 8 / 0) | 1 of 5 | 1 of 5 | 2 of 5 | 2 of 5 | C4 has no tests and `D` 0.0, as labelled `unevidenced` |

Totals over labelled tests with a defined band: `a_static` 26 of 33, `d_mut` 17 of 29, `d_reach` 13 of 26. Descriptive only.

Threshold-free view (mean and count by label; AUC of "label strong vs weak or none", ties counted half; tiny n):

| measure | mean for strong (n) | mean for weak (n) | mean for none (n) | AUC strong vs rest | AUC (strong or weak) vs none |
|---|---|---|---|---|---|
| `a_static` | 0.855 (21) | 0.279 (7) | 0.340 (5) | 0.88 | 0.79 |
| `d_mut` | 0.344 (19) | 0.473 (6) | 0.068 (4) | 0.55 | 0.93 |
| `d_reach` | 0.521 (18) | 0.556 (6) | 0.325 (2) | 0.50 | 0.82 |

## Reading it honestly

On these fixtures the static score matches the labelled bands better than mutation does, and mutation does something different from what the labels encode.

**Where mutation and the labels agree, and `a_static` does not.** Tests that exercise code the PR did not change get `a_static` 1.0 (they contain exact value checks) but kill nothing: `test_domain_of` (02), `test_line_total_multiplies` (01), `test_title_case` (05), `test_release_restores` and `test_stock_value` (04). The labels call `test_domain_of` "none"; `a_static` says strong, mutation says 0 kills. These are irrelevant tests rather than weak ones; in the pipeline the symbol-to-test link (`l_st`) and criterion link already discount them, and the measurement agrees with that discount. It is the clearest case for mutation as an independent check on the links.

**Where `a_static` calls a test strong but the mutants say otherwise.** Besides the irrelevant tests above: the two reject-input tests of fixture 06 (`a_static` 0.8, `d_reach` 0.27) and `test_slugify_empty` (05, 1.0 versus 0.17). They are strong in the label's sense (exact exception or value) but narrow: the function has many behaviours and one test pins one of them, so a per-test fraction is small. A per-test detection score measures breadth as well as strength; the criterion-level union `D(c)` is the better summary of "how much of this symbol is pinned by the evidence for this criterion".

**Where `a_static` calls a test weak and the mutants say it detects a lot.** `test_normalize_*` (02, `a_static` 0.25, `d_reach` 0.8), `test_clamp_above_is_bounded` (03, 0.35 versus 0.75), `test_top_is_bounded` (07, 0.3 versus 0.67), `test_accepts_eight_characters` (08, 0.25 versus 0.61). Cause: many default-set mutants make the code crash or return `None` (`RET`, `EXC`, `NEG`, `CRM`, `ROR` on a guard), and even a truthiness assertion notices a crash. The default set has no operator that changes a *computed value* through a call chain such as `addr.strip().lower()`. This is an operator gap, not evidence that truthiness tests are good. An exploratory rerun of fixtures 02 and 03 with an opt-in operator `CALLX` (call replaced by its operand, added after seeing this result, so post hoc) adds three mutants to fixture 02 (`addr.strip()` removed, `addr.lower()` removed): both survive the two weak tests, `D(C1)` falls from 0.667 to 0.444, and the surviving mutants name exactly what is unproven. The weak tests still reach `d_reach` 0.57 by killing the crash-type mutants, so the fixed `>= 0.5` rule would still label them strong. Fixture 03 is unchanged because `clamp` has no call chain. Consequence for the design: report **which mutants survive** (the explanation) at least as prominently as a number, and decide the operator set (D1, tier B) before the pre-registration freeze.

**Where the label is arguably the problem.** `test_clamp_returns_an_int` (03, label "none", `isinstance` check) kills one mutant (`return None`) and `test_is_blank` (08, label "none") kills two. A type check does notice `None`. The band is a judgement about intent, not about what the test can detect, and the two measures are answering different questions.

**What the criterion view shows.** Fixture 08: `D` is 0.61 for C1 (length), 0.22 for C2 (digit), 0.04 for C3 (uppercase) and 0.0 for C4 (no tests). The order C1 > C2 > C3 > C4 is consistent with the labelled states (proven, proven, weak, unevidenced), but C2 is labelled proven and scores only 0.22 (lower bound 0.10): one linked test pins one rule out of the many mutants of `validate_password`, which is the granularity problem again. Fixture 01 shows the symbol-granularity limit: C1 (arithmetic) has `D` 0.667 and C2 (validation) 0.389, but both are charged for every mutant of `apply_discount`, including those on the other criterion's lines. Criterion links are symbol-level (LK-02), so `D(c)` under-credits a criterion implemented by part of a function (open decision D6).

**Scope creep.** Fixture 05 has two changed symbols no criterion mentions. `round_money` is well covered (3 of 3 killed, by a test unrelated to the criteria) while the `REQUEST_TIMEOUT_SECONDS` change (30 to 300) has a surviving mutant and no test. Mutating unlinked changed symbols and reporting them is cheap and informative.

**Small-sample behaviour.** Fixture 04 produced 2 mutants and fixture 03 produced 5, so almost every number there is `n/a` or has a very wide interval (for example fixture 03 C2: `D` 0.2, Wilson lower bound 0.04). The guards (no number below 5 mutants, consumers use the lower bound) did their job; a real PR needs the sampling budget and the wider operator set to produce usable counts.

## Limitations of this run

- Local runner only; the sandbox adapter was unit-tested with fakes and never run against Docker here.
- One seed, no mutant sampling (everything fit in the budget), no survivor or baseline reruns, so flaky handling is untested on real runs.
- `d_reach` uses a line-level `settrace` plugin, not the LK-03 coverage database; only the mutant's first line counts as reached.
- Bands and thresholds are arbitrary and fixed in advance; with `>= 0.5` the labelled-strong boundary tests of fixture 01 are "weak". Change the threshold and every agreement count above changes.
- The equivalent-mutant detector fired once in fixture 01 and once in fixture 02 (both exception-message constants); there is no labelled sample, so its error rate is unknown. Genuinely equivalent mutants that no pattern catches (for example `a > b` to `a >= b` where `a - b` is 0 at `a == b`, seen in a unit-test snippet) stay in the denominator and push `d` down.
- Labels come from the fixture authors and were not independently annotated.
- The mutated module is written with `ast.unparse`; the fixture tests do not depend on formatting.
