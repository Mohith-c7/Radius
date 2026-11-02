# Mutation evidence service (EV-04, EV-05, EV-09, EV-10)

**Status:** design plus a flag-gated spike (`packages/testing/src/radius_testing/mutation/`, `RADIUS_FEATURE_MUTATION`, default off, nothing wired into the worker). Date: 2026-11-03.
**Reads:** `../DESIGN.md` (6.3 `q(e)`, 7 evidence quality), `../tasks/EV-evidence-quality.md` (EV-04, EV-05, EV-09, EV-10), `VERDICT_V2_SLICE.md` (3.5 `q(e,c)`), `../preregistration/PREREGISTRATION.md` (RQ2, mutation budgets), `../../security/EXECUTION_ISOLATION.md` (F-07), `../literature/related-work.md`, `../evaluation/MUTATION_FIXTURES.md` (fixture sanity run, not a research result).

> Every number below is a hypothesis with a default, to be tuned by the evaluation plan. Cost figures are estimates until the pre-registered timing pilot (PREREGISTRATION 17.3) replaces them.

## 1. What the service is for

A passing test only counts as evidence for a criterion to the degree that it would have **failed if the code were wrong**. `a_static` guesses this from assertion shape. Mutation measures it: seed small faults into the symbols the PR changed, run the linked tests, and see which tests notice. The output is `d_mut(e, c)`, the measured detection power of evidence item `e` for criterion `c`, which replaces the static cap in `q(e,c)` when enough data exists.

Non-goals: the service never decides a verdict, never edits the user's repository, never generates tests, and never claims anything from survivors alone (Section 8).

## 2. Scope: changed symbols only (LK-01)

- **Input:** `SymbolChangeSet` from LK-01 (`radius_analysis.symbol_changes`). Mutate the `new_range` of every symbol whose `change_kind.is_behavioral` is true (`added`, `modified_body`, `modified_signature`, `renamed`, `moved`, `moved_between_files`, `decorator_or_annotation_changed`). `docstring_or_comment_only` and `formatting_only` are skipped (no behaviour change), as are `removed` symbols (nothing at HEAD).
- **Granularity:** the whole symbol range, not only the changed hunks. A changed line can break behaviour that lives in untouched lines of the same function, and the criterion link (LK-02) is at symbol level. Mutants on lines inside a changed hunk (`SymbolHunk.new_lines`) get priority when the budget forces sampling (Section 5.4).
- **Excluded always:** test files and `conftest.py` (a mutant in a test is tampering, not evidence), generated/vendored paths (LK-01 ignore globs), docstrings, f-string constants, lines marked `# pragma: no mutate`, and anything under a path that is not a Python source file (v1 is Python only; Stryker for TypeScript is EV-14).
- **Unlinked changed symbols** are still mutated (this is how scope creep becomes visible: surviving mutants in code no criterion asked for) but never feed a criterion's `d_mut`.
- **Prototype:** `generate_mutants(source, path, scope)` takes `scope` as line ranges, the shape of `LineRange`. The fixture script derives them from LK-01.

## 3. Operators (Python)

A deliberately small set. Rationale: the "sufficient operator" literature (Offutt-style selective mutation, see the survey `Papadakis2019`) says a few operator families yield almost the same adequacy ranking as the full set at a fraction of the cost; mutants of this kind correlate with real faults (`Just2014`, `Andrews2005`, both read only via the review in `related-work.md`, so the coupling claim is unverified for Python agent patches and is a validity threat, not a premise).

| id | operator | example | why it is in the set |
|---|---|---|---|
| `ROR` | relational / boundary | `<` to `<=`, `>` to `>=`, `==` to `!=`, `is` to `is not`, `in` to `not in` | off-by-one and inversion are the most common real logic faults; kills need a boundary test |
| `AOR` | arithmetic | `+` to `-`, `*` to `/`, `//` to `/`, `%` to `*`, `**` to `*` (also augmented) | wrong formula; needs an exact-value assertion |
| `BOOL` | boolean | `and` to `or` | wrong combination of conditions |
| `NEG` | negation | `not x` to `x`; `if/while/ternary` test to `not (test)` | inverted control flow |
| `CRM` | condition removal | drop one operand of `and`/`or`; `if/while` test to `False` | a clause nobody tests (the classic missing-validation case) |
| `CON` | constant | `n` to `n+1` (`0` to `1`), `True` to `False`, `s` to `"XX"+s` | magic numbers, defaults, flags |
| `RET` | return value | `return v` to `return None` | tests that never look at the result |
| `EXC` | exception removal | `raise ...` to `pass` | error paths asserted only loosely |
| `CALL` | call removal | statement `f(...)` to `pass` | side effects nobody checks |
| `ARG` | argument swap | first two positional arguments swapped | wrong argument order |

