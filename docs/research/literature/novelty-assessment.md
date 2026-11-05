# Novelty Assessment (EP-01)

Date: 2026-11-02. Basis: `related-work.md` (tags P/S as defined in `README.md`). All statements are of the form "we did not find"; the search was not systematic (US-only web index, no citation-graph crawl). Re-run before submission.

## Summary verdict

| # | Claim (`EVALUATION_PLAN.md` section 1) | Status after review | Recommended action |
|---|---|---|---|
| 1 | Criterion-level, intent-to-evidence view finds unproven behavior that CI and coverage miss | **Partly covered as an idea; open as an empirical result.** Criteria-to-evidence checking exists in at least two open tools and in the traceability literature | Narrow to "unproven *relative to fault-detecting evidence*" and make the empirical comparison the contribution |
| 2 | Evidence weighted by fault-detection ability separates plausible-but-incorrect patches from correct ones better than pass rate, coverage, LLM judge | **Mechanism partly covered (SWE-ABS); the PR-time predictive use is open** | Position against SWE-ABS/UTBoost/PatchDiff explicitly; evaluate as a *predictor without gold patch* |
| 3 | Trust probability is calibrated; conformal abstention controls error among accepted PRs | **Method not new; application not found.** Precedents exist in SE (JIT conformal) and for agents (CORA) | Frame as a careful evaluation of risk control under shift, not as a new method |
| 4 | Process signals add predictive value beyond final output | **Process-aware evaluation exists (AgentLens, TrajEval); prediction of correctness from process, with incremental value, not found** | Keep, but narrow to incremental AUROC/ECE and be explicit about the AgentLens label difference |
| 5 | Risk-ranked triage lets humans find more defects in less time | **Components are well established (JIT, line-level ranking); the agent-PR user study is not found** | Narrow to evidence-aware ranking vs strong JIT and LLM-reviewer baselines; the user study is the contribution |

The unmodified headline sentence in `DESIGN.md` ("nobody we found") cannot be kept as a blanket statement: AgentProof (RengGyu), ScopeProof and SWE-ABS each cover part of it. What survives is the **combination**: criterion-linked evidence + fault-detection-weighted strength + calibrated abstention, evaluated against ground-truth labels at PR time with no gold patch.

---

## Claim 1: criterion-level intent-to-evidence view

**What exists**
- Requirements-to-code/test traceability is a mature field: IR links (Antoniol 2002), BERT links for issue-commit (T-BERT, ICSE 2021), RAG/LLM links (LiSSA, ICSE 2025). All stop at *linking*; none judge whether the linked artifacts would detect a failure.
- PR-issue alignment classifiers exist (Altunhan et al., arXiv 2026): coarse, PR-level.
- Tools: **AgentProof (RengGyu)** maps issue to acceptance criteria and marks a criterion "met" only with linked passing execution evidence, using GitHub check metadata; deterministic; generates a re-prompt. **ScopeProof** maps reviewer-confirmed criteria to implementation and test candidates with evidence levels E0-E4, static only. **GenRamzi/AgentProof** does base/head re-runs with fail-to-pass proof tests and integrity rules. **Proofrail** and **Workproof** check agent completion claims against commits/receipts (search-result level).
- Reproduction-test generation (SWT-Bench, TDD-Bench in search results) uses the issue as intent and a fail-to-pass test as evidence; precision of SWE-Agent doubled with such tests as a filter (SWT-Bench abstract).

**What is genuinely new (as far as found)**
- Treating a *passing test as insufficient evidence* unless it would have failed under plausible faults in the linked symbols (B4 tools stop at "a passing check exists").
- Per-criterion evidence strength that combines link confidence, independence and fault sensitivity, and a deterministic verdict.
- An empirical test of whether this separates cases CI misses, with ground-truth labels.

**How to narrow**
- Do not claim "criteria-to-evidence mapping" as novel. Claim: "evidence-strength-aware criterion support", with the criteria view as the interface.
- Phrase RQ2/H2 against B4 explicitly: same criteria, different evidence model.

**Baselines to add to EP-06**
- B4a: AgentProof (RengGyu) rules re-implemented from its README (its license is unconfirmed; do not copy code, see `tasks/EV-evidence-quality.md`).
- B4b: ScopeProof-style static candidate retrieval (evaluation-only license; re-implement ideas only).
- B8: Fail-to-pass reproduction-test filter (SWT-Bench style) as an intent-based evidence baseline.
- For RQ1 linking: VSM/BM25 (IR), T-BERT-style, LiSSA-style RAG linking, and the PR-issue alignment classifier.

---

## Claim 2: fault-detection-weighted evidence separates plausible-but-incorrect patches

