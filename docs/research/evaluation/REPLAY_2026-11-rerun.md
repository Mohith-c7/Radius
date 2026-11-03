# Verdict v2 replay re-run on current code (2026-11-03)

**Status: exploratory, descriptive, NOT a pre-registered evaluation and NOT a research result.** Same label as [REPLAY_2026-11.md](REPLAY_2026-11.md): outside the pre-registered RQs (`docs/research/preregistration/PREREGISTRATION.md`: exploratory runs carry no inferential claim). Nothing here may be quoted as an accuracy, recall or false-positive rate. Every figure comes from the run output saved in [REPLAY_2026-11-rerun.results.json](REPLAY_2026-11-rerun.results.json).

The third alignment review (`docs/research/ALIGNMENT_LOG.md`, entry 2026-11-03 third, item 8) asked for this: the old report's headline tables described the pipeline before the later fixes and were never recomputed. This file supplies the corrected tables. It does not rewrite the old report, whose method, case studies and findings stay as they were (its banner now points here).

- **Code state:** `origin/develop` at `45a9bcf`. One fix was made during the re-run (`e1c140f`, T004, section 7). It is NOT in the two first passes. It was in the working tree for the part of the second pass that includes PR #109 (stated where it matters).
- **PRs:** the same 29 as the old results JSON, pinned by number (3 9 22 28 40 45 50 51 53 80 82 84 86 87 90 91 94 95 100 101 102 103 104 105 106 107 108 109 110). The listing now holds 103 merged PRs; a fresh stratified selection would differ, so the pinned set is the comparable one.
- **Two intent modes:** `sections` (shipped default; `--intent-mode deterministic` in the script) and `summary` (opt-in, DEC-032). The `llm` mode was not run (no key, no network). The old `bullets` sensitivity mode was not repeated.
- **Command:** `scripts/verdict_v2_replay.py --numbers <29> --intent-mode {deterministic|summary} --cache-dir <outside the repo>`; per-PR child process with the script's default 300 s hard timeout (old run: 400 s), one PR at a time, GitHub access by `gh api -X GET` only (nothing was written to GitHub).

## 1. Method and honest limits

What ran per PR: metadata by read-only `gh api`; base and head commits resolved from git; head `.py` files extracted with `git archive`; the production source sanitiser, the extractor of the chosen mode and the rule-based testability rater on the PR title and body; Stage A (symbol changes, tamper rules, links, assertions, relevance, policy at base); Stage B and the verdict rules. No LLM.

1. **One repository, same team, same author.** 28 of 29 PRs were written with an AI assistant (`agent_signal` fired on 28 of 29 in both modes); the repository is also the system under test. Nothing generalises.
2. **Static evidence only; CI results assumed green (counterfactual).** No per-case CI results exist for historical PRs, so every linked or changed test is assumed to have passed. Verdicts are a ceiling on static support, never a statement that tests passed. As shipped (no CI results) the verdict would be R2p for the PRs not decided earlier by R1c: 27 of 29 in `sections`, 26 of 29 in `summary`.
3. **Criteria stay `proposed`.** In `summary` mode each criterion carries `unconfirmed_inferred_intent` by design (low weight, never confirmed).
4. **No ground truth.** "Wrong", "overstated" and "fixed" below are one reviewer's reading of the diff, not labels.
5. **Non-determinism under load is still present** and is the largest threat to reading the tables (section 5): the same PR on the same code gave `failed` in one run and `insufficient_evidence` in another. A Docker dev stack and other processes ran on the machine throughout (the old run was loaded too, differently), so runtimes are not comparable with the old report.
6. Selection, survivorship and data hygiene as in the old report: this repository's own public PR text only; author logins and local paths were removed from the saved JSON; no secrets.

## 2. Corrected aggregate tables (first pass, 29 PRs per mode)