Deliberately omitted: statement deletion in general (too many trivial survivors), decorator/lambda/comprehension operators, inheritance and async operators, type-annotation mutation, and LLM-generated mutants (non-deterministic; also `Mutahunter` is AGPL-3.0 and must not be copied or linked, QS-13). Engine ports: the design allows `mutmut`/`cosmic-ray` adapters (EV-04 step 1) but their licences must be checked first (QS-13); the spike implements its own minimal engine, which is also what makes seeds and ids fully controllable.

**Determinism.** Mutants are sorted by `(path, line, col, operator, replacement, id)`. The id is `sha1(path|operator|span|description|replacement)[:12]`, independent of enumeration order and of Python hash randomisation. `mutant_hash = sha256(mutated module text)` is the cache identity.

**Observed in the fixture run** (not a general claim): `ARG` mutants such as `round(2, x)` fail with a `TypeError` under almost any test that calls the function, so they say little about assertion quality. Proposed tiers for sampling priority: tier A `ROR`, `AOR`, `BOOL`, `CRM`, `EXC`, `RET`, `NEG`; tier B `CON`, `CALL`; tier C `ARG`. The operator set used for the RQ2 predictor is frozen at pre-registration (Section 12).

**Production note on text patching.** The spike writes the mutated module with `ast.unparse`, which normalises formatting and drops comments in the mutated copy (not in the user's checkout). Acceptable for a spike; production should patch the source text by span so tracebacks keep their line numbers, and should run one **control mutant** (the unparsed but unmutated file) to detect unparse regressions: it must pass every baseline-passing test.

## 4. Execution: sandbox only

```
worker (holds DATABASE_URL, GitHub key)           never executes repo code
  |
  |  mutate in memory (AST, pure Python, no exec/import of repo code)
  v
fresh copy of the checkout (.git excluded, symlinks kept as links)  <- the mutated file is written HERE only
  |
  v  ContainerSandboxRunner (F-07): --network none, --read-only, tmpfs /tmp, --cap-drop ALL,
     no-new-privileges, nobody uid, pids/memory/cpu/ulimit caps, --pull never, fixed env allowlist,
     output watchdog, wall-clock kill. One container per mutant run; results via /results/junit.xml
```

- The spike's `SandboxMutantRunner` builds a plain `TestRunPlan` (`python -m pytest -q [-x] <test ids>`) and calls `ContainerSandboxRunner.run_collecting(plan, copy, artifacts=("junit.xml",))`. It reuses all F-07 isolation unchanged; timeouts map to `SandboxConfig.timeout_seconds` (a derived config per run). Command construction is unit-tested with fakes; it has not been exercised against Docker in this spike.
- **Test ids are validated** before they reach the command line (no leading `-`, no `..`, no absolute or drive paths), so a test id can never become a pytest option.
- **Dev-only backend.** `SubprocessLocalRunner` runs pytest as a child process of the caller. It is refused unless `RADIUS_MUTATION_ALLOW_LOCAL=1`, works on a temp copy, uses a minimal environment, and is documented as unsafe for untrusted code. Production code must not construct it.
- **Image.** The sandbox image must already contain the repository's test dependencies (no network). Its digest (`image@sha256:...`) is part of every cache key.
- **Throughput options.** (a) One container per mutant (the spike): simplest, strongest isolation, about one container start per mutant. (b) **Mutant schemata**: instrument all mutants of a file into one module selected by a variable, run N mutants per container, with the selector delivered through a file under `/results` rather than an environment variable the code under test could read. Faster by roughly the container-start share (Section 7), but a larger trusted surface; keep as an optimisation after (a) is measured.
- **Parallelism.** `P` containers at `--cpus 1.0`, with `P` bounded by worker capacity and the PR's compute budget; results are merged in canonical mutant order so output does not depend on `P`.

## 5. Test selection, early exit, caching, budgets

### 5.1 Which tests run per mutant

1. **Baseline** (once per PR and test set, repeated `baseline_runs` times, default 2 in production): run the selected tests on the unmutated HEAD. Tests that fail are excluded (a failing test cannot be attributed), and tests whose outcome changes between runs are flagged flaky and excluded (F-11).
2. **Stage 1: linked tests, full matrix.** Run all baseline-passing tests linked to the mutated symbol (LK-03 `symbol_test_link` above a confidence floor, plus VS-04 relevance), without early exit. Per-test attribution (`d_mut` per test) needs to know every test that fails, so `-x` is not used here. Linked sets are small by construction.
3. **Stage 2: escalate on survival or empty link set.** If the mutant survived stage 1, or the symbol has no linked tests, run the wider selected set with `-x` (early exit on the first killing test) ordered by prior kill history. A stage 2 kill sets `killed_outside_linked` (the mutant is detected, but not by evidence tied to the criterion); it does not credit any linked test.

### 5.2 Per-mutant timeout

`timeout = clamp(3 x median baseline duration of the run set + startup, 5 s, 120 s)`; an infinite-loop mutant is stopped by the sandbox wall-clock kill. A timeout is recorded as `timeout` and **excluded from `d_mut` denominators** (it cannot be attributed to a test). The suite-level "detected by CI" statistic may count it separately. Rerun a timeout once before recording it.

### 5.3 Result caching (EV-09)

Prototype key: `sha256(mutant_hash | sorted(test ids) | image digest)`. **This is incomplete for production**, because a test body or an imported helper can change without its id changing. Production key:

```
H( mutant_hash,                    # sha256 of the mutated module
   H(contents of the selected test files and conftests),
   H(contents of the non-mutated source files in the test dependency closure),
   image_digest, python/pytest versions, runner args, algo_version )
```

Cached values are final statuses only (`killed` with `killed_by`, `survived`); `timeout`, `error`, `flaky` are never cached. Namespaces are per organisation and repository (no cross-tenant sharing: a hit would reveal that another tenant ran the same code). Acceptance (EV-09): a second run on an unchanged symbol is a measured full hit; any test or dependency change invalidates; the cached result equals the full result on the fixtures. The spike's `run_mutants(cache=...)` and its test cover the hit path and the digest/test-set miss path; the content hashes are the follow-up.

### 5.4 Budgets and graceful degradation

| budget | default | source |
|---|---|---|
| max mutants per PR | 50 | PREREGISTRATION 17.3 rule (a), floor 20 |
| wall clock for the mutation stage | 900 s | H6b p95 target; pre-registration also caps 20 min per RQ2 patch |
| per-mutant timeout | Section 5.2 | |
| compute cost cap | per-org policy, in vCPU-seconds | cost model, Section 7 |

Degradation ladder, each step recorded in `mutation_run.status` and shown in the UI ("mutation: sampled 50 of 212"):

1. Full set within budget.
2. **Seeded stratified sample** (`sample_mutants`): rank = `sha256(seed:id)`, round-robin across symbols so a large function cannot starve small ones, tier A first, changed-hunk lines first; the seed is stored with the run. Same seed, same mutants, on every Python version (no `random`).
3. Tier A operators and changed hunks only.
4. Linked tests only (skip stage 2).
5. Skip: `d_mut = None` everywhere and `q` falls back to the static cap. A verdict is never blocked by an unfinished mutation job unless the org policy says so; partial results are published first ("mutation pending", EV-04 step 6). Mutants not started when the wall clock expires are listed as `skipped_for_budget`.

## 6. Equivalent mutants (EV-10)

A surviving mutant counts against a test only if it changes behaviour. Equivalence is undecidable; the detector (`detect_equivalent`) marks `equivalent_suspect` using cheap explainable checks, in order:

1. identical AST after normalisation (`ast.dump`),
2. identical bytecode (recursive code-object comparison; catches constant folding),
3. patterns: neutral literal operand (`x + 0`, `x * 1`), identical operands (`a and a`), removal of `print`/logging calls, mutated string constants that are exception messages. Textual no-ops (for example swapping identical arguments) never leave the generator.

Policy: suspects are **excluded from the denominator by default** (`exclude_suspects=True`), **always listed** (never silently dropped; `KillMatrix.excluded()` returns them by reason), and the policy flag is auditable. Acceptance for EV-10 (not done in the spike): label 100 or more survivors from the pilot manually with two annotators, report the detector's precision and recall, and publish the rate at which suspects are in fact killable. The fixture run shows the other direction too: `a > b` to `a >= b` survives every test of fixture-like code where the two behave identically, and no pattern catches it. Such mutants stay in the denominator, which makes `d_mut` conservative (it can only lower a test's score).