**What exists**
- Weak tests inflate agent scores: SWE-Bench+ (31.08% of passed patches suspicious due to weak tests, abstract), UTBoost (345 erroneous patches labelled passed; 36 instances), PatchDiff (29.6% of plausible patches behave differently from gold; 7.8% pass while failing developer tests; 6.2 points inflation), SWE-ABS (19.78% of previously passing patches rejected; top agent 78.80% -> 62.20%), SWE-Proof (about a quarter of test-passing patches admit counterexamples).
- **SWE-ABS is the closest prior work**: mutation-driven adversarial testing generates plausible-but-wrong mutant patches and writes tests that reject them. It already shows that mutation-style reasoning exposes weak test evidence, at benchmark scale, with released code (MIT) and data.
- Coverage vs effectiveness (Inozemtseva & Holmes 2014), mutants vs real faults (Just et al. 2014; Andrews et al. 2005), pseudo-tested methods (Niedermayr et al. 2016), LLM-test generation guided by mutants (Meta ACH 2025, MutGen 2025).
- Execution-free verifiers (Agentic Rubrics, arXiv 2601.04171) and LLM judges (with documented biases: Zheng et al. 2023, Moon et al. 2026, Jin & Chen 2025, Zhao et al. 2026).

**What is genuinely new**
- SWE-ABS, UTBoost and PatchDiff *create better labels* using the gold patch or LLM-generated tests at benchmark time. None *scores a single PR at review time without the gold patch* and evaluates how well that score predicts the labels (AUROC, recall at fixed FPR). That predictive use, plus the comparison to coverage, LLM-as-judge and Radius v1, is the open part.
- Mutation scoped to criterion-linked changed symbols (cheaper than whole-file; baseline B6 tests exactly this).

**Threat:** high for the sentence "mutation exposes weak evidence for agent patches" (SWE-ABS owns it); partial for the PR-level predictive claim.

**How to narrow**
- Reword the claim: "A deployable, gold-free evidence-strength score predicts which test-passing patches are incorrect, and does so better than pass rate, coverage and LLM judges."
- Cite SWE-ABS/UTBoost/PatchDiff as label sources and as upper-bound analyses; do not present mutation-for-benchmark-strengthening as ours.
- Be explicit about the validity limit of mutants as a proxy (Just et al. 2014: not all real faults are coupled; summary-level, verify before quoting a number).

**Baselines/datasets to add to EP-06 / EP-03**
- Label sources: SWE-ABS strengthened suites (MIT repo, Hugging Face datasets), UTBoost augmented tests (artifact not located on the arXiv page; ask authors), PatchDiff (no artifact link located). Use at least two label sources and a manual audit (CA-09); SWE-ABS reports UTBoost strengthened only 10/500 instances, so labels from different sources will disagree.
- B9: execution-free rubric verifier (Agentic Rubrics style) as a stronger "LLM" baseline than a plain judge.
- B10: SWT-Bench-style reproduction-test pass as a verifier.
- B11: "SWE-ABS-as-oracle" upper bound (not a deployable baseline; shows the ceiling).
- Datasets: SWE-Bench+ (leakage-filtered), SWE-Mutation (mutant source), ImpossibleBench (tamper ground truth), EvalPlus (non-SWE sanity check).

---

## Claim 3: calibration and conformal abstention

**What exists**
- Calibration: Platt (1999/2000), Niculescu-Mizil & Caruana (2005), Guo et al. (2017) for ECE and temperature scaling. In SE: Spiess et al. (ICSE 2025) calibrate code LMs with Platt scaling and note that it needs correctness data.
- Conformal/risk control: Conformal Risk Control (ICLR 2024), Learn then Test (2021). Selective classification (El-Yaniv & Wiener 2010; Geifman & El-Yaniv 2017).
- In SE: **Shahini et al. (MSR 2024)** apply conformal prediction to JIT defect prediction and find the 95% guarantee covered only about 27% (DeepJIT) and 9% (CC2Vec) of predictions: an honest warning that guarantees may be vacuous in practice. RisCoSet (2026) controls risk in code generation via prediction sets. CORA (2026) applies conformal risk control to execute/abstain for GUI agents.

**What is genuinely new**
- Applying calibrated trust + conformal risk control to *PR acceptance* with an error-rate-among-accepted guarantee. I did not find this combination. This is application novelty, not method novelty.

**Threat:** partial (technique and precedents exist). Main risk is not priority but **validity**: exchangeability across repos, agents and time is doubtful (agents drift), so the guarantee is conditional; Shahini et al. suggest low effective coverage.

**How to narrow**
- Claim "evaluation of calibration and of conformal risk control for PR verification under time and repo shift", report coverage (not just risk), and state the exchangeability assumption and how splits break it.
- Do not claim a new calibration or conformal method.

**Baselines to add (EP-09)**
- Uncalibrated score; Platt; isotonic (watch overfitting on small data, per Niculescu-Mizil & Caruana); temperature scaling; naive threshold; selective classification with a held-out threshold (Geifman & El-Yaniv); Learn-then-Test as the non-monotone alternative; Spiess-style Platt on confidence.