| Metric | `sections` (shipped) | `summary` (opt-in) |
|---|---|---|
| PRs run / ok / errors / timeouts | 29 / 29 / 0 / 0 | 29 / 29 / 0 / 0 |
| Verdicts | insufficient_evidence 27, failed 2, verified 0 | insufficient_evidence 26, failed 3, verified 0 |
| Deciding rule | R2a 16, R2e 11, R1c 2 | R2e 10, R2a 9, R2b 7, R1c 3 |
| R2e reasons | `no_intent_criteria` 9, `not_applicable` 2 | `no_intent_criteria` 8, `not_applicable` 2 |
| Criteria per PR (median / mean / max; total) | 0 / 0.00 / 0; 0 | 0 / 0.59 / 4; 17 |
| PRs with no extractable intent | **29 of 29 (1.00)** | **18 of 29 (0.62)** |
| Criterion states (all `proposed`) | none | unevidenced 11, weak 3, excluded 3, proven 0, contradicted 0 |
| Testability of the 17 criteria | - | behavioral 7, structural 4, non-functional 3, subjective/vague 2, untestable external 1 |
| Intent coverage q25 / q50 / q75 | 0.00 / 0.00 / 1.00 | 0.00 / 0.60 / 1.00 |
| Producer failures (`producer_failed:*`) | 0 | 0 |
| Runs with a degraded marker (not counting the by-design `unconfirmed_inferred_intent`) | 7 of 29 | 7 of 29 |
| Markers | `truncated` 6 (#3, #28, #100, #103, #107, #109), `unsupported_language:typescript` 4, `:javascript` 3, `producer_timeout:assertions` 2 (#100, #109), `producer_timeout:symbol_test_links` 1 (#100) | `truncated` 4 (#9, #22, #28, #100), `unsupported_language:typescript` 4, `:javascript` 3, `producer_timeout:criterion_symbol_links` 1 (#28) |
| Runtime per PR, median / p95 / max (s) | 48.75 / 134.17 / 155.33 | 34.36 / 113.06 / 123.27 |
| Peak RSS per child, median / max (MB) | 149 / 367 | 149 / 374 |
| PRs with tamper findings (findings) | 8 (34) | 11 (37) |
| Tamper findings by severity | high 2, medium 8, low 24 | high 3, medium 9, low 25 |
| Tamper by rule and severity | T016 low 11, T013 low 10, T009 medium 3, T002 medium 2, T011 medium 2, T014 low 2, T010 high 1, T012 medium 1, T017 high 1, T017 low 1 | T013 low 17, T009 medium 5, T016 low 4, T014 low 3, T002 medium 2, T011 medium 2, T001 high 1, T004 high 1, T010 high 1, T017 low 1 |
| PRs decided `failed` | #22 (T017 `collection_hook`), #87 (T010 `continue_on_error`) | #87 (T010), #100 (T001 `test_deleted`), #109 (T004 `conjunct_dropped`) |

Rule glossary (`docs/verdict-v2.md`): R1c = an unwaived tamper finding at severity high or above; R2a = no behavioral, testable criterion while behavioral code changed; R2b = unproven intent mass above 0.20; R2e (DEC-031) = no in-scope criterion and no behavioral change.

Reading notes.

- The two passes differ in tamper counts for reasons unrelated to the intent mode (tamper does not read intent). Six `sections` runs and four `summary` runs were `truncated`, at different PRs, and a truncated run drops findings (section 5). So "PRs decided failed" depends on which runs happened to finish; it is not a stable property of the PRs.
- `summary` mode produced a criterion on 11 PRs. None is `proven`, and none can be, because there are no CI per-case results.
- `verified` appears nowhere: with no criteria R2e gives `insufficient_evidence`.

### Per-PR table

"old" is the deterministic run in the old report. Tamper n is the number of findings in the first pass of each mode; markers are from the first pass (`lang:` = `unsupported_language:`, `timeout:` = `producer_timeout:`).

| PR | type | files | old (det.) | sections now | summary now | criteria (summary) | tamper n (sections / summary) | degraded markers (sections / summary) |
|---|---|---:|---|---|---|---:|---|---|
| #3 | other | 27 | insuff. R2a | insuff. R2a | insuff. R2a | 0 | 0 / 0 | lang:typescript,truncated / lang:typescript |
| #9 | other | 49 | insuff. R2a | insuff. R2a | insuff. R2a | 0 | 3 / 0 | - / truncated |
| #22 | other | 98 | failed R1c | failed R1c | insuff. R2a | 0 | 9 / 0 | - / truncated |
| #28 | other | 32 | insuff. R2a | insuff. R2a | insuff. R2b | 1 | 0 / 5 | truncated / timeout:criterion_symbol_links,truncated |
| #40 | fix | 11 | failed R1c | insuff. R2a | insuff. R2b | 4 | 1 / 1 | - / - |
| #45 | ci | 20 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #50 | docs | 20 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #51 | ci | 7 | insuff. R2a | insuff. R2a | insuff. R2a | 1 | 0 / 0 | - / - |
| #53 | docs | 7 | insuff. R2a | insuff. R2a | insuff. R2a | 0 | 0 / 0 | - / - |
| #80 | ci | 5 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #82 | fix | 7 | verified R4 | insuff. R2e | insuff. R2b | 2 | 0 / 0 | - / - |
| #84 | fix | 3 | insuff. R2a | insuff. R2a | insuff. R2b | 1 | 0 / 0 | - / - |
| #86 | ci | 3 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #87 | fix | 9 | failed R1c | failed R1c | failed R1c | 1 | 1 / 1 | - / - |
| #90 | docs | 1 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #91 | feat | 22 | failed R1c | insuff. R2a | insuff. R2a | 1 | 4 / 4 | lang:javascript,lang:typescript / lang:javascript,lang:typescript |
| #94 | ci | 1 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #95 | docs | 7 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #100 | feat | 120 | insuff. R2a | insuff. R2a | failed R1c | 0 | 0 / 1 | lang:javascript,lang:typescript,truncated,timeout:symbol_test_links,timeout:assertions / lang:javascript,lang:typescript,truncated |
| #101 | feat | 23 | failed R1c | insuff. R2a | insuff. R2a | 0 | 7 / 7 | - / - |
| #102 | feat | 20 | insuff. R2a | insuff. R2a | insuff. R2b | 1 | 2 / 2 | - / - |
| #103 | docs | 31 | failed R1c | insuff. R2a | insuff. R2b | 1 | 0 / 1 | truncated / - |
| #104 | docs | 1 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #105 | feat | 7 | insuff. R2a | insuff. R2a | insuff. R2a | 1 | 7 / 7 | - / - |
| #106 | other | 1 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #107 | feat | 53 | insuff. R2a | insuff. R2a | insuff. R2a | 0 | 0 / 5 | truncated / - |
| #108 | ci | 2 | verified R4 | insuff. R2e | insuff. R2e | 0 | 0 / 0 | - / - |
| #109 | fix | 61 | failed R1c | insuff. R2a | failed R1c | 0 | 0 / 3 | lang:javascript,lang:typescript,truncated,timeout:assertions / lang:javascript,lang:typescript |
| #110 | fix | 23 | insuff. R2a | insuff. R2a | insuff. R2b | 3 | 0 / 0 | - / - |

## 3. Before / after against the old report

| Item | Old report (deterministic) | Now, `sections` | What changed it |
|---|---|---|---|
| Verdicts | verified 11, insufficient 11, failed 7 | verified 0, insufficient 27, failed 2 | rows below |
| The 11 old `verified` PRs (#45 #50 #80 #82 #86 #90 #94 #95 #104 #106 #108) | R4 | the same 11 PRs are R2e (9 `no_intent_criteria`, 2 `not_applicable`) | R2e / DEC-031; the set is identical PR for PR |
| `failed` PRs | #22 #40 #87 #91 #101 #103 #109 | #22 #87 | #40: T001 rename rule. #91, #101: T002 split (high to medium). #103: T015 env-var-name fix. #109: not reproduced in this `sections` run, which was truncated (it did appear in `summary`, see case 8) |
| Criteria / no extractable intent | 0 criteria, 29 of 29 | 0 criteria, 29 of 29 | unchanged: default-mode recall on this repo's PRs is still zero (old F1) |
| `summary` mode | did not exist | 17 criteria on 11 of 29 PRs, 0 proven | DEC-032 |
| Tamper findings (PRs) | 72 (12); T013 low 42, T016 low 11 | 34 (8); T013 10, T016 11 | T013 is now one finding per file and kind. Not a like-for-like drop: 6 `sections` runs were truncated. `summary` shows T013 17 |
| High-severity tamper findings | 7 (T002 x2, T001, T004, T010, T015, T017) | 2 (T010, T017) | T001/T002/T015 rule changes; T004 not seen because the run was truncated |
| Runs with a degraded marker | markers: typescript 4, javascript 3, truncated 1 (the old text says 4 of 29 degraded) | 7 of 29 (truncated 6) | load, not code: the old run was truncated once, this one six times |
| Runtime median / p95 / max | 20.1 / 67.8 / 103.1 s | 48.75 / 134.17 / 155.33 s | machine load; not comparable |

Fix by fix, on the real PRs. R2e / DEC-031 removed every `verified` (11 to 0). The T001 rename rule removed #40's finding (a low T017 conftest note remains). The T002 split turned #91 and #101 from high to medium (`runtime_skip_conditional`, `runtime_skip_new`). T015 removed #103's finding. T013 summarising collapsed individual `# noqa` lines into per-file findings. This re-run shows no effect from anything touching extraction recall (F1), links (F-L1), languages (F-L2), budgets (F-P1), fixture exclusions (F-T4) or threshold relaxation (F-T5); those remain open (section 6).

## 4. Case studies (hand-read; one reviewer's judgement, not labels)

All seven PRs the old report called wrong or overstated are covered: #40, #91, #101, #103, #87, #22, #109. Item 7 (#100) is a new case.

**1. #40 fix: refresh uv.lock, make settings/tests independent of a local .env (old: T001 `test_deleted` high, `failed`). Now: fixed.** `sections`: `insufficient_evidence` by R2a with one low T017 (`conftest_changed_with_source`). `summary`: 4 criteria (3 unevidenced including the title, 1 weak: "Root `conftest.py` clears `env_file`..."), R2b, same low T017. The renamed test is no longer reported as deleted in either mode.

**2. #91 feat(api): HTTP hardening (old: T002 `runtime_skip` high, `failed`). Now: no longer `failed`; the finding is still overstated.** `insufficient_evidence` R2a in both modes; findings T002 `runtime_skip_conditional` medium, T009 medium, T011 medium x2. Source read: `if not obs_metrics.metrics_enabled(): pytest.skip("prometheus_client not installed")` inside a new test. That is an optional-dependency guard, but the guard regex (`_ENV_GUARD`, `disabling.py:177-182`) does not recognise `metrics_enabled()`, so it is `conditional` (medium) rather than `guarded` (low). It no longer decides the verdict.

**3. #101 feat(api,docs): OpenAPI 3.1 contract (old: T002 `runtime_skip` high, `failed`). Now: no longer `failed`; label still wrong.** `insufficient_evidence` R2a; T002 `runtime_skip_new` medium plus 6 low. Source read: the skip sits in the `else:` of a `for ref in (...)` loop that looks for a base spec in git, which is conditional (nothing found). `_guard_of` (`disabling.py:189-212`) only considers `if` and `except` ancestors, so it reads as "unconditional, in a new test". Severity is capped at medium, so the effect is small.

**4. #103 docs: align docs with code (old: T015 `hardcoded_secret` high on an env-var name, `failed`). Now: fixed.** `sections`: R2a with 0 findings, but that run was `truncated`, so on its own it proves little. The `summary` pass and the second pass (neither truncated) show 1 low finding and no T015. `summary`: 1 criterion, unevidenced, R2b.

**5. #87 fix(docker): non-root, digest-pinned images (old: T010 `continue_on_error` high, `failed`). Now: unchanged, still overstated.** `failed` R1c in both modes; the only tamper finding is `continue-on-error: true` in `.github/workflows/container-scan.yml`. I read it as an advisory scan setting that a reviewer can accept in seconds; `needs_review` would fit and `failed` overclaims. The T010 severity question is still open.

**6. #22 test(bench): add 8 golden intent-to-evidence fixtures (old: T017 `collection_hook` high, `failed`). Now: unchanged in `sections`; flips with load.** `sections`: `failed` R1c on T017 high (`collect_ignore` in `benchmarks/fixtures/intent/conftest.py`), T012 medium for the deliberately hallucinated dependency, and 7 low. `summary` and both second-pass runs were `truncated` with no T017, giving `insufficient_evidence`. Same open issue as before (fixtures are intentionally broken code, F-T4), and the verdict depends on whether the run finished.

**7. #100 feat: Verdict v2 alpha (120 files; old: `insufficient_evidence`). Now: newly wrong in some runs, and unstable.** `sections`: R2a, `truncated` plus two producer timeouts, 0 findings. `summary`: `failed` R1c on T001 `test_deleted` high. Source read: `test_runner_does_not_reference_verdict_v2_yet` was renamed and rewritten into `test_runner_references_verdict_v2_only_through_the_publish_and_outbox_hooks` (3 lines to 12) because this PR wired the runner. The rename rule needs 0.6 body similarity (`RENAME_SIMILARITY`, `disabling.py:20`), so a rename with a rewritten body is still a deletion (a documented limit). The second `sections` pass gave 16 findings including 5 high T005 (determinism checks such as `row() == row()`) and `failed`; the second `summary` pass gave 0 findings and R2a. Four runs, two verdicts.

**8. #109 fix: (old: T004 `conjunct_dropped` high, "plausible, not verified"). Now: a false positive, found and fixed here.** `sections`: R2a, `truncated`, no finding. `summary`: `failed` R1c on T004. Source read: `assert run["title"].startswith("Radius v2: ") and "criteria proven" in run["title"]` became three separate asserts. Assertions are paired by position, so the first (one clause) looked like the two-clause original losing a clause. Fixed in `e1c140f` (section 7). The second-pass `sections` run of #109, taken with the fix and not truncated, has no T004. The second-pass `summary` run was truncated and reports 0 findings, so it says nothing.

Also read. #106 (test: loosen a performance bound): `insufficient_evidence` by R2e in both modes; the word is no longer `verified`, but the relaxation is still not flagged (old F-T5 open). #104 (docs only): R2e `not_applicable`, correct. #84: `summary` gives one criterion (the title), `unevidenced` with S 0.00 although 12 tests are linked; old F-L1 still open and its cause still not instrumented. #82: R2e in `sections`; `summary` gives 2 unevidenced criteria and R2b, closer to what a reviewer needs. #102: `summary` gives 1 criterion, weak with S 0.47, R2b.

## 5. Run-to-run variation (same code, different tamper results)

Eight PRs that were `truncated` or had producer timeouts in a first pass were run again in both modes (second pass, separate cache, same machine). Tamper does not depend on the intent mode, so each PR has four tamper runs. "Non-low findings" lists distinct rule:check pairs. The second-pass runs of #109 include the T004 fix; the other rows were unaffected by it.

| PR | run | verdict (rule) | tamper findings (high/medium/low) | non-low findings | markers |
|---|---|---|---|---|---|
| #3 | sections | insuff. (R2a) | 0/0/0 | - | truncated |
| #3 | summary | insuff. (R2a) | 0/0/0 | - | - |
| #3 | retry sections | insuff. (R2a) | 0/0/0 | - | - |
| #3 | retry summary | insuff. (R2a) | 0/0/0 | - | - |
| #9 | sections | insuff. (R2a) | 0/0/3 | - | - |
| #9 | summary | insuff. (R2a) | 0/0/0 | - | truncated |
| #9 | retry sections | insuff. (R2a) | 0/0/3 | - | - |
| #9 | retry summary | insuff. (R2a) | 0/0/3 | - | - |
| #22 | sections | failed (R1c) | 1/1/7 | T012:unverified_guarded_import, T017:collection_hook | - |
| #22 | summary | insuff. (R2a) | 0/0/0 | - | truncated |
| #22 | retry sections | insuff. (R2a) | 0/1/0 | T012:unverified_guarded_import | truncated |
| #22 | retry summary | insuff. (R2a) | 0/1/0 | T012:unverified_guarded_import | truncated |
| #28 | sections | insuff. (R2a) | 0/0/0 | - | truncated |
| #28 | summary | insuff. (R2b) | 0/2/3 | T009:pragma_no_cover | timeout:criterion_symbol_links, truncated |
| #28 | retry sections | insuff. (R2a) | 0/2/3 | T009:pragma_no_cover | - |
| #28 | retry summary | insuff. (R2b) | 0/2/3 | T009:pragma_no_cover | - |
| #100 | sections | insuff. (R2a) | 0/0/0 | - | truncated, timeout:symbol_test_links, timeout:assertions |
| #100 | summary | failed (R1c) | 1/0/0 | T001:test_deleted | truncated |
| #100 | retry sections | failed (R1c) | 6/7/3 | T001:test_deleted, T002:runtime_skip_conditional, T005:always_true, T005:self_comparison, T007:source_broad_swallow, T009:pragma_no_cover | truncated, timeout:symbol_test_links, timeout:assertions |
| #100 | retry summary | insuff. (R2a) | 0/0/0 | - | truncated, timeout:symbol_test_links, timeout:assertions |
| #103 | sections | insuff. (R2a) | 0/0/0 | - | truncated |
| #103 | summary | insuff. (R2b) | 0/0/1 | - | - |
| #103 | retry sections | insuff. (R2a) | 0/0/1 | - | - |
| #103 | retry summary | insuff. (R2b) | 0/0/1 | - | - |
| #107 | sections | insuff. (R2a) | 0/0/0 | - | truncated |
| #107 | summary | insuff. (R2a) | 0/0/5 | - | - |
| #107 | retry sections | insuff. (R2a) | 0/0/5 | - | - |
| #107 | retry summary | insuff. (R2a) | 0/0/5 | - | - |
| #109 | sections | insuff. (R2a) | 0/0/0 | - | truncated, timeout:assertions |
| #109 | summary | failed (R1c) | 1/0/2 | T004:conjunct_dropped | - |
| #109 | retry sections | insuff. (R2a) | 0/0/2 | - | - |
| #109 | retry summary | insuff. (R2a) | 0/0/0 | - | truncated, timeout:symbol_test_links, timeout:assertions |

Read off the table. #100 was `failed` in 2 of 4 runs and `insufficient_evidence` in 2. #22 was `failed` in 1 of 4. #109 was `failed` in 1 of 4 (the T004 false positive, now fixed). #107 had 0 findings when truncated and 5 low when not; #28 had 0 or 5 findings the same way. A verdict that depends on whether a 30 s tamper budget (`tamper/config.py:49`, `tamper/context.py:144`) or a 60/120 s Stage A budget (`verdict_v2/collect.py:67-77`) was hit cannot be audited. This is the old F4/F-P1, unchanged, and it is why no single-run tamper count should be quoted.

## 6. Findings still open

| ID | Finding | Evidence | Where | Proposed fix |
|---|---|---|---|---|
| F-X1 | Default extraction yields 0 criteria on this repo's PRs (29 of 29); `summary` yields at least one on 11 of 29, none proven | section 2 | `packages/intent/src/radius_intent/infrastructure/extraction/config.py:14` | Measure `summary` precision on a labelled sample (IN-09/IN-10) before promoting it; make "no intent found" the headline |
| F-P1 | Time budgets make output depend on load | section 5 | `tamper/config.py:49`, `tamper/context.py:144`, `apps/worker/src/radius_worker/verdict_v2/collect.py:67-77` | Work-unit budgets; record elapsed and budget in the bundle; never let a `truncated` run silently choose between `failed` and `insufficient_evidence` |
| F-T1b | A test renamed and rewritten below 0.6 similarity is still `test_deleted` high (#100) | case 7 | `tamper/rules/disabling.py:20` and `_is_rename_of` (`:33-52`) | Cap at medium when the same file gains a test with the same called names and at least as many assertions; tune the floor on data |
| F-T2b | `runtime_skip` guard detection is a name regex; a skip in `for/else` is not seen as conditional (#91, #101) | cases 2, 3 | `tamper/rules/disabling.py:177-187` (`_ENV_GUARD`), `:189-212` (`_guard_of`) | Treat a skip in a `For`/`While` `orelse` as conditional; treat a call to a helper named `*enabled*`/`*available*`/`*installed*` as an environment guard |
| F-T5a | T005 `self_comparison` high flags determinism checks (`row() == row()`); documented limitation, 4 highs in one #100 run | section 5 | `tamper/rules/assertions.py:219-220` | Cap at medium when both sides are the same call in a test whose name contains `determinis`, `idempot` or `stable` |
| F-T4 | Fixture/benchmark directories trigger T012/T016/T017 (#22) | case 6 | `tamper/rules/fixtures.py:49,101,122`, `tamper/rules/dependencies.py:136` | Path exclusions through the base-branch policy file; the replay does not exercise policy |
| F-T5 | No rule for relaxing numeric thresholds in assertions (#106) | case list | `tamper/rules/assertions.py:114` (`AssertionWeakened`) | New check under T004; evaluate on `scripts/tamper_eval.py` mutants first |
| F-T6 | T010 `continue-on-error` and T017 `collect_ignore` stay high and decide `failed` (#87, #22) | cases 5, 6 | `tamper/rules/config_weakening.py:185,232`, `tamper/rules/fixtures.py:49` | Cap at medium unless a policy requires the step; severities are still assumed |
| F-L1 | Terse-title criterion gets no counted evidence although 12 tests are linked (#84) | case list | criterion-link and relevance stage; cause not instrumented | Log edge counts per criterion, then measure |
| F-L2 | TypeScript/JavaScript unsupported by Stage A | 4 PRs carry the marker | Stage A language support | Product decision |
| F-U1 | "degraded" is shown as a marker code | section 2 | comment renderer | One plain sentence |
| F-D1 | `docs/verdict-v2.md:49` still cites the old "3 of 7" figure | grep | `docs/verdict-v2.md:49` | Update with this report (outside the scope of this change) |

`tamper/...` paths are under `packages/analysis/src/radius_analysis/`.

## 7. Bug fixed during the re-run

`e1c140f` (`fix(analysis): T004 conjunct_dropped ignores an and assertion split into several asserts`): `packages/analysis/src/radius_analysis/tamper/rules/assertions.py` (`AssertionWeakened._compare`) now compares the clause totals of the whole test before reporting a dropped clause. Test: catalog case `t004-conjunct-split-into-asserts` in `packages/analysis/tests/tamper_cases/cases_tests.py` (fails without the change, passes with it). Changelog fragment `changelog.d/tamper-t004-split-conjuncts.fixed.md`.

## 8. Not verified

- The `reason` strings in the saved JSON are cut at about 200 characters, so the T005 `always_true` finding in the second-pass #100 run was not read in full.
- Whether T017 on #22 and T010 on #87 are intended (the owner's call).
- Linux timings; behaviour with real CI results, policy files, waivers or `.radius/intent.yml` (none of the 29 PRs carry them).
- Whether `summary`-mode criteria resemble what a human would confirm; the `llm` mode (not run).
- That the second-pass #109 result is due to the fix alone: the fix was applied while the second pass was running, and no pre-fix rerun of #109 exists in a non-truncated state (the first `summary` pass is the only pre-fix evidence).
- Any comparison of runtimes with the old report (machine load differed).

## 9. Reproduce

```
export GH_TOKEN=$(gh auth token --user Mohith-c7)   # read-only GETs only
N="3 9 22 28 40 45 50 51 53 80 82 84 86 87 90 91 94 95 100 101 102 103 104 105 106 107 108 109 110"
python scripts/verdict_v2_replay.py --numbers $N --intent-mode deterministic --cache-dir <dir>/sections
python scripts/verdict_v2_replay.py --numbers $N --intent-mode summary       --cache-dir <dir>/summary
```