## 7. Cost model (estimates, to be replaced by the pilot)

Per run: `t_run = t_start + t_tests`, where `t_start` is the container start plus interpreter and pytest import, and `t_tests` the linked tests. Per PR: `T = (1 + b + N x (1 + r_s)) x t_run / P`, with `b` baseline repeats (2), `N` sampled mutants, `r_s` the share of survivors that are rerun (about 0.3 assumed), `P` parallel containers.

| scenario | N | t_run (assumed) | P | wall | vCPU-seconds |
|---|---|---|---|---|---|
| small PR, fast unit tests | 20 | 3 s | 2 | about 60 s | about 140 |
| typical PR | 50 | 6 s | 4 | about 130 s | about 520 |
| large PR, slow tests | 50 (capped from 400) | 20 s | 4 | about 420 s | about 1,700 |

At an assumed 0.04 USD per vCPU-hour the typical PR is about 0.006 USD; at the pre-registered N = 5,000 RQ2 patches, 50 mutants and 6 s runs, the compute is about 2,000 vCPU-hours of mutation runs before the cap rules (a, c) bite. **Measured in the spike** (Windows dev box, local runner, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`): one pytest invocation on a three-line fixture costs about 2.7 s, of which an empty `python -c pass` is 1.1 s; so startup dominates and the schemata optimisation (Section 4) is the first thing to measure on Linux.

## 8. From kill matrix to `d_mut`

### 8.1 Definitions

Over the **decided, non-equivalent** mutants of the symbols linked to criterion `c` (status `killed` or `survived`; `timeout`, `error`, `flaky`, and `equivalent_suspect` are excluded and reported):

```
N          = |such mutants|
killed(t)  = |{m : t in killed_by(m)}|           (credit "multi", default: every killing test gets a full kill)
           = sum 1/|killed_by(m)|                  (credit "split")
d_mut(t)   = killed(t) / N          if N >= n_min (default 5), else None   (EV-05 literal)
d_reach(t) = killed(t) / N_t        N_t = such mutants whose line t executes; None if N_t < 3
lcb, ucb   = Wilson score interval of (killed, N)   (z = 1.96)
D(c)       = |mutants killed by any test linked to c| / N                   (union; no double counting)
```

`d_mut` as literally written in EV-05 (killed by `e` over all mutants of the linked symbols) systematically scores narrow tests low: a test of one error path cannot kill the arithmetic mutants. `d_reach` is the conditional version (given that `e` ran the mutated line, did it notice?), which is closer to what "would have failed if the code were wrong" means. Both are computed; the choice is open decision D2. Reachability in production should come from the LK-03 dynamic coverage database (`linking/coveragedb.py`, per-test contexts) instead of the spike's `sys.settrace` plugin.

Sample guards: no number is emitted below `n_min`; the consumer uses `lcb`, never the point estimate; a criterion whose symbols have zero mutants (comments only, or all suspects) gets `d = None` and the static fallback (EV-05 step 3).

### 8.2 Plugging into `q(e, c)` without changing the frozen contract

Today (`packages/evidence/src/radius_evidence/domain/quality.py`): `d_eff = min(cap_static, a_static)` and `EvidenceQuality.d_mut: float | None = None`. The change is confined to how `d_eff` is chosen:

```
d_eff = d_lcb(e, c)                    if d_mut(e, c) is not None            # measured: replaces the cap
      = min(cap_static, a_static)       otherwise                             # unmeasured: static cap, as in the alpha
q     = d_eff * i * f * flaky_f * (1 - tamper_p)                              # unchanged
```

- `d_mut` (the point estimate) is stored in the existing field; `d_eff` uses its Wilson lower bound; new reason codes `d_from_mutation` and `mutation_insufficient_sample`; `algo_version` is bumped. No field is added or removed, the combiner stays monotone in `d`, and an old consumer that ignores `d_mut` still reads a valid `d_eff`. (Whether `verdict_v2.schema.json` already exposes `d_mut` should be confirmed at EV-08; adding an optional property is compatible.)
- A measured `d_eff` may exceed `cap_static`; that is the point (the cap exists because the static proxy is unverified). A guard is needed for tests with `a_static = 0` that "kill" only through uncaught exceptions: see open decision D4.
- **Criterion level.** `S(c) = 1 - prod(1 - lambda q l)` assumes independent evidence, but two tests that kill the same mutants are one piece of evidence. With a kill matrix the union `D(c)` is available; recommended for Beta: `S(c) <- min(S(c), D_lcb(c))` as a ceiling, evaluated as an ablation (D5) before it becomes default.
- **Known limit.** Links are symbol-level, so a criterion implemented by part of a function is charged for mutants in the rest of it. The fixture run shows this on fixture 01 (C1 is about the discount arithmetic, C2 about validation, one function): see `MUTATION_FIXTURES.md`. Line-level criterion links, or reach-restricted unions, are the mitigation (D6).

## 9. Flaky handling (F-11, EV-10)

- Baseline run repeated; a test that fails or changes outcome at baseline is excluded and listed.
- A survivor is rerun (`survivor_reruns`, default 1); if the rerun is killed the mutant is `flaky` (excluded, reported). Reruns use fresh containers and never run after a sandbox error (an error is not evidence of flakiness; same rule as `ContainerSandboxRunner`'s failure reruns).
- A kill whose only killer has a high F-11 flakiness score is marked `killed_low_confidence` and does not credit that test fully; `flaky_f` (the separate factor in `q`) still applies to the test itself.
- Timeouts rerun once. Everything above is budgeted: reruns count against the wall clock.

## 10. Safety

Mutants are generated code, run against untrusted repositories.

| threat | control |
|---|---|
| mutant or PR test code reads secrets / calls out | F-07 sandbox: no network, fixed env allowlist, nothing forwarded from the worker |
| fork bomb, memory or disk exhaustion, infinite loop, output flood | pids/memory/cpu/fsize ulimits, tmpfs cap, wall-clock kill, output watchdog (all F-07); per-mutant timeout |
| mutation applied to the user's checkout | mutated file is written only into a throw-away copy (`_write_mutant` rejects paths outside it); a test asserts the checkout is byte-identical afterwards |
| test id turned into a pytest option or path escape | `validate_test_ids` |
| mutating a test or harness file to force "kills" | tests and `conftest.py` are out of scope by construction |
| **result forgery**: code running in the container writes `/results/junit.xml` itself | the report is evidence from untrusted code, with the same trust as any CI result; cross-check with the process exit status; never use mutation output as the sole basis of a pass; tamper rules apply |
| **mutation-aware tests** that fail whenever the source file changed (hash or `inspect.getsource` of the code under test) and so inflate `d_mut` | candidate tamper rule: a test that reads the source of the symbol it covers is down-weighted (`i`) or nullified; also visible as "killed by every mutant including no-op ones": run the control mutant |
| nondeterminism | fixed seed, canonical order, `PYTHONHASHSEED=0`, fixed test order, `-p no:cacheprovider`, no pytest plugin autoload |
| generator parses with the worker's Python grammar, not the repo's | a `SyntaxError` yields no mutants and the degradation ladder falls back to static; record the worker's Python version in `algo_version` |

The generator itself never imports or executes repository code (pure `ast`). Nothing in the spike is wired into the worker; the library is inert unless a caller constructs a runner.

## 11. Data model and API (unchanged from DESIGN 5; for reference)

`mutation_run(id, analysis_id, engine, scope, budget, seed, status, ...)` and `mutant(run_id, symbol_id, operator, location, status in killed|survived|timeout|equivalent_suspect|flaky|error|skipped_for_budget, killed_by_test_id[])`. `killed_by` is a set, not the single `killed_by_test_id` of the EV-04 sketch, because per-test attribution needs the full matrix: one row per (mutant, killing test) in a child table, or a JSON array. Migration number as in EV-04 (0013).

## 12. Circularity and the RQ2 label (the review's concern)

**The risk.** RQ2's primary label `L_ABS` marks a test-passing agent patch as incorrect when it fails a test suite strengthened by mutation-driven adversarial tests (SWE-ABS, which needs the gold patch). Our predictor `d_mut` is also a mutation score. If both use the same mutant families, sites and tests, a correlation could mean "two mutation procedures agree", not "d_mut predicts incorrectness". Four channels: shared operator families; shared mutation sites (both mutate the lines the patch touches); shared test artefacts (strengthened tests leaking into the feature run); and a construct overlap (both measure "tests catch behaviour changes"). PREREGISTRATION already lists this as a construct threat (about line 406); this section turns it into a protocol.

**Recommended protocol (to be frozen with the pre-registration):**

1. **Gold-free, label-free feature inputs.** The feature job gets only: the agent patch, the repository at the agent HEAD, and the *original* tests, i.e. exactly what exists at PR time. It never sees the gold patch, SWE-ABS's strengthened tests or mutants, or any `L_*` artefact. Enforced by an input manifest hashed into the feature record and a CI check that rejects any path from the label store.
2. **Different mutation machinery on the two sides.** Features use this design's engine and operator set `O_pred` (frozen: Section 3, with seed and budget). Labels come from SWE-ABS's released artefacts as they are, plus the human audit label `L_audit` (a stratified sample, at least two annotators) and `L_cons` where available. Radius's own mutation engine is never used to produce or extend any label.
3. **Measure the overlap instead of assuming it.** For sampled instances, compare our mutants with the label-side mutants at site level (same file and line, same operator family). Report the overlap rate. If SWE-ABS's mutants are not released for an instance, report that and use only the next two controls.
4. **Held-out mutants as an internal control.** Split `O_pred` mutants deterministically by id hash into a feature half and a held-out half. The held-out half is never a feature; it is used only to check that `d_mut` computed on the feature half predicts kills on the held-out half (a property of the measurement, independent of the label).
5. **Stratified headline.** Report AUROC of `d_mut` overall and in two strata: instances where our mutation sites overlap the label-side sites and instances where they do not. If the effect exists only in the overlap stratum, the headline claim is the non-overlap stratum (or the paper says the effect is label-coupled).
6. **Negative controls.** (a) `d_mut` computed on random mutants outside the changed symbols; (b) `d_mut` with test-to-symbol links permuted within the repository; (c) the B6 baseline (whole-file mutation score without intent linking) and B1 coverage. A predictor that "works" under (a) or (b) is measuring something other than evidence strength.
7. **Report dependence.** State which label sources share methodology with the feature; the robustness rule in PREREGISTRATION 2.6 (sign agreement on `L_cons` and `L_audit`) stays.

None of this removes the construct overlap; it bounds it and makes it reportable.

## 13. Mapping to tasks and what the spike does not cover

| piece | task | spike |
|---|---|---|
| generator, ids, scope, pragma | EV-04 | done (`operators.py`) |
| sampling, budget, cache key | EV-04, EV-09 | `budget.py`; key lacks content hashes (5.3) |
| runners | EV-04, F-07 | `runner.py`; sandbox backend unit-tested with fakes only |
| kill matrix, `d_mut`, Wilson, criterion aggregate | EV-05 | `matrix.py` |
| equivalence, flaky | EV-10, F-11 | `equivalence.py`; flaky via baseline and survivor rerun; no labelled FP-rate yet |
| persistence, async job, UI, policy | EV-04, EV-11 | not started |
| `q` integration | EV-08 follow-up | design only (8.2) |
| TypeScript | EV-14 | not started |

## 14. Open decisions (owner input needed)

- **D1. Engine.** Own minimal engine (this spike) versus an adapter over `mutmut`/`cosmic-ray` (licences to be checked, QS-13). Recommendation: own engine for the research claim (controllable seeds and ids), adapter port kept open.
- **D2. Denominator.** EV-05 literal `d_mut` (all mutants of the linked symbols) versus conditional `d_reach`. The fixture run (MUTATION_FIXTURES.md) is too small to settle it; decide with the pilot. Band thresholds in the fixture script (0.5 and 0.20) are arbitrary and fixed a priori, not calibrated.
- **D3. Timeout policy.** Exclude from denominators (this design) versus count as detected, as classic mutation score does.
- **D4. Kill kind.** Credit kills by assertion failure only, or also by uncaught exceptions? Without a split, an assertion-free test can earn `d_mut` by crashing. JUnit distinguishes `failure` from `error`; the spike merges them.
- **D5. Criterion ceiling.** Adopt `S(c) <= D_lcb(c)` (or replace noisy-OR with union detection) when mutation data exists? Pre-registered ablation.
- **D6. Link granularity.** Accept symbol-level criterion links for `d_mut`, or require line-level links (new task)?
- **D7. Schemata.** Authorise the multi-mutants-per-container optimisation after measurement.
- **D8. Blocking policy.** May an org require mutation to finish before a verdict is published?
- **D9. Mutation-aware test rule.** Add the source-reading rule to the tamper catalog (EV-02 follow-up).
- **D10. Cache sharing** across repositories of one organisation (default: per repository).
