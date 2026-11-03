# Wired mutation evidence: fixture sanity run (NOT a research result)

**Status: run on 2026-11-03** (Windows 11 dev box, dev-only local runner, trusted F-14 fixture code, `RADIUS_MUTATION_ALLOW_LOCAL=1`, `defusedxml` and `cryptography` installed). Command:

```
RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_wired_eval.py --mode both --json mutation_wired.json
```

The script runs the real Stage A and Stage B on each fixture with the flag off (OFF, static) and on (ON). Operator set: the frozen default; 50-mutant budget (never reached); seed 0; baseline twice; survivors rerun once. **Fixture sanity, not a research result:** one tiny function per fixture, 2 to 23 mutants, one patch each, no confidence claim beyond "this is what the code does on these 8 inputs".

## Result per fixture and mode

Columns: expected verdict (`verdict_v2.fixture_expectations.json`), verdict OFF and ON, mutation run (`status generated/decided/killed`), then per criterion `state S` OFF -> ON (n = decided mutants linked to the criterion, killed = of them killed by any counted test). "(static)" means the criterion was not measured and kept its static result.

| fixture | mode | expected | OFF | ON | mutation run | criteria OFF -> ON |
|---|---|---|---|---|---|---|
| 01_correct_strong_tests | auto | verified | insufficient_evidence | insufficient_evidence | measured 19/18/18 | C1 weak 0.292 -> unevidenced 0.131 (n=18, killed 15)<br>C2 proven 0.611 -> unevidenced 0.184 (n=18, killed 17) |
| 01_correct_strong_tests | gold | verified | verified | insufficient_evidence | measured 19/18/18 | C1 proven 0.734 -> weak 0.408 (n=18, killed 12)<br>C2 proven 0.604 -> unevidenced 0.173 (n=18, killed 7) |
| 02_correct_weak_tests | auto | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 7/6/4 | C1 unevidenced 0.050 -> unevidenced 0.060 (n=6, killed 4)<br>C2 unevidenced 0.014 -> unevidenced 0.017 (n=6, killed 4) |
| 02_correct_weak_tests | gold | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 7/6/4 | C1 weak 0.283 -> weak 0.335 (n=6, killed 4)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 03_incorrect_passes_weak_tests | auto | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 5/5/4 | C1 unevidenced 0.102 -> unevidenced 0.068 (n=5, killed 3)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C3 unevidenced 0.113 -> unevidenced 0.012 (n=5, killed 1) |
| 03_incorrect_passes_weak_tests | gold | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 5/5/4 | C1 weak 0.252 -> unevidenced 0.166 (n=5, killed 3)<br>C2 unevidenced 0.144 -> unevidenced 0.026 (n=5, killed 1)<br>C3 weak 0.252 -> unevidenced 0.026 (n=5, killed 1) |
| 04_test_tampering | auto | failed | failed | failed | unmeasured/too_few_decided_mutants 2/2/1 | C1 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C3 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 04_test_tampering | gold | failed | failed | failed | unmeasured/too_few_decided_mutants 2/2/1 | C1 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C3 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 05_scope_creep | auto | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 5/5/4 | C1 unevidenced 0.000 -> unevidenced 0.000 (static)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 05_scope_creep | gold | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 5/5/4 | C1 proven 0.604 -> weak 0.408 (n=5, killed 4)<br>C2 proven 0.688 -> weak 0.416 (n=5, killed 4) |
| 06_hallucinated_dependency | auto | failed | failed | failed | measured 13/13/13 | C1 proven 0.512 -> weak 0.413 (n=13, killed 11)<br>C2 proven 0.601 -> unevidenced 0.149 (n=13, killed 4) |
| 06_hallucinated_dependency | gold | failed | failed | failed | measured 13/13/13 | C1 proven 0.688 -> proven 0.598 (n=13, killed 11)<br>C2 proven 0.604 -> unevidenced 0.149 (n=13, killed 4) |
| 07_vague_intent | auto | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 6/6/5 | C1 excluded 0.000 -> excluded 0.000 (static)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 07_vague_intent | gold | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 6/6/5 | C1 excluded 0.000 -> excluded 0.000 (static)<br>C2 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 08_multi_criterion_partial_evidence | auto | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 23/23/18 | C1 weak 0.331 -> unevidenced 0.137 (n=23, killed 14)<br>C2 unevidenced 0.156 -> unevidenced 0.025 (n=23, killed 5)<br>C3 unevidenced 0.039 -> unevidenced 0.002 (n=23, killed 1)<br>C4 unevidenced 0.000 -> unevidenced 0.000 (static) |
| 08_multi_criterion_partial_evidence | gold | insufficient_evidence | insufficient_evidence | insufficient_evidence | measured 23/23/18 | C1 proven 0.604 -> weak 0.238 (n=23, killed 14)<br>C2 weak 0.432 -> unevidenced 0.070 (n=23, killed 5)<br>C3 unevidenced 0.144 -> unevidenced 0.006 (n=23, killed 1)<br>C4 unevidenced 0.000 -> unevidenced 0.000 (static) |

