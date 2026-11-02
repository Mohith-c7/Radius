# Pre-registration: Radius Intent-to-Evidence Verification (EP-02)

<!-- FREEZE-BLOCK-START -->
**Freeze status: DRAFT -- not frozen.**

| Field | Value |
|---|---|
| Document version | 0.2-draft |
| Freeze date | not frozen |
| Content hash (SHA-256, procedure in `CHANGELOG.md`) | DRAFT hash of v0.2-draft, for tracking only, not a freeze hash: `c01cb5fc6e325c7c9d2b2a29de48ccce9af19c3b2fc6444491625e28418be71f` |
| Frozen by (owner) | not frozen |
| External deposit (archive / registry / signed git tag) | not done |

Until this block says "FROZEN", every number in this file is a proposal. Do not run any confirmatory experiment (EP-07 to EP-12) against a test split before the freeze. After the freeze, the body of this file never changes; changes are amendments (section 14).
<!-- FREEZE-BLOCK-END -->

**Task:** EP-02. **Drafted:** 2026-11-02. **v0.2-draft:** 2026-11-02 (owner decisions in section 17 resolved by delegation, DEC-025; checklist status added; no analysis choice in sections 1 to 15 changed; still NOT frozen). **Depends on:** EP-01 (`../literature/`). **Parent plan:** `../EVALUATION_PLAN.md`.
**Citation rule:** only works that have an entry in `../literature/references.bib` are cited, by BibTeX key in backticks. Every figure taken from a paper is the one recorded in `../literature/related-work.md` (primary-page verified in EP-01). Nothing in this file is a result.

---

## 0. How to read this document

- "Initial guess, fixed at freeze" marks every threshold, tolerance, prior and sample-size assumption that has no empirical basis yet. It is a commitment once frozen, not a prediction.
- "Confirmatory" analyses are the ones listed per RQ as primary. Everything else is "secondary" (reported, Benjamini-Hochberg controlled) or "exploratory" (reported with an explicit label, no inferential claim).
- All RQs are reported whatever the outcome (section 13 and the fallback plan in `../EVALUATION_PLAN.md` section 8).

---

## 1. Claims being tested (reworded after EP-01)

EP-01 (`../literature/novelty-assessment.md`) showed that the original five claims overlap with existing work. They are restated here; this wording replaces `../EVALUATION_PLAN.md` section 1 for the purposes of the paper.

| # | Claim as pre-registered | What it is NOT claiming | Tested by |
|---|---|---|---|
| C1 | **Evidence-strength-aware criterion support.** Per-criterion support that discounts evidence by its ability to detect faults identifies unproven behavior that a "a passing test exists" rule does not. | Not "criteria-to-evidence mapping is new": AgentProof (`AgentProofRengGyu`) and ScopeProof (`ScopeProof`) map criteria to evidence, and requirements traceability is mature (`Antoniol2002`, `Lin2021`, `Fuchss2025`). | RQ1 (can criteria and links be recovered), RQ2 (comparison with B4 and B9 on the same criteria) |
| C2 | **A gold-free, PR-time predictor.** A score computed at review time, without the gold patch and without strengthened tests, predicts which test-passing agent patches are incorrect, better than pass rate, coverage, and LLM-based verifiers. | Not "mutation exposes weak tests for agent patches": SWE-ABS (`Yu2026sweabs`) shows this at benchmark time using the gold patch; UTBoost (`Yu2025utboost`) and PatchDiff (`Wang2026patchdiff`) relabel benchmarks. They are label sources and upper bounds here, not competitors for novelty. | RQ2 |
| C3 | **Evaluation contribution.** An evaluation of calibration and of risk-controlled abstention for PR acceptance under time and repo shift. | Not a new calibration or conformal method (`Platt1999`, `Guo2017`, `Angelopoulos2024crc`, `Angelopoulos2021ltt` exist; `Shahini2024` applies conformal prediction to JIT defect prediction and warns about vacuous coverage). | RQ3 |
| C4 | **Process signals computable at PR time add predictive value** beyond final-output features, with the AgentLens qualifiers: AgentLens (`Sahoo2026`) reports a Lucky Pass rate of 10.7% on a 1,815-trajectory subset covering 47 tasks, OpenHands only, ranging 0.5% to 23.2% across backends, code not released as of arXiv v4, and it evaluates runs that already pass using other passing runs of the same task as reference. | Not "process quality matters" (AgentLens shows that on passing runs); not a re-implementation of the Lucky tiers. Our setting has no same-task reference runs and tests prediction of correctness, not a process tier. | RQ4 |
| C5 | **Evaluation contribution.** Evidence-aware hunk ranking, compared with strong defect-prediction and LLM-reviewer rankings, with a controlled user study on seeded defects in agent-written PRs. | Not new ranking components (`Kamei2013`, `Pornprasit2021` exist); time-saving claims only from the user study. | RQ5 |

Overhead (RQ6) supports deployability and is not a novelty claim.

---

## 2. Conventions common to all RQs

