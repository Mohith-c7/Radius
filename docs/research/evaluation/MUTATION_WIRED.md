# Wired mutation evidence: fixture sanity run (NOT a research result)

**Status: not run yet.** The ON-versus-OFF table for the 8 F-14 fixtures could not be produced in the environment where the wiring was built: the dev-only local runner parses pytest's JUnit report with `defusedxml`, which was not installed there, so every baseline run was reported as "no cases" and the producer degraded, as designed, to `unmeasured / baseline_failed_to_run` (the verdicts and supports then equal the static ones, which was checked on fixture 08: the same four states and supports, OFF and ON). No numbers are claimed here.

How to produce the table (trusted F-14 fixture code only; the local runner executes it on the host):

```
RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_wired_eval.py --mode both --json mutation_wired.json
```

The script runs the real Stage A and Stage B on each fixture with the flag off and on, and prints per criterion the state and support S(c) OFF versus ON, the measured basis, the number of mutants, per-test `a_static -> d_eff` and the survivors ("gaps"). Disagreements with the static result and with `verdict_v2.fixture_expectations.json` are printed, not hidden. Paste the output into this file, label it fixture sanity, and list every disagreement.

What the unit tests already establish (hand-computed on fixture 08 with a synthetic kill matrix, `apps/worker/tests/test_verdict_v2_mutation.py`): a strong static pair that kills 8 and 4 of 10 mutants drops C1 from S 0.604 (supported) to 0.408 (weak); a test that kills 10 of 10 raises C2 from 0.432 to 0.520; a test that kills nothing gets d_eff 0.

Limits that apply to any result: a bounded sample of one fault family; symbol-level links (a criterion implemented by part of a function is charged for the mutants of the rest); `d_reach` not computed; the operator set is the frozen default (the post-hoc `CALLX` is not used).