## Reading it (facts, not claims)

- **Producer healthy:** 14 of 16 runs are `measured`; both fixture-04 runs are `unmeasured / too_few_decided_mutants` (the changed symbol yields 2 mutants, below the minimum of 5), so ON equals OFF there by design. No run degraded to `baseline_failed_to_run` with the dependencies installed.
- **Support moves down much more often than up.** Of the measured criteria, only those of fixture 02 rose (gold C1 0.283 -> 0.335; auto C1 and C2 by 0.01 and 0.003; tests with a_static 0.25 killing 4 of 6 mutants); all others fell, several by 0.4 to 0.5 (for example 01 gold C2 0.604 -> 0.173). Two causes visible in the data: a test only kills mutants in the part of the symbol it exercises, and `d_mut = killed / N` is taken over **all** mutants of the symbol-level link (known limit D6), and the Wilson lower bound is low for N below 25.
- **Verdict changes vs static:** exactly one. **01 gold: `verified` -> `insufficient_evidence`.** The label for fixture 01 is `verified` (correct patch, strong tests), so this ON result **disagrees with the labelled expectation**; it is a loss of support caused by the symbol-level denominator, not a finding that the patch is wrong (all 18 decided mutants of that symbol are killed by some test). Every other verdict equals OFF and equals the label.
- **No separation of correct and incorrect patches is shown.** Fixture 03 (incorrect patch, weak tests) stays `insufficient_evidence` OFF and ON; fixture 01 (correct) moves to the same verdict ON. Mutation lowers both. This does not test RQ2.
- **Fixtures 06 (`failed`) and 04 (`failed`)** stay `failed`: the verdict is decided by CI / tamper rules, mutation only changes support (DEC-035 item 5).
- Survivors ("gaps") are listed per run by the script (for example 08: lines 11 to 16 of `src/validators.py`, operators CON, CRM, NEG, ROR, RET); they are printed, not summarised here.
- 05 auto and 07 are `static_only` ON although a mutation run exists: the criteria have no linked counted tests (S = 0 OFF as well), so nothing to measure.

## Defect found by this run (fixed)

On fixture 08 the first run produced `degraded: producer_timeout:assertions, truncated` and all four criteria collapsed to S = 0.000 ON, although the mutation run itself was healthy (23 decided, 18 killed). Cause: the mutation stage (about 110 s for 23 mutants on this machine) ran inside the shared 120 s Stage A budget (`CollectLimits.timeout_s`), so every producer after it (assertions, relevance) got a zero budget, timed out and set the blocking `truncated` marker. In the worker, with container runs that cost seconds each, **any** mutation-enabled analysis with more than a handful of mutants would have lost its assertion evidence. Fix: the time spent in the mutation step (which has its own `mutation_timeout_s`) is credited back to the shared budget (`apps/worker/src/radius_worker/verdict_v2/collect.py`); regression test `test_mutation_time_does_not_consume_the_shared_stage_a_budget`. The 08 rows above are from the run after the fix; the other fixtures were not affected (their ON degraded lists contained no timeouts) and were not rerun.

## Sandbox versus local runner

See `docs/security/EXECUTION_ISOLATION.md` ("Measured: sandbox adapter versus local runner"): fixture 08 gold, identical kill matrix.

## Limits that apply to any result

A bounded sample of one fault family; symbol-level links (a criterion implemented by part of a function is charged for the mutants of the rest); `d_reach` not computed; the operator set is the frozen default (the post-hoc `CALLX` is not used); the design's stage 2 (wider test set on survival) is not implemented; timings below depend on a loaded Windows machine.