### 2.1 Versions, seeds, reproducibility
- Every result row carries `algo_version`, git commit hash, dataset manifest hash, config hash and seed (`../DESIGN.md` section 9). A table that lacks them is not reportable.
- Master seed: 20261102 (initial guess, fixed at freeze). Derived seeds: bootstrap = master; mutant sampling = {11, 23, 37, 41, 53}; train/validation partitions = {101, 102, 103, 104, 105}.
- Bootstrap: 10,000 resamples (the plan's floor is 1,000), percentile intervals, resampling at the cluster level named per RQ (never at the patch level when patches share a task).
- Stochastic components (mutant sampling, embeddings, LLM runs) are repeated with the seed list above; the reported value is the mean over seeds, and the across-seed standard deviation is reported next to every table. LLM calls: provider/model version pinned and logged, temperature 0, 3 repeated runs per input, outputs cached by prompt hash. LLMs never touch the Radius verdict path (`../DESIGN.md` section 7); they appear only in the extraction/linking experiments and as baselines B3 and B7.

### 2.2 Splits (time-based and repo-based) and leakage rules
1. **Time split (primary).** Sort task instances by `created_at` (task creation date in the dataset manifest). The earliest 40% are the **dev** split (all tuning, feature design, thresholds); the latest 60% are the **test** split. The dev split is further divided by instance into 60% model-fit and 40% calibration (seeded). Cut points are computed by this rule from the manifest hash recorded at freeze, not chosen by eye.
2. **Repo split (secondary robustness).** Leave-one-repo-out (LORO) on the test split's repositories, plus leave-one-agent-out where agent identity is known. SWE-bench Verified covers few repositories (`Jimenez2024`; count to be read from the manifest), so repo-based results are reported per repo with a pooled estimate, not as the confirmatory analysis.
3. **Group integrity.** All patches for the same task instance are in the same split (instance is the cluster). Near-duplicate patches (identical normalized diff hash) within an instance are collapsed and their multiplicity stored.
4. **Test discipline.** The test split is evaluated once per frozen `algo_version` after tuning is closed and recorded in `CHANGELOG.md` (a "tuning closed" entry with commit hash). Any re-run on test after seeing test results is a deviation (section 14).
5. **No gold at inference.** Features for RQ2 to RQ5 are computed only from what exists at PR time: base repository, diff, tests present or added in the PR, issue/PR text, CI results, optionally the trajectory. They must not use: the gold patch, hidden/official tests that were not visible to the agent, strengthened tests (SWE-ABS, UTBoost), leaderboard labels, or any label source below. Violations are checked by a feature-provenance test in the harness (EP-05).
6. **Label isolation.** Label-source artifacts are stored in a separate bucket not mounted in the feature pipeline.
7. **LLM contamination.** For B3 and B7 (and for LLM-assisted extraction) the model's knowledge cutoff is recorded; results are also reported on the subset of test instances created after that cutoff when one exists (contamination sensitivity). SWE-Bench+ (`Aleithan2024`) leakage-filtered tasks are used as a second sensitivity subset where available.
8. **Tuning budget parity.** Radius and each baseline get the same tuning budget on dev only: 5-fold instance-grouped cross-validation and at most 50 hyperparameter configurations (random search, same seeds). Defaults are fixed before tuning and reported.

### 2.3 Label sources and how they are used
Defined once, referenced by RQ2 to RQ4.

| Label | Definition | Role |
|---|---|---|
| `L_ABS` (primary) | Agent patch passes the original official tests but fails the SWE-ABS strengthened test suite (`Yu2026sweabs`; released code MIT and data on Hugging Face per EP-01). Positive class = incorrect. | Primary label for RQ2, RQ3, RQ4 |
| `L_UTB` | Rejected under UTBoost-augmented tests (`Yu2025utboost`) | Secondary; artifact not located in EP-01, requires contacting authors |
| `L_PD` | Plausible patch judged different from gold and certainly incorrect in the PatchDiff study (`Wang2026patchdiff`) | Secondary; artifact not located |
| `L_union` / `L_cons` | Incorrect under any / under at least two available sources | Sensitivity |
| `L_audit` | Manual audit of 200 randomly drawn labelled patches by two reviewers (CA-09) | Estimates label noise; used for the bias-bound sensitivity analysis in 2.6 |

SWE-ABS reports that UTBoost strengthened only 10 of 500 instances against 251 for SWE-ABS (EP-01), so source disagreement is expected; agreement (Cohen's kappa on the overlap) is reported before any model result.

### 2.4 Statistical procedures (named)
| Purpose | Procedure |
|---|---|
| Paired AUROC comparison | DeLong test with a cluster-robust (by task instance) variance, because several agents' patches share an instance. The paired cluster-bootstrap CI for the AUROC difference is computed in parallel; if the two disagree on significance, the conservative one governs and the disagreement is reported. |
| Single AUROC / PR-AUC / recall at fixed FPR | Cluster bootstrap percentile 95% CI |
| Paired binary outcomes at a fixed operating point | McNemar exact test (conditional binomial) on discordant pairs; effect size = odds ratio of discordant pairs, plus risk difference with bootstrap CI. Operating points are set on dev only (FPR = 0.10, initial guess). With clustered data the McNemar test is run on instance-level aggregated outcomes and checked with the cluster bootstrap. |
| Paired continuous outcomes | Wilcoxon signed-rank on cluster-level (per instance or per PR) paired differences; effect size = matched-pairs rank-biserial correlation plus Hodges-Lehmann median difference with CI |
| Calibration | ECE (10 equal-mass bins as primary, 10 equal-width bins also reported), Brier score with its decomposition, negative log-likelihood, reliability curves; paired cluster bootstrap for differences in ECE and Brier |
| Selective prediction | Risk-coverage curves, accepted-set error with exact Clopper-Pearson interval |
| Multiple comparisons, confirmatory | **Holm-Bonferroni** at family-wise alpha = 0.05, applied within each RQ's confirmatory family (the family is listed per RQ). RQs are separate scientific claims and are not corrected against each other; this is stated in the paper. |
| Multiple comparisons, secondary | Benjamini-Hochberg at FDR 0.10 within each RQ's secondary family; results labelled "secondary" |
| Exploratory | No p-values presented as evidence; descriptive CIs only |
| Threshold hypotheses | A hypothesis of the form "metric >= target" (or "<= target") is **supported** only if the point estimate meets the target **and** the one-sided Holm-adjusted bootstrap bound stays within the stated tolerance of the target (tolerances are per hypothesis, initial guesses). Otherwise it is **not supported**; between the two is reported as "inconclusive". |

### 2.5 Effect sizes and minimum practically important differences (MPID)
All MPIDs are initial guesses fixed at freeze. A comparison counts as a win only if it is **both** statistically significant after Holm adjustment **and** the point estimate reaches the MPID.

| Metric | MPID |
|---|---|
| AUROC difference (RQ2, RQ4) | 0.05 (RQ2), 0.03 (RQ4, nested models) |
| ECE | 0.01 absolute |
| Hit rate @ top 20% hunks (RQ5 replay) | 0.10 absolute |
| User-study detection rate | 0.15 absolute |
| Linking Top-3 accuracy / F1 (RQ1) | 0.05 absolute |

### 2.6 Missing, censored and noisy labels
- `unknown` outcome labels are excluded from primary analyses; their count and a comparison of their features with labelled items are reported. Sensitivity: best-case and worst-case imputation bounds on the primary metric.
- Real-PR outcomes (CA-01) use horizon h = 90 days (initial guess). A PR with less than h days of follow-up and no event is right-censored, excluded from the primary analysis, and handled in sensitivity analyses by inverse-probability-of-censoring weighting and a Kaplan-Meier time-to-defect view. Revert/follow-up-fix labels are known to miss silent defects; this is a stated threat.
- Label noise: using `L_audit`, the estimated label error rate is used for a bias-bound sensitivity analysis of AUROC (assuming errors independent of features, then worst-case). The paper reports the primary metric and the bound.
- Source disagreement: results are reported for each label source separately; the headline is `L_ABS`, the robustness claim requires the sign of the effect to agree on `L_cons` where it exists.

### 2.7 Exclusion criteria (applied before looking at any model result; logged with counts and reasons)
1. Patch does not apply to the base commit, is empty, or touches no source file.
2. Repository environment cannot be built and tests run in the sandbox after 3 attempts (infrastructure failure, not a model failure).
3. Official tests are flaky: the gold patch's tests give inconsistent results over 3 reruns (instance dropped entirely).
4. Duplicate normalized diffs (kept once, multiplicity recorded).
5. Pipeline failure for Radius or any compared method on a patch: handled as below.
6. Instances also used in dev are never in test.

**Pipeline-failure policy.** Primary comparisons use the common-support subset where all compared methods return a score (paired design). The sensitivity analysis treats a failure as "not flagged" (lowest risk). If more than 15% of eligible patches are excluded for items 2 or 5, or if exclusion rates differ between label classes (Fisher exact test, p < 0.05), the result is flagged as at risk of selection bias in the paper.

### 2.8 Reporting
- Report every pre-registered analysis including null and negative results, with CIs, effect sizes, seeds, N and exclusions.
- Report the achieved N and the minimum detectable difference (section 12) next to each confirmatory test.
- Pre-freeze pilot work on dev data is allowed and must be listed in `CHANGELOG.md` under "Pre-freeze pilots".

---

## 3. Datasets and assembly (summary; assembly is EP-03)

| Dataset | RQs | Notes |
|---|---|---|
| SWE-bench Verified tasks and public agent patches (`Jimenez2024`), with strengthened-test labels from SWE-ABS (`Yu2026sweabs`): 11,041 passing patches of which 2,184 (19.78%) were rejected, per EP-01 | RQ2, RQ3, RQ4 (patches); RQ6 (timing sample) | Prevalence of the positive class is therefore about 0.20 (used in the power analysis, to be re-measured on the manifest). Licences of patch submissions to be checked. |
| UTBoost / PatchDiff artifacts | RQ2 secondary labels | Not located in EP-01; contact authors |
| SWE-Bench+ (`Aleithan2024`), SWT-Bench (`Mundler2024`), SWE-Mutation (`Sun2026swemutation`), ImpossibleBench (`Zhong2025`) | leakage subset; B8; mutant source; tamper ground truth | Check licences at download |
| Radius mutation benchmark (`benchmarks/`, `docs/benchmarks/`) with criteria annotations | RQ1, RQ5 seeded fixtures | Seeded faults give known ground truth |
| Gold intent/link set (IN-09, LK-07, EP-04) | RQ1 | At least 150 PRs, two independent annotators plus adjudication |
| Own agent trajectories (PR-01 logging), several agent configurations on benchmark tasks | RQ4 | Full traces only for the primary analysis |
| AIDev (`Li2026aidev`) | exploratory corpus for CA-01 and descriptive statistics | No criteria annotations; licence unverified; not used for confirmatory tests |
| AgentLens-Bench | none | Not released as of arXiv v4; if released before freeze, add to RQ4 as an external check by amendment |
| Consented design-partner PRs and public OSS agent PRs (CA-01) | RQ3 exploratory/secondary; RQ5 replay | Public/benchmark first, partner data only with explicit opt-in (DEC-014) |

---

## 4. Baselines (numbering from `../EVALUATION_PLAN.md` section 4, as updated by EP-01)

Note: `../literature/novelty-assessment.md` numbers some extra baselines differently (for example it lists the rubric verifier as B9 and the reproduction-test verifier as B10). This pre-registration follows the numbering in `../EVALUATION_PLAN.md` section 4. Reconcile the two files before freeze.

| ID | Baseline | Used in |
|---|---|---|
| B0 | CI pass/fail only | RQ2 (degenerate on test-passing patches, see 6.3), RQ3 input |
| B1 | Line/branch coverage of changed lines | RQ2, RQ3 input |
| B2 | Radius v1 heuristic score | RQ2, RQ3 input |
| B3 | LLM-as-judge on diff + issue (fixed prompt, 3 runs); judge biases documented (`Zheng2023`, `Moon2026`, `Jin2025`, `Zhao2026`) | RQ2 |
| B4 | AgentProof-style criterion mapping with "a passing test exists" (B4a, re-implemented from the README of `AgentProofRengGyu`; `AgentProofGenRamzi` is a different tool and is not B4) | RQ1 extraction, RQ2 |
| B5 | Verik/SlopGate-style tamper rules only (`Verik`, `SlopGate`) | RQ2 secondary |
| B6 | Mutation score of the whole file, no intent linking (mutation tooling as in `Papadakis2019` survey; `Mutahunter` as one available engine) | RQ2 |
| B7 | Execution-free rubric verifier (`Raghavendra2026`) | RQ2 |
| B8 | Fail-to-pass reproduction-test verifier, SWT-Bench style (`Mundler2024`) | RQ2 secondary |
| B9 | ScopeProof-style static criterion-to-candidate retrieval (`ScopeProof`; ideas re-implemented only, evaluation-only licence) | RQ1 linking, RQ2 secondary |
| B10 | Linking: BM25/VSM, T-BERT-style (`Lin2021`), LiSSA-style RAG (`Fuchss2025`), PR-issue alignment classifier (`Altunhan2026`) | RQ1 |
| B11 | Calibration: Platt (`Platt1999`), isotonic (`NiculescuMizil2005`), temperature scaling (`Guo2017`), selective classification with held-out threshold (`ElYaniv2010`, `Geifman2017`), Learn-then-Test (`Angelopoulos2021ltt`) | RQ3 |
| B12 | Triage: random, by-size, by-churn, effort-aware JIT (`Kamei2013`), JITLine (`Pornprasit2021`), LLM reviewer (`PRAgent`; c-CRAB protocol, `Zhang2026ccrab`) | RQ5 |
| Oracle | SWE-ABS-style strengthened tests as oracle (`Yu2026sweabs`): not deployable, ceiling only | RQ2 reference |

Fair comparison rules: same inputs, same splits, same tuning budget, same seeds, variance reported. A baseline that cannot be run for licence or availability reasons is listed as "not run" with the reason, never silently dropped.

---

## 5. RQ1 -- Criterion extraction and linking

**Question.** Can criteria be extracted and linked to code and tests accurately enough to be useful?

### 5.1 Operational definitions
- **Gold criterion.** An atomic, testable statement of intent, annotated on the PR's intent sources with a character span (`../DESIGN.md` section 6.1). Two annotators label independently from written guidelines; a third adjudicates. Annotators first mark each PR as "well-specified" or not (has explicit acceptance criteria in a checklist, an Acceptance Criteria heading, Gherkin, or a linked issue with numbered requirements) before seeing any system output.
- **Match.** A system criterion matches a gold criterion if their source spans have character-IoU >= 0.5 (initial guess); 10% of matches are audited by hand.
- **Gold link.** For a gold criterion: the set of changed or blast-radius symbols that implement it, and the tests that exercise those symbols, labelled by the two annotators and adjudicated.
- **Top-3 accuracy.** Share of criteria with at least one gold symbol among the top 3 ranked candidates. **MRR** = mean reciprocal rank of the first gold symbol.
- **Human acceptance rate.** Share of system criteria confirmed unchanged by the user in the product UI; descriptive only, from design-partner use.

### 5.2 Hypotheses (initial guesses, fixed at freeze)
- **H1a.** On well-specified PRs, extraction F1 >= 0.75 (criterion-level, match as above). Tolerance: one-sided Holm-adjusted lower bound >= 0.70.
- **H1b.** On the same PRs, linking Top-3 accuracy >= 0.80 (criterion to symbol). Tolerance: lower bound >= 0.75.
- **H1c.** Radius linking Top-3 accuracy exceeds each of BM25/VSM, B9 and LiSSA-style RAG by at least 0.05 (MPID).
- **Secondary:** MRR, precision and recall separately; F1 on all PRs (not only well-specified); symbol-to-test link accuracy; T-BERT-style baseline if training data suffice; extraction F1 versus B4 rules; PR-level alignment versus the B10 PR-issue classifier (coarse, PR-level only).

### 5.3 Data, splits
Gold set of at least 150 PRs (EP-04). 30 PRs go to dev (guideline and prompt tuning, annotator calibration), at least 120 PRs form the test set, split by repository so that no test repository appears in dev where possible and ordered by PR date within repository otherwise. A separate 30-PR pilot used to write the guidelines is discarded from both.

### 5.4 Statistics
Cluster (PR) bootstrap, 10,000 resamples, for P/R/F1, Top-3 and MRR. H1c: McNemar exact test on per-criterion Top-3 hits (aggregated per PR and checked with the cluster bootstrap). Confirmatory family: {H1a, H1b, H1c vs BM25/VSM, H1c vs B9, H1c vs LiSSA-style}, Holm over 5.

**Annotation agreement.** Cohen's kappa for the "is this an atomic criterion" decision on candidate spans and for link labels; a kappa below 0.60 (initial guess) on a 30-PR pilot triggers guideline revision and re-annotation before the test set is annotated. Agreement is reported for the final set with a bootstrap CI.

### 5.5 Power and sample size (arithmetic)
- Precision-style proportions: with p = 0.75 and a target 95% half-width h = 0.05, an independent sample needs n = 1.96^2 x 0.75 x 0.25 / 0.05^2 = 3.8416 x 0.1875 / 0.0025 = 288.1, so 289 criteria. Criteria within a PR are correlated; assume 4 criteria per PR and intra-PR correlation 0.2 (assumptions), so the design effect is 1 + (4 - 1) x 0.2 = 1.6 and the clustered requirement is 289 x 1.6 = 461 criteria (about 116 PRs).
- For Top-3 at p = 0.80: n = 3.8416 x 0.16 / 0.0025 = 245.9, so 246, x 1.6 = 394 criteria.
- 120 test PRs x 4 criteria = 480 criteria >= 461, so the gold set meets the requirement under these assumptions. If the realized criteria per PR is lower, the achieved half-width is reported and the claim is weakened accordingly.
- Kappa precision: with n = 600 items, observed agreement 0.85 and chance agreement 0.50 (assumptions), SE(kappa) ~ sqrt(0.85 x 0.15 / (600 x 0.5^2)) = sqrt(0.1275 / 150) = 0.029, a 95% half-width of about 0.057.

### 5.6 Stopping and exclusions
Annotation stops when the target counts are reached; no PR is dropped after seeing system output. PRs with no recoverable intent source are kept in the all-PR analysis and excluded from the well-specified analysis only by the annotators' pre-output flag.

---

## 6. RQ2 -- Gold-free PR-time prediction of incorrect-but-passing patches (claims C1, C2)

**Question.** Does evidence-quality weighting detect weak verification better than baselines, without the gold patch?

### 6.1 Operational definitions
- **Unit.** One agent patch for one task instance. **Cluster** = task instance.
- **Population (primary).** Patches that pass the original official tests (the "plausible" patches), after the exclusions in 2.7.
- **Label.** `L_ABS` (positive = incorrect despite passing). Secondary labels in 2.3.
- **Predictor.** `UIM`, the unevidenced intent mass, from the frozen pipeline (`../DESIGN.md` section 6.4), higher = riskier. Criteria come from the deterministic+LLM extraction in its frozen configuration; the intent source is the issue text and PR description only (no gold). All algorithm hyperparameters (`tau_support`, lambda, `cap_static`, `iota_agent`, link caps) are set on dev by the 2.2 rule 8 procedure and recorded at the "tuning closed" entry.
- Secondary predictors: minimum `S(c)`; mean `S(c)`; the logistic combination of UIM, tamper counts and `d_mut` summaries fitted on dev.

### 6.2 Hypotheses (initial guesses, fixed at freeze)
- **H2.** On the test split, AUROC(UIM) >= 0.70 (tolerance: lower bound >= 0.65), **and** AUROC(UIM) exceeds each of B1, B2, B3, B4, B6, B7 by at least 0.05, each significant after Holm adjustment. The comparison with B4 is the test of claim C1 (same criteria, "a passing test exists" evidence versus fault-detection-weighted evidence). The comparison with B3 and B7 tests the claim against LLM verifiers.
- **H2-secondary (S2.1 to S2.6):**
  1. PR-AUC and recall at FPR = 0.10 (operating point set on dev).
  2. Comparison with B5, B8 and B9 (not in the confirmatory family).
  3. Position against the oracle: share of the oracle-to-B3 AUROC gap closed by UIM.
  4. Value of mutation: UIM using `d_eff` with mutation versus with static assertion strength only, and the correlation of `a_static` and `d_mut` (EP-08).
  5. Where CI misses: among patches that pass CI and that Radius flags, precision (PPV) of the flag for `L_ABS`, McNemar against B4's flag set at the same FPR.
  6. Consistency across labels `L_UTB`, `L_PD`, `L_cons`.

### 6.3 B0 note
On the primary population every patch passes the official tests, so B0 (CI pass/fail) is constant and its AUROC is 0.5 by construction. B0 is therefore reported as a reference line and excluded from the confirmatory family. A second population "all patches, including failing ones" with `L_ABS` extended (failing patches counted as incorrect) is reported as secondary, where B0 is non-degenerate.

### 6.4 Splits
Time split as in 2.2 (primary); LORO and leave-one-agent-out (secondary).

### 6.5 Statistics
Confirmatory family: six comparisons (UIM vs B1, B2, B3, B4, B6, B7), Holm over m = 6, two-sided DeLong with cluster-robust variance, mirrored by cluster-bootstrap CIs for the AUROC difference. The H2 absolute-threshold part is checked with the one-sided bootstrap bound. Secondary family: BH at 0.10.

### 6.6 Power and sample size (arithmetic)
Assumptions (initial guesses, fixed at freeze): prevalence of the positive class 0.20 (from the 2,184 / 11,041 = 0.198 figure in EP-01), baseline AUROC 0.65, Radius AUROC 0.70 (difference 0.05 = MPID), correlation between the two AUROCs on the same patches r = 0.5, alpha per test = 0.05 / 6 = 0.0083 (the strictest Holm step), power 0.80, design effect 2.0 for clustering (about 20 agents' patches per instance and an assumed intra-instance correlation of 0.05 give 1 + 19 x 0.05 = 1.95, rounded up).
- Variance of one AUROC (Hanley-McNeil approximation): Var(A) = [A(1-A) + (nP - 1)(Q1 - A^2) + (nN - 1)(Q2 - A^2)] / (nP x nN), with Q1 = A / (2 - A), Q2 = 2A^2 / (1 + A).
- Variance of the paired difference: Var(A1) + Var(A2) - 2 r sqrt(Var(A1) Var(A2)), multiplied by the design effect.
- Required: |A2 - A1| / SD(difference) >= z(1 - 0.0083/2) + z(0.80) = 2.64 + 0.84 = 3.48, i.e. SD(difference) <= 0.05 / 3.48 = 0.0144.
- Solving numerically gives **N = 4,920 patches, of which 984 positives** (without design effect: 3,690 patches with 738 positives; with design effect 3.0: 7,380).
- Minimum detectable AUROC difference at this alpha and 80% power, design effect 2.0: 0.064 at N = 3,000; 0.055 at 4,000; 0.050 at 5,000; 0.043 at 6,600.
- **Planned N:** the full test split (about 60% of 11,041 = 6,600 patches, 1,300 positives, if the manifest matches the EP-01 figures). **Minimum for confirmatory status: 5,000 patches (about 1,000 positives).**

### 6.7 Stopping rules and exclusions
If compute caps force fewer than all patches, sample whole task instances at random (seeded), not patches, and stop at the first instance count whose patch total reaches the minimum. Below 5,000 patches H2 is reported as "underpowered", with the achieved minimum detectable difference. No early stopping on observed results.

---

## 7. RQ3 -- Calibration and risk-controlled abstention (claim C3)

**Question.** Is the trust probability calibrated, and does conformal abstention control the error among accepted PRs?

### 7.1 Operational definitions
- **Trust probability P.** Calibrated probability that a test-passing patch is correct, from the frozen logistic model on dev features (`../DESIGN.md` section 6.7) followed by the pre-specified calibrator: isotonic if the calibration split has at least 1,000 patches, otherwise Platt scaling (rule is an initial guess, fixed at freeze). Process signals are not features in RQ3's primary analysis (the SWE-ABS patches have no traces).
- **Label.** `L_ABS`; target Y = 1 if correct.
- **Accept / defer.** Accept if P >= threshold t chosen on the calibration split by the procedure below; otherwise `needs_review`.
- **Risk guarantee procedure (primary).** Conformal risk control (`Angelopoulos2024crc`) with the shifted loss l(t) = (1[incorrect] - alpha) x 1[accepted at t], so that E[l] <= 0 is equivalent to accepted-set error <= alpha. Whether this loss meets the monotonicity and boundedness conditions must be verified by the implementer (CA-05) before freeze. Alternative (secondary and fallback): Learn-then-Test (`Angelopoulos2021ltt`) with delta = 0.10.
- **alpha** = 0.10 (initial guess, fixed at freeze).

### 7.2 Hypotheses (initial guesses, fixed at freeze)
- **H3a.** On the test split, ECE (10 equal-mass bins) < 0.05 for the calibrated P. Supported only if N_test >= 2,000 and the upper 95% bootstrap bound is < 0.07.
- **H3b.** On the time-based test split, the accepted-set error is <= alpha = 0.10 with a one-sided exact Clopper-Pearson 95% upper bound <= 0.13 (tolerance 0.03), **and** coverage (accepted share) >= 0.30 so that the guarantee is not vacuous (cf. `Shahini2024`, where the 95% guarantee covered only a small share of predictions).
- **H3c.** Over 200 seeded repartitions of the test data into instance-grouped calibration/test halves (exchangeable case), the share of repartitions with accepted error > alpha is <= 0.15 (delta + 0.05).
- **Secondary:** calibrated P has lower Brier than the uncalibrated model and than each B11 alternative (paired cluster bootstrap, Wilcoxon on instance-level Brier contributions); coverage-risk curves for all B11 methods; ECE under LORO and time shift; reliability curves; Brier decomposition.

### 7.3 Splits
Calibration and model-fit splits come from dev (2.2). Test is the time-based 60%. Exchangeability across repos, agents and time is doubtful; the shift results (time split, LORO) are the primary evidence and the repartition result H3c is the optimistic reference. Real-PR outcomes (CA-01) are exploratory unless at least 2,000 uncensored labelled PRs from at least 20 repositories exist at freeze (initial guess), in which case they form a second confirmatory population with the same hypotheses.

### 7.4 Statistics
Confirmatory family: {H3a, H3b, H3c}, Holm over 3. Secondary family: BH at 0.10. Cluster bootstrap by instance.

### 7.5 Power and sample size (arithmetic)
- **ECE noise floor.** Even a perfectly calibrated model has positive expected ECE because bin means are noisy. We simulated 400 draws of n items with predicted probabilities ~ Beta(1.2, 2.8) (mean 0.30; an assumption), outcomes drawn from those probabilities, ECE with 10 equal-mass bins: mean ECE under perfect calibration is 0.064 at n = 250, 0.045 at n = 500, 0.032 at n = 1,000, 0.0225 at n = 2,000 (95th percentile 0.033), 0.016 at n = 4,000. A target of 0.05 is unreachable at n = 250 to 500 and has little headroom at 1,000; hence the N_test >= 2,000 requirement. Recompute the floor with the real dev score distribution before freeze.
- **Accepted-set test.** Exact upper bound with k errors among n_a accepted at an observed error of 0.08: n_a = 200 gives upper bound 0.127; 400 gives 0.111; 800 gives 0.101. To certify alpha = 0.10 with tolerance 0.03, n_a >= 400 accepted items is needed; at coverage 0.30 that means N_test >= 400 / 0.30 = 1,333, so the 2,000 floor covers both.
- **Conformal slack.** The finite-sample slack of conformal risk control with a loss bounded in an interval of width 1 is of order 1 / (n_cal + 1); with n_cal >= 1,000 this is about 0.001, negligible next to the 0.03 tolerance.

### 7.6 Stopping and exclusions
Same as RQ2. If N_test < 2,000, H3a and H3b are reported as exploratory.

---

## 8. RQ4 -- Incremental value of process signals (claim C4)

**Question.** Do process signals computable at PR time add predictive power over final-output features?

### 8.1 Operational definitions
- **Population.** Runs from our own harness (PR-01 logging) of at least 4 agent configurations on SWE-bench Verified tasks, restricted to runs that pass the official tests (the setting AgentLens evaluates, so numbers are comparable in kind though not in value) and to **full traces**. Label `L_ABS`.
- **Final-output model M_out.** Logistic model on: patch size, number of files and hunks, coverage of changed lines, tests added/edited flag, plus the Radius evidence features (UIM, `S(c)` summaries, tamper counts, `d_mut` summaries). No process features.
- **Length/variance control M_len.** M_out plus trajectory length and variability features (in the spirit of `Majgaonkar2025`).
- **Full model M_proc.** M_out plus the process signals of `../DESIGN.md` section 6.6 (`test_edit_before_pass`, `assertion_removed_then_green`, `retry_count`, `edit_revert_thrash`, `scope_growth`, `time_to_green`, `late_test_weakening`, `flaky_pass_reliance`, `ignored_failure`, `dependency_added_unverified`).
- Plain outcome-only model R0 (without Radius evidence features) is also fitted as a secondary reference.
- All models are fitted on dev with the same tuning budget (2.2 rule 8) and evaluated on the same test runs.

### 8.2 Hypotheses (initial guesses, fixed at freeze)
- **H4.** AUROC(M_proc) - AUROC(M_out) >= 0.03 and AUROC(M_proc) - AUROC(M_len) >= 0.03, each significant after Holm adjustment (family of 2), **and** the observed difference exceeds the 95th percentile of the differences obtained when process-signal rows are permuted across runs within agent-by-difficulty strata (1,000 permutations), to guard against gains from added dimensionality.
- **Secondary:** ECE and Brier change (M_proc vs M_out; MPID 0.01 in ECE); gain versus R0; per-signal marginal contribution (drop-one); agent-wise differences; partial-trace stratum (exploratory); git-history-inferred signals (PR-05) versus real traces; AgentLens-style tiers as an extra baseline only if its code or data are released (needs same-task reference runs; re-implement from the paper otherwise, flagged as approximate).

### 8.3 Statistics
DeLong with cluster-robust variance (cluster = task instance) for nested models evaluated on a held-out test (valid because the models are fitted on dev only); cluster-bootstrap CIs; paired cluster bootstrap for ECE and Brier differences.

### 8.4 Power and sample size (arithmetic)
Assumptions (initial guesses): prevalence 0.20; M_out AUROC 0.70; M_proc AUROC 0.73 (difference 0.03 = MPID); correlation between the two AUROCs r = 0.9 (nested models share most of their information); alpha per test 0.05 / 2 = 0.025; power 0.80; design effect 1.5 (about 5 agent configurations per task, intra-task correlation 0.125, 1 + 4 x 0.125 = 1.5). Using the Hanley-McNeil variance of 6.6: **N = 1,530 passing full-trace runs, of which 306 positives.** Sensitivity: with r = 0.8 the requirement is 3,060 runs (612 positives); with a true difference of 0.05 and r = 0.9 it is 550 runs. **Minimum for confirmatory status: 1,500 runs with at least 300 positives**; below that H4 is reported as underpowered with its minimum detectable difference.

### 8.5 Stopping and exclusions
Runs with incomplete traces are not in the primary analysis; the count by agent is reported (proprietary agents may only yield partial traces). Runs where the harness crashed are excluded and counted. Data collection stops when the minimum is reached or the compute budget is exhausted (declared at freeze), never based on an interim effect estimate.

---

## 9. RQ5 -- Risk-ranked review triage (claim C5)

**Question.** Does evidence-aware triage help reviewers find defects?

### 9.1 Part A: offline replay
- **Unit.** A PR (or seeded fixture) with known defective hunks. **Defect hunk** = a hunk containing at least one line that is (i) a seeded-fault location in a fixture or (ii) identified as bug-inducing by an SZZ-style procedure from a linked follow-up fix, validated by manual check of 100 randomly chosen items. (The exact procedure is finalized in EP-03; label noise is a stated threat.)
- **Metric.** Recall@20%: share of defect hunks within the top 20% of hunks by risk, per PR. Secondary: recall at fixed line budgets, mean reciprocal rank of the first defect hunk, effort-aware Popt-style area (reported, not confirmatory).
- **Eligibility.** PRs with at least 10 hunks and at least one defect hunk (top 20% is degenerate for small PRs).
- **Hypotheses (initial guesses, fixed at freeze).**
  - **H5a.** Mean Recall@20% of the Radius ranking >= 0.60 (the random expectation is 0.20); tolerance: lower 95% bound >= 0.50.
  - **H5b.** Radius Recall@20% exceeds each of random, by-size, Kamei-style effort-aware JIT, JITLine and the LLM reviewer (B12) by at least 0.10.
- **Statistics.** Wilcoxon signed-rank on per-PR paired differences; confirmatory family {H5a, five H5b comparisons}, Holm over 6; secondary BH. Where a baseline cannot be run (for example JITLine requires training data), it is listed as not run.
- **Power (arithmetic).** H5b: paired difference with assumed SD 0.30 (initial guess) and MPID 0.10, so dz = 0.10 / 0.30 = 0.333; alpha for the strictest Holm step in the family of 6 = 0.05 / 6 = 0.0083; n = ((z(1 - 0.0083/2) + z(0.80)) / dz)^2 = ((2.638 + 0.842) / 0.333)^2 = 109.2; dividing by the Wilcoxon asymptotic relative efficiency 0.955 gives 114.4, so **115 PRs**. H5a: one-sample, null mean 0.50, true mean 0.60, SD 0.25, alpha 0.05 two-sided: n = ((1.96 + 0.84) / 0.4)^2 = 49. **Planned and minimum: 150 eligible PRs** (the minimum detectable paired difference at n = 150 is (2.638 + 0.842) x 0.30 / sqrt(150 x 0.955) = 0.087 at alpha 0.0083, SD 0.30).

### 9.2 Part B: user study (TR-05)
- **Design.** Within-subject crossover. Each participant reviews 4 agent-written PRs in the same interface, 2 with the triage ranking and rationale and 2 with the default file-order diff. Condition order and PR sets are counterbalanced by a Latin square; PR sets are matched on size and hunk count. Each PR carries 4 seeded defects (initial guess), each verified by two people as a real defect not revealed by a failing test. A 20-minute cap per PR (initial guess).
- **Participants.** Developers with at least one year of Python experience; screening quiz; informed consent; institutional approval or an explicit determination that none is required (a freeze prerequisite). Three pilot participants debug the protocol and are excluded from analysis; pilot data are never pooled.
- **Primary outcome.** Detection rate: seeded defects correctly identified (hunk overlap and a correct rationale, judged by two raters blinded to condition) divided by seeded defects, within the time cap, averaged per participant and condition.
- **Interpretation note.** The plan's "more defects per minute" is operationalized by a fixed time cap on the primary outcome to avoid trading speed against accuracy; defects per minute and time-to-first-defect are secondary. The owner may prefer a different primary (decision list, section 17).
- **Hypothesis H5c (initial guess).** Detection rate with triage exceeds detection rate without by at least 0.15 (MPID), significant at alpha = 0.05 (single primary comparison, no multiplicity).
- **Secondary (BH).** Defects per minute; time to first true defect (log-rank / Cox model with censoring at the cap); false-positive flags per PR; perceived workload (questionnaire fixed at freeze); subjective trust.
- **Analysis.** Participant-level paired difference; Wilcoxon signed-rank; effect size = mean difference with 10,000-resample bootstrap 95% CI and matched-pairs rank-biserial correlation. Sensitivity: logistic mixed model at the defect level (random intercepts for participant and PR; fixed effects for condition, order, PR set).
- **Power (arithmetic).** Assumptions (stated, not measured): detection rate 0.40 without triage and 0.55 with (difference 0.15); SD of the participant-level paired difference 0.25 (each participant contributes 8 seeded defects per condition: binomial SD at p = 0.5 is sqrt(0.25 / 8) = 0.177 per condition, plus between-participant variability), so dz = 0.15 / 0.25 = 0.60. Two-sided paired test, alpha 0.05, power 0.80: noncentral-t calculation gives **n = 24 participants** (power 0.804); the Wilcoxon correction (divide by 0.955) gives 26; allowing 10% non-completion gives **29 recruited**. Sensitivity: dz = 0.5 needs 34 (Wilcoxon 36, recruit 40); dz = 0.8 needs 15 (Wilcoxon 16, recruit 18). Power at the plan's minimum of 12 participants is 0.35 for dz = 0.5, 0.48 for dz = 0.6 and 0.71 for dz = 0.8, so 12 participants can only detect very large effects.
- **Stopping rule.** Target 29 recruited and at least 24 completing both conditions. No interim analysis of outcomes. Recruitment stops at the target or at a recruitment deadline fixed at freeze; if fewer than 24 complete, the analysis is run as planned and labelled underpowered, and the achieved power is reported. A session may be halted only for participant safety or data-integrity reasons.
- **Exclusions.** Failed screening quiz; incomplete session (fewer than both conditions); a documented protocol breach (for example seeing seeded-defect locations); all decided before unblinding the raters' scores.

---

## 10. RQ6 -- Overhead

**Question.** Is the cost acceptable?

- **Definitions.** Latency = wall-clock time from job start (webhook or CLI invocation) to verdict published, on a hardware and sandbox configuration declared at freeze (CPU, memory, no network). "Cheap verdict" = everything except mutation; "mutation stage" = the mutation job with its configured budget. Cost per PR = compute time at a stated unit price plus LLM tokens at the provider's list price on the measurement day, reported separately. Cold-cache and warm-cache runs are separate series.
- **Population.** At least 300 PRs from the RQ2 test split stratified by diff-size terciles (at least 100 per tercile for an exploratory per-stratum view).
- **Hypotheses (initial guesses, fixed at freeze).** H6a: p95 latency of the cheap verdict < 120 s. H6b: p95 latency of the mutation stage < 900 s within the configured budget. Timeouts and failures count as exceeding the limit.
- **Statistics.** Nonparametric one-sided 97.5% upper confidence bound of the 95th percentile from order statistics (the smallest rank k with P(Bin(n, 0.95) <= k - 1) >= 0.975). Confirmatory family {H6a, H6b}, Holm over 2. Descriptive cost comparison with B3 and B7 (LLM calls per PR).
- **Power (arithmetic).** The upper bound is the k-th order statistic: n = 100 gives k = 100 (the maximum, uninformative); n = 200 gives k = 197; n = 300 gives k = 293; n = 500 gives k = 485. So the bound is meaningful from about n = 200 and tight enough at **n = 300**; the claim is supported if the 293rd smallest of 300 latencies is below the limit.
- **Stopping/exclusions.** Stop at 300 PRs; runs with infrastructure faults unrelated to Radius (sandbox host failure) are repeated, not dropped; the repeat count is reported.

---

## 11. Ablations (EP-12) -- secondary, with BH control; no confirmatory claims

Primary reporting metric: change in test AUROC (RQ2 population) with cluster-bootstrap CI; for the calibration ablations also change in ECE.

1. Remove each factor of `q(e)`: `d` (use static only), `a_static`, `i` (independence), `f` (freshness).
2. Remove tamper findings.
3. Remove link confidence (set all links to 1).
4. Remove LLM-assisted extraction (deterministic only) and the reverse (LLM only).
5. Remove process signals (links to RQ4).
6. Mutation scope: criterion-linked symbols versus whole file (B6); mutant sampling fraction {10%, 25%, 50%, 100%}; mutation budget.
7. Sensitivity sweeps: `tau_support` in {0.4, 0.5, 0.6, 0.7, 0.8}; `cap_static` in {0.2, 0.4, 0.6}; `iota_agent` in {0.4, 0.6, 0.8}; non-explicit link cap in {0.85, 0.95, 1.0}; lambda per evidence kind; UIM criterion weights uniform versus testability-weighted.
8. Calibrator choice and calibration-split size.
9. Triage: remove the `u(h)` evidence-gap term (`../DESIGN.md` section 6.8); beta in {0, 0.5, 1, 2}.

Sweeps are run on dev only to choose settings and on test once, at the frozen setting, for reporting.

---

## 12. Power summary

| RQ | Test | Assumptions (initial guesses) | Required | Planned / minimum |
|---|---|---|---|---|
| RQ1 | CI half-width 0.05 on F1/Top-3 | p = 0.75/0.80, 4 criteria per PR, ICC 0.2, DE 1.6 | 461 / 394 criteria | 120 test PRs (about 480 criteria) |
| RQ1 | kappa CI | n = 600, p_o = 0.85, p_e = 0.5 | half-width 0.057 | reported |
| RQ2 | DeLong, Delta AUROC 0.05, Holm m = 6 | prev 0.20, AUROC 0.65 vs 0.70, r = 0.5, DE 2.0, alpha 0.0083, power 0.80 | 4,920 patches (984 positive) | about 6,600 / 5,000 min |
| RQ3 | ECE < 0.05 | Beta(1.2, 2.8) scores | N_test >= 2,000 (floor 0.0225) | 2,000 min |
| RQ3 | accepted-set error | observed 0.08, tolerance 0.03 | 400 accepted (~1,333 total at coverage 0.30) | covered by 2,000 |
| RQ4 | DeLong nested, Delta 0.03, Holm m = 2 | prev 0.20, r = 0.9, DE 1.5, alpha 0.025 | 1,530 runs (306 positive) | 1,500 min |
| RQ5-A | Wilcoxon, Delta 0.10 recall, Holm m = 6 | SD 0.30, alpha 0.0083 | 115 PRs | 150 PRs |
| RQ5-B | paired t / Wilcoxon, Delta 0.15 detection | SD of diff 0.25, dz 0.6, alpha 0.05 | 24 (t), 26 (Wilcoxon), 29 recruited | 29 recruited, 24 min |
| RQ6 | p95 upper bound | order statistic | n = 300 | 300 |

Calculations were done with the Hanley-McNeil variance approximation for AUROC and noncentral-t for the paired study; they are approximations. The harness (EP-05) must re-compute them with the real prevalence and cluster sizes read from the manifest before freeze, and the recomputed values replace this table in the frozen version (an editorial update made before the freeze, recorded in the changelog).

---

## 13. Global stopping rules

1. No optional stopping: every confirmatory analysis has a fixed N or a fixed collection rule stated above; no analysis is repeated "until significant".
2. Compute-limited truncation: sample whole clusters at random with the declared seed; never drop items after seeing outcomes.
3. A negative or null result on a confirmatory hypothesis is reported as such and the paper's claims are narrowed according to `../EVALUATION_PLAN.md` section 8.
4. If the gold-set kappa (RQ1) is below 0.60 after one revision round, RQ1 is reported as "annotation reliability insufficient" and its hypotheses are treated as unevaluable rather than tested.
5. If the label-source agreement (2.3) is so low that `L_ABS` and `L_cons` give opposite signs for the RQ2 effect, the paper reports the effect as label-dependent.

---

## 14. Deviations and amendments policy

- After the freeze, the body of this file (outside the freeze block) is immutable. Its canonical hash is recorded in `CHANGELOG.md` and any difference is a violation.
- A change is an **amendment**: appended to `CHANGELOG.md` with an ID (A1, A2, ...), date, author, exact text before/after, justification, whether any test-split result had been seen when it was made (yes/no), the RQs affected, and a chained hash (procedure in `CHANGELOG.md`).
- **Minor amendment** (clarification, typo, a data-source substitution with equal properties, a bug fix in code not affecting analysis): allowed any time; reported in the paper's appendix.
- **Major amendment** (changes a hypothesis, metric, threshold, split, exclusion rule, baseline set, or sample size): allowed only with justification; if any test-split result had been seen, the affected analyses are reported as **exploratory** in the paper and the original pre-registered result is still reported.
- **Unplanned deviations** (for example a baseline cannot be run, a dataset is unavailable, an exclusion rate exceeds 15%) are logged as deviations with the same fields, whether or not they require an amendment, and listed in the paper.
- Analyses not in this file are labelled exploratory and cannot support the headline claims.

---

## 15. Threats to validity

- **Construct.** `L_ABS` and the other labels come from augmented tests that may themselves be wrong, and from the same family of methods (mutation-driven strengthening) as one of our features, so label and feature are partly coupled (our `d_mut` and SWE-ABS's adversarial mutants). Mitigations: at least two label sources, manual audit `L_audit`, mutation engine and operators different from SWE-ABS's where feasible, report on labels where the coupling is weakest, bias-bound analysis. Mutants are an imperfect proxy for real faults (`Just2014`, `Andrews2005`); coverage is not strongly correlated with effectiveness (`Inozemtseva2014`), which is why B1 is a baseline rather than a feature of interest.
- **Internal.** Tuning leakage (dev only, test once), implementation bugs in re-implemented baselines (validated on toy cases in EP-06), LLM drift (pinned versions, cached), annotator bias (blinding, adjudication), order and learning effects in the user study (counterbalancing).
- **External.** Python-first; SWE-bench tasks versus real PRs; few repositories in SWE-bench Verified; agent distribution drifts quickly; trajectory data from few agents; the user-study sample (developers recruited by convenience) and seeded defects differ from natural defects.
- **Conclusion.** Underpowered subgroups; clustered data handled by cluster-robust methods but with an assumed design effect; right-censored outcomes; exchangeability for conformal guarantees is violated by shift; the ECE noise floor depends on the score distribution.
- **Novelty.** Related tools and papers are fast-moving; the EP-01 search was not systematic. Re-run the queries in `../literature/README.md` before submission and before freeze.
- **Researcher degrees of freedom.** The same authors build Radius and the baselines; baselines re-implemented from READMEs may be weaker than the originals. Mitigation: tuning budget parity, publish code, invite maintainers' checks where possible.

---

## 16. Pre-freeze checklist (all must be true before the owner freezes)

- [ ] EP-01 merged and the baseline numbering reconciled between `../EVALUATION_PLAN.md` section 4 and `../literature/novelty-assessment.md`.
- [ ] Dataset manifests assembled (EP-03): SWE-bench Verified instances with dates and repos, public agent patches with licences checked, SWE-ABS artifacts downloaded and hashes recorded, UTBoost/PatchDiff artifacts requested (or declared unavailable).
- [ ] Manifest facts re-measured: number of patches, positives, instances, repos, agents per instance; power table recomputed with them (section 12).
- [ ] Split cut points computed from the manifest and recorded (2.2).
- [ ] Gold set annotation guidelines written; pilot kappa measured >= 0.60 on the 30-PR pilot (EP-04); the gold test set size reached (>= 120 test PRs).
- [ ] Label agreement between sources measured on the overlap; manual audit sample `L_audit` drawn.
- [ ] Baselines B0 to B12 implemented and validated, or listed as not run with a reason (EP-06); licence decisions for B4, B9 recorded.
- [ ] Experiment harness (EP-05) can emit `algo_version`, seed, commit, manifest hash; the feature-provenance test (no gold at inference) passes.
- [ ] Verdict/score `algo_version` for the frozen pipeline tagged; tuning on dev closed and logged ("tuning closed" entry).
- [ ] Conformal loss formulation checked by the CA-05 implementer (7.1).
- [ ] ECE floor recomputed with the real dev score distribution (7.5).
- [ ] User-study materials ready: seeded-defect PR sets validated, interface with and without triage, rater rubric, questionnaire, recruitment plan and deadline; ethics approval or documented exemption; consent form.
- [ ] Hardware/sandbox configuration for RQ6 declared.
- [ ] Compute budget declared (determines whether the RQ2 minimum of 5,000 patches is reachable).
- [ ] Pre-freeze pilots listed in `CHANGELOG.md`; confirmation that no test-split labels or results have been viewed.
- [x] Owner decisions in section 17 answered and the answers written into this file (v0.2-draft, by delegation; the owner may veto before the freeze).
- [ ] Hash computed per `CHANGELOG.md`, the freeze block filled in, the git tag created, and the file deposited externally (decision 17.10).

### Status of the checklist at version 0.2-draft (2026-11-02)

Resolved in v0.2: the owner-decision item (section 17, answered by delegation, DEC-025) and the licence decisions for B4 and B9 as far as they concern Radius itself (DEC-018: no code from AGPL or unlicensed tools is copied; Mutahunter-style tools may only be run as separate processes). Everything else below is **still open**, which is why this document is not frozen:

| Prerequisite | State |
|---|---|
| Dataset manifests assembled (EP-03); SWE-ABS artifacts downloaded and hashed; public agent patches with licences checked | Manifests exist (`../datasets/INVENTORY.md`); patches from `swe-bench/experiments` not yet pinned; UTBoost, PatchDiff, SWE-Bench+, SWE-Mutation blocked pending author replies (`../datasets/AUTHOR_REQUESTS.md`, drafts not sent) |
| Manifest facts re-measured; power table (section 12) recomputed; split cut points computed | Not done. Section 12 still uses literature numbers |
| Gold set: guidelines, pilot kappa >= 0.60 on 30 PRs, >= 120 test PRs | Not done. No kappa has been measured |
| Label agreement between sources; `L_audit` drawn | Not done (needs two sources) |
| Baselines B0 to B12 implemented and validated | Not done |
| Harness emits `algo_version`, seed, commit, manifest hash; feature-provenance test passes | Not done |
| Pilot runs (timing, per-patch mutation cost, RQ1 pilot) | Not done. Needed to fix the RQ2 compute budget (17.3) |
| Frozen-pipeline `algo_version` tagged; tuning closed and logged | Not done |
| CA-05 conformal loss check; ECE floor with real dev scores | Not done |
| User-study materials, ethics determination, consent form, recruitment plan | Not done |
| RQ6 hardware declared | Not done |
| Pre-freeze pilots listed; confirmation no test-split result viewed | Nothing viewed or run (changelog section 4 is empty) |
| Freeze: hash, freeze block, signed tag, external deposit | **Owner act only.** Not done. Commands in 17.10 |

---

## 17. Decisions the owner must make before freezing (resolved by delegation, 2026-11-02; DEC-025)

The owner delegated these as "take the ideal decisions". Each answer is a recorded choice with its reason; the owner can veto any of them before the freeze, and nothing here is a result.

1. **Primary label: `L_ABS` is the headline.** `L_cons` (incorrect under at least two sources) and `L_union` are sensitivity analyses, not the headline, because the second source (UTBoost, PatchDiff) is not available yet and a headline that depends on an unobtained artifact cannot be frozen. If the SWE-ABS artifacts turn out to be unusable, the pre-registration is not frozen and is redrafted (it is not switched silently). The robustness rule in 2.6 stays: the sign of the effect must agree on `L_cons` where it exists.
2. **Primary predictor for RQ2: UIM as proposed (single pre-specified score).** A fitted combination adds degrees of freedom, hides what is being tested, and is the version most likely to overfit; it stays the secondary predictor in 6.1. This keeps claim C2 interpretable.
3. **Compute budget for RQ2: target N = 5,000 patches (the stated minimum); the budget is fixed from a pilot, not guessed.** Rules: (a) sample at most 50 mutants per patch (fixed seeds), with a per-patch wall-clock cap of 20 minutes; (b) a timing pilot on 100 dev-split patches measures the median and 95th percentile cost, and the total budget is declared as N x median cost, written into this file before freeze (the figure is therefore blank in v0.2 and is a freeze prerequisite); (c) if the declared budget does not reach 5,000 patches, reduce mutants per patch (floor 20) before reducing N, because N drives power while mutant count only adds measurement noise; (d) if still short, sample whole task-instance clusters at random with the declared seed (rule 13.2) and label RQ2 underpowered with the achieved minimum detectable difference; never drop patches after seeing outcomes. Mutation-testing tools whose licence conflicts with DEC-018 are not linked into Radius.
4. **alpha = 0.10 and tolerance 0.03 are kept.** With a base rate of incorrect-but-passing patches of about 0.20, accepting only sets whose error is at most 0.10 halves the error of unfiltered acceptance, which is a meaningful reviewer-facing guarantee, and the 0.30 coverage floor stops a vacuous result. A stricter alpha = 0.05 is reported as a secondary operating point (BH family), not confirmatory. Which error rate a real user accepts is a product question for the design-partner phase and does not change this scientific choice.
5. **User-study primary outcome: fixed-time-cap detection rate (as proposed).** Cap 20 minutes per PR, 4 seeded defects per PR, 4 PRs per participant. Defects per minute and time to first defect are secondary. A fixed cap prevents trading accuracy for speed and keeps one primary comparison with no multiplicity.
6. **Ethics route: ask the owner's institution for a written determination (exempt, minimal-risk) before any recruitment; written consent in all cases.** Partner data is not part of any confirmatory analysis (item 9), so it needs no ethics route for the pre-registered claims; any partner-data work follows DEC-020. Recruitment channel and deadline: developer volunteers via the owner's institution and open-source communities, with a deadline fixed at freeze (**owner to configure** the institution, the recruiter contact and the date). The study does not start until the determination is on file.
7. **RQ4 data: at least 4 agent configurations that we run ourselves, built from open-source scaffolds crossed with at least 2 models** (for example mini-swe-agent, which the SWE-ABS repository bundles under MIT, and OpenHands, which AgentLens used), keeping full traces. The final list is fixed after the compute pilot and written here before freeze. Proprietary agents with partial traces are excluded from the primary analysis; they may appear in the exploratory partial-trace stratum (8.2) only.
8. **Multiplicity: Holm within each RQ's confirmatory family (as proposed).** RQs are separate claims; a single family across all RQs would sacrifice power in RQ2 to guard against a combination nobody claims. The paper states this.
9. **Outcome horizon 90 days; partner-data results are exploratory only, never confirmatory.** Revert and follow-up-fix labels mature slowly; 90 days is the stated initial guess and 180 days is run as a sensitivity analysis. Partner data would be small and consent-limited (DEC-020), so it cannot carry a confirmatory claim.
10. **External deposit: two layers, both required, key holder = owner ("owner to configure").** (a) A signed git tag `prereg-v<version>` on the freeze commit. (b) An immutable archive with a DOI: a Zenodo deposit of the tagged archive (or an OSF Registration of `PREREGISTRATION.md` and `CHANGELOG.md`; either gives a timestamp independent of GitHub). Record the tag object, the SHA-256 and the DOI in the freeze block and in `CHANGELOG.md`. The agent does not create keys, tags or deposits. Exact commands for the owner (run in the repository root, after filling the freeze block and committing):

    ```
    # one-time: create a signing key (GPG) and tell git to use it
    gpg --full-generate-key
    gpg --list-secret-keys --keyid-format=long          # note the key id
    git config user.signingkey <KEYID>
    #   alternative, SSH signing:
    #   git config gpg.format ssh
    #   git config user.signingkey ~/.ssh/id_ed25519.pub
    # recompute and compare the canonical hash (must equal the freeze block and CHANGELOG)
    cd docs/research/preregistration
    tr -d '\r' < PREREGISTRATION.md | sed '/<!-- FREEZE-BLOCK-START -->/,/<!-- FREEZE-BLOCK-END -->/d' | sha256sum
    cd ../../..
    # signed tag, verify it, then publish it
    git tag -s prereg-v1.0 -m "Radius pre-registration v1.0 (frozen)"
    git tag -v prereg-v1.0
    git push origin prereg-v1.0
    # archive plus checksum plus detached signature for the external deposit
    git archive --format=tar.gz -o prereg-v1.0.tar.gz prereg-v1.0
    sha256sum prereg-v1.0.tar.gz > prereg-v1.0.tar.gz.sha256
    gpg --armor --detach-sign prereg-v1.0.tar.gz
    # upload prereg-v1.0.tar.gz (+ .sha256, .asc) to Zenodo or OSF, publish, copy the DOI into the freeze block
    ```

    Extra artifacts to deposit with it: `CHANGELOG.md`, the dataset manifests (`benchmarks/datasets/manifests/*.json`) with their hashes, the split cut-point file computed from the manifest, the feature-provenance test, the `algo_version` tag and commit hash, the "tuning closed" log entry, the analysis scripts at the tagged commit, and the public key. (The tag signature proves the owner made the commitment at that commit; the external DOI proves when.)
11. **Artifacts that appear before the freeze (AgentLens-Bench, UTBoost, PatchDiff, SWE-Bench+):** added by a logged draft revision (v0.3-draft and so on, recorded in `CHANGELOG.md` section 2), as secondary label sources or an external check, never as the headline. After the freeze they enter only as amendments under section 14 (a minor amendment if added as an extra secondary source, a major one if they would change a hypothesis or the primary label). Any artifact obtained must have its licence recorded in the inventory first (DEC-020).

---

## 18. References (BibTeX keys in `../literature/references.bib`)

`Antoniol2002`, `Lin2021`, `Fuchss2025`, `Altunhan2026`, `Inozemtseva2014`, `Just2014`, `Andrews2005`, `Papadakis2019`, `Jimenez2024`, `Aleithan2024`, `Yu2025utboost`, `Wang2026patchdiff`, `Yu2026sweabs`, `Mundler2024`, `Raghavendra2026`, `Zhong2025`, `Sun2026swemutation`, `Li2026aidev`, `Zhang2026ccrab`, `AgentProofRengGyu`, `AgentProofGenRamzi`, `ScopeProof`, `Verik`, `SlopGate`, `PRAgent`, `Mutahunter`, `Platt1999`, `NiculescuMizil2005`, `Guo2017`, `ElYaniv2010`, `Geifman2017`, `Angelopoulos2024crc`, `Angelopoulos2021ltt`, `Shahini2024`, `Sahoo2026`, `Majgaonkar2025`, `Kamei2013`, `Pornprasit2021`, `Zheng2023`, `Moon2026`, `Jin2025`, `Zhao2026`.

Statistical methods named without a bibliography entry (DeLong, McNemar, Wilcoxon, Holm-Bonferroni, Benjamini-Hochberg, Hanley-McNeil, Clopper-Pearson, Cohen's kappa) are standard and are cited in the paper from their original sources once added to `references.bib` (EP-14); they are not cited here to respect the rule of citing only verified bib entries.