---

## Claim 4: process signals add predictive value

**What exists**
- **AgentLens** (arXiv 2605.12925): from 2,614 OpenHands trajectories on 60 SWE-bench Verified tasks (8 backends), 47 tasks with enough passing runs; 10.7% of passing trajectories in the 1,815-trajectory subset are "Lucky Passes", range 0.5%-23.2% across backends; ranking by process quality shifts some models by up to five positions. Code and data not yet released (per v4 page). Method needs other passing runs of the *same task* as reference.
- Majgaonkar et al. (2025): failed trajectories longer and more variable; Kim et al. (2026, TrajEval): 16,758 trajectories, 60-69% of failures edit the right function yet fail ("Coherence Collapse"); ImpossibleBench (2025): measures test exploitation.
- No application of classical process mining (conformance checking) to coding-agent logs found.

**Correction to repo text.** `tasks/PR-process-verification.md` says AgentLens reports "a noticeable share of passing agent runs reach correct patches through weak processes". Verified: the figure is 10.7% overall, 0.5%-23.2% by backend, on a 1,815-trajectory subset from 47 tasks, OpenHands only. Cite with these qualifiers.

**What is genuinely new**
- Using process features, available *without reference runs or gold patches*, to predict patch incorrectness and to improve calibration, with a pre-registered incremental test (AUROC/ECE vs outcome-only features). AgentLens measures process quality of runs that already passed and defines "Lucky" on correct patches; it does not claim process predicts correctness.

**Threat:** partial. Reviewers will ask how this differs from AgentLens.

**How to narrow**
- Claim 4 as "process signals computable at PR time add predictive value", not "process quality matters" (AgentLens shows that).
- Data caution: all published trajectory studies use OpenHands/SWE-agent on SWE-bench; the PR-time setting with proprietary agents (Claude Code, Codex, Cursor) may only yield partial traces.

**Baselines (EP-10)**
- Outcome-only features (test pass, size, coverage); trajectory length/variance features (Majgaonkar); AgentLens-style tiers if the code is released (re-implement from the paper otherwise; needs same-task references); TrajEval-style stage features (requires reference patches, so use only as analysis).

---

## Claim 5: risk-ranked review triage

**What exists**
- JIT defect prediction: Kamei et al. (TSE 2013, effort-aware), JITLine (MSR 2021, commit-level plus defective lines, replication package on Zenodo). Review-request prioritization (Pineapple, GPP: pointers only, metadata not verified). LLM review agents and benchmarks: PR-Agent (MIT), CodeRabbit, c-CRAB (existing agents solve around 40% of tasks, abstract), CR-Bench (signal-to-noise trade-off). AIDev gives 932,791 agent PRs (a search summary says the curated subset includes reviews; not confirmed on the arXiv page).
- I found no study of hunk-level, evidence-aware ranking for *agent-written* PRs, nor a controlled user study of it.

**What is genuinely new**
- Ranking hunks by *evidence-gap risk* (unproven criteria, surviving mutants, tamper) rather than by defect-proneness or LLM opinion, and a seeded-defect user study.

**Threat:** partial. A reviewer may say "this is JIT defect prediction plus LLM review". The differentiator must be shown empirically.

**How to narrow**
- Report hit-rate@k vs size-ordered, random, effort-aware JIT (Kamei/JITLine), and LLM-reviewer rankings; the human study is the main contribution. Do not claim time savings without the study.

**Baselines (EP-11)**
- Random; by-size; by-churn; Kamei-style logistic effort-aware; JITLine; LLM reviewer (PR-Agent, c-CRAB protocol); human-only control.

---

## Cross-cutting threats to novelty

1. **Fast-moving tools.** There are at least five repositories with the name AgentProof; the one matching our competitor row is RengGyu/AgentProof (0 stars, no LICENSE seen). GenRamzi/AgentProof lists "targeted mutation proof" on its roadmap. Re-check both before submission.
2. **SWE-ABS (ICML 2026, same group as UTBoost) is the paper reviewers will compare against.** Address it in the introduction.
3. **Vendors** (TestSprite, others) may add intent tracing; their results are company-reported only.
4. **Label validity** (construct threat): labels come from the same family of methods (augmented tests) we compare against; use multiple label sources and manual audit.

## Gaps that are real (candidate contributions)

1. A gold-free, PR-time evidence-strength predictor evaluated against ground-truth labels (not yet found).
2. Calibrated abstention with an explicit risk guarantee for PR acceptance, evaluated under shift (not yet found).
3. Process features that predict patch incorrectness incrementally (not yet found; AgentLens is adjacent).
4. Evidence-aware hunk ranking with a user study on agent PRs (not yet found).
5. Open benchmark/harness combining the above, joining criteria annotations to agent PRs (AIDev has no criteria; SWE-ABS has no intent annotations).
