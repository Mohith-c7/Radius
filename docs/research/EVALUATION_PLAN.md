# Evaluation and Paper Plan (Research Track)

**Status:** Proposed. Date: 2026-11-02.
Goal: produce results that a reviewer would believe. Everything here runs through the **production pipeline** (EP-05) so the paper and the product cannot drift apart.

---

## 1. Claims we want to be able to make (only if the data supports them)

1. A criterion-level view of PR evidence (intent-to-evidence traceability) identifies unproven behavior that pass/fail CI and coverage miss.
2. Weighting evidence by its ability to detect faults (mutation-based and static proxies) separates plausible-but-incorrect patches from correct ones better than pass rate, coverage, or an LLM-as-judge baseline.
3. The resulting trust probability is calibrated, and conformal abstention controls the error rate among accepted PRs.
4. Process signals from agent trajectories add predictive value beyond the final output.
5. Risk-ranked review triage lets humans find more defects in less time.

If a claim fails, report it honestly and narrow the paper's contribution (the plan in section 8 supports this).

## 2. Research questions and hypotheses

| RQ | Question | Hypothesis (H) | Primary metric |
|---|---|---|---|
| RQ1 | Can criteria be extracted and linked to code/tests accurately enough to be useful? | H1: deterministic+LLM-assisted extraction reaches F1 >= 0.75 on well-specified PRs; links reach Top-3 accuracy >= 0.8 | P/R/F1, MRR, Top-k, human acceptance rate |
| RQ2 | Does evidence-quality weighting detect weak verification better than baselines? | H2: AUROC of `S`/UIM for "patch is incorrect despite passing tests" exceeds CI-pass, coverage, and Radius v1 | AUROC, PR-AUC, recall at fixed FPR |
| RQ3 | Is the trust probability calibrated, and does conformal abstention control risk? | H3: ECE < 0.05 on held-out data; accepted-set error <= alpha (+/- CI) | ECE, Brier, risk-coverage curve |
| RQ4 | Do process signals add predictive power? | H4: adding signals improves AUROC/ECE over outcome-only features | AUROC delta, ablation |
| RQ5 | Does triage help reviewers? | H5: top 20% risk-ranked hunks contain >= 60% of seeded/true defect hunks; users find more defects per minute with triage | hit rate at k, time, detection rate |
| RQ6 (overhead) | Is the cost acceptable? | H6: cheap verdict < 2 min p95; mutation adds < 15 min p95 within budget | latency, cost per PR |

Hypothesis thresholds above are *initial guesses* and are fixed in the pre-registration (EP-02) before running the experiments. The pre-registration draft (`preregistration/PREREGISTRATION.md`, not frozen) restates the claims after EP-01 (claim 2 as a gold-free PR-time predictor, claim 1 as evidence-strength-aware support, claims 3 and 5 as evaluation contributions, claim 4 with the AgentLens qualifiers) and refines the metrics, splits and sample sizes; where it differs from this table, the pre-registration governs once frozen.

## 3. Datasets (EP-03)

| Dataset | Use | Notes |
|---|---|---|
| SWE-bench Verified/Lite instances with agent patches | RQ2, RQ3 | Official tests pass for some wrong patches; analyses exist (UTBoost, PatchDiff, SWE-ABS). Numbers below were checked on the primary arXiv pages on 2026-11-02 (EP-01): UTBoost (arXiv 2506.09289, ACL 2025): 36 instances with insufficient tests, 345 erroneous patches labelled passed, 40.9% of Lite and 24.4% of Verified leaderboard entries affected. PatchDiff (arXiv 2503.15223, ICSE 2026): 3 tools on SWE-bench Verified, 29.6% of plausible patches behave differently from gold, 28.6% of those certainly incorrect, 7.8% pass while failing the developer tests, 6.2 points inflation. SWE-ABS (arXiv 2603.00520, ICML 2026 listing not fetched): 251/500 Verified instances strengthened (UTBoost: 10), 2,184 of 11,041 passing patches rejected (19.78%; some summaries say 19.71%), top agent 78.80% -> 62.20% in v1 (an ICML listing reportedly says 61.80%; cite arXiv v1). Licenses: SWE-ABS code MIT (github.com/OpenAgentEval/SWE-ABS); UTBoost and PatchDiff: no artifact link found on the arXiv pages, license unknown. Details: `literature/related-work.md`. |
| UTBoost / PatchDiff / SWE-ABS augmented tests and labels | Ground truth for "plausible but incorrect" | Use released artifacts where they exist (SWE-ABS: yes, MIT, plus Hugging Face datasets; UTBoost and PatchDiff: not located, contact authors). Use at least two label sources and audit disagreements (SWE-ABS reports UTBoost strengthened only 10 of 500 instances, so sources will disagree). Re-run their validation where feasible. |
| SWE-Bench+ (arXiv 2410.06992), SWT-Bench (2406.12952), SWE-Mutation (2605.22175), ImpossibleBench (2510.20270) | Leakage-filtered tasks; issue reproduction tests; mutant source; tamper ground truth | Added by EP-01. Check licenses at download time; SWT-Bench and ImpossibleBench have public repositories, SWE-Bench+ and SWE-Mutation: no repository link found on the arXiv pages. |
| AIDev (arXiv 2602.09185): 932,791 agent-authored PRs from 5 agents, curated subset 33,596 PRs from 2,807 repos with > 100 stars | Candidate public corpus for CA-01 and RQ4 | Added by EP-01. No criteria annotations; license and exact fields not verified; check before use. |
| AgentLens-Bench (arXiv 2605.12925) | Trajectory reference for RQ4 | Not released as of arXiv v4 (2026-10-05). Do not plan on it; re-check. |
| Radius mutation benchmark (P3) in `benchmarks/` and `docs/benchmarks/` | Controlled ground truth with seeded faults | Extend with intent annotations (criteria). |
| Gold intent/link annotations (IN-09, LK-07) | RQ1 | >= 150 PRs, two annotators, kappa reported. |
| Real PR corpus with outcomes (CA-01) | RQ3, RQ4 | From design partners (consented) and public OSS with agent-authored PRs; labels from reverts/follow-up fixes/incidents; right-censoring handled. |
| Seeded-defect review tasks | RQ5 | Created from fixtures; humans find defects with/without triage. |
| Agent trajectories | RQ4 | From our own runs of several agents on benchmark tasks (log everything via PR-01), plus partner data. |

Data hygiene: time-based and repo-based splits; deduplicate; no leakage of labels into features; document licenses; store hashes; release what is permitted.

## 4. Baselines (EP-06)

- B0: CI pass/fail only.
- B1: line/branch coverage of changed lines.
- B2: Radius v1 heuristic score.
- B3: LLM-as-judge on the diff + issue (strong model, fixed prompt, multiple seeds).
- B4: AgentProof-style criterion mapping with "passing test exists" evidence (re-implemented or run as-is if license permits).
- B5: Verik/SlopGate-style tamper rules only.
- B6: Mutation score of the whole file without intent linking.
- Added by EP-01 (see `literature/novelty-assessment.md`):
  - B7: execution-free rubric verifier (Agentic Rubrics style, arXiv 2601.04171) as a stronger LLM baseline than a plain judge.
  - B8: fail-to-pass reproduction-test verifier (SWT-Bench style, arXiv 2406.12952).
  - B9: ScopeProof-style static criterion-to-candidate retrieval (re-implement ideas only; its license is evaluation-only).
  - B10 (RQ1 linking): BM25/VSM, T-BERT-style and LiSSA-style RAG linking, PR-issue alignment classifier.
  - B11 (RQ3): Platt, isotonic, temperature scaling, selective classification with held-out threshold, Learn-then-Test.
  - B12 (RQ5): random, by-size, effort-aware JIT (Kamei-style), JITLine, LLM reviewer (PR-Agent; c-CRAB protocol).
  - Upper bound (not deployable): SWE-ABS-style strengthened tests as oracle.
- B4 note: "AgentProof" is ambiguous (at least five unrelated GitHub projects). The one matching B4 is github.com/RengGyu/AgentProof (no LICENSE file seen; re-implement from its README, do not copy). github.com/GenRamzi/AgentProof (Apache-2.0) is a different tool (BASE/HEAD re-runs, proof tests, integrity rules).

Fair comparison: same inputs, same splits, tuned with the same budget, report seeds and variance.

## 5. Experiments

| ID | Task | Needs |
|---|---|---|
| EP-01 [x] DONE 2026-11-02 (outputs in `literature/`) | Literature review (traceability, mutation testing for AI code, PR verification tools, calibration/conformal, process mining of agents). Confirm or narrow the novelty claim. Maintain a reading list and a table of related work with dates and artifacts. | none (start now) |
| EP-02 [~] DRAFT 2026-11-02 (not frozen; `preregistration/`) | Pre-registration: RQs, hypotheses, metrics, analysis plan, stopping rules, exclusion criteria. Freeze before running. | EP-01 |
| EP-03 | Dataset assembly, licensing check, splits. | F-14 |
| EP-04 | Gold annotation (IN-09, LK-07), agreement study. | EP-03 |
| EP-05 | Experiment harness that calls the production pipeline, takes a dataset manifest + config, writes results with `algo_version`, seed, commit hash. One command reproduces any table. | M3 |
| EP-06 | Baselines implemented and validated. | EP-05 |
| EP-07 | RQ1 experiments (extraction, linking). | IN-10, LK-07 |
| EP-08 | RQ2 experiments, including correlation of `a_static` vs `d_mut`. | EV-08, M4 |
| EP-09 | RQ3 experiments (calibration, conformal). | CA-05 |
| EP-10 | RQ4 experiments (PR-10). | PR-06 |
| EP-11 | RQ5 (replay + user study; TR-05). | TR-03 |
| EP-12 | Ablations: remove each of `d`, `i`, `f`, tamper, link confidence, LLM extraction, process signals; vary `tau_support`, `lambda`, caps; sensitivity plots. | all |
| EP-13 | Threats to validity and error analysis (manual review of 100 failures/false alarms). | EP-07..11 |
| EP-14 | Paper writing, figures, artifact packaging (Docker image, datasets, scripts, README to reproduce within hours), preprint. | EP-12, EP-13 |

## 6. Statistics

- Report effect sizes with bootstrap 95% CIs (>= 1000 resamples); paired tests (McNemar for classification disagreements, Wilcoxon for continuous paired metrics); multiple-comparison correction where several hypotheses are tested.
- Calibration: ECE with fixed and adaptive bins, reliability curves, Brier decomposition.
- Report variance over seeds for stochastic parts (mutant sampling, LLM temperature if non-zero, embeddings).
- Sample-size reasoning for the user study (power analysis) documented in EP-02.

## 7. Threats to validity (to address explicitly in the paper)

- **Construct:** "incorrect patch" labels come from augmented tests that may themselves be wrong; use multiple label sources and manual audit (CA-09).
- **Internal:** parameter tuning leakage; fix by tuning on a dev split only.
- **External:** Python-first; benchmark tasks vs real PRs; agent distribution drifts quickly.
- **Conclusion:** small partner sample; right-censored outcomes.
- **LLM variability:** model versions change; we pin versions and cache outputs; LLMs are not on the verdict path.
- **Novelty risk:** related tools (AgentProof, Verik, SlopGate, ScopeProof) are fast-moving; re-check before submission. EP-01 found that SWE-ABS (mutation-driven adversarial test strengthening, ICML 2026) already covers the mechanism of claim 2 at benchmark time, that AgentProof/ScopeProof cover criterion-to-evidence mapping, and that AgentLens covers process-aware evaluation of passing runs; see `literature/novelty-assessment.md`.

## 8. Fallback plan if results disappoint

- If RQ1 (linking) is weak: lean on explicit intent (`.radius/intent.yml`, issue-linked tests) and publish the negative extraction result plus a human-in-the-loop design.
- If RQ2 shows no gain: report that mutation-weighted evidence is not worth the cost; the tamper/assertion-strength results may still stand.
- If RQ3 data is too small: present calibration on benchmark labels only and clearly state limits.
- In all cases, the benchmark, gold set and harness are contributions.

## 9. Paper outline (draft)

1. Introduction: the verification gap for agent-written code; contributions.
2. Background and related work (EP-01).
3. Problem formulation: intent, evidence, support, trust.
4. Approach: IEG, evidence quality, verdict, process signals, calibration, triage.
5. Implementation (Radius) and reproducibility.
6. Evaluation: RQ1-RQ6.
7. Discussion: practical findings, limits, ethics (surveillance concerns, over-trust).
8. Threats to validity. 9. Conclusion and future work.

Venue options to evaluate (check current calls and deadlines at the time): software engineering conferences (ICSE, FSE, ASE) and their new-ideas/industry tracks, MSR for the dataset angle, workshops on LLMs for code, and arXiv preprint first. Do not assume dates; verify.

## 10. Ethics and compliance

- Consent and anonymization for partner data and the user study; institutional approval if required.
- Respect licenses and terms for scraped OSS data; release hashes/IDs where redistribution is not allowed.
- Avoid framing as surveillance of developers; report aggregates; state the risk of misuse in the paper.
- Disclose AI assistance used in the research and writing according to the venue's rules.

## 11. Artifact checklist (EP-14)

- [ ] Docker image with pinned dependencies; one-command reproduction of every table and figure.
- [ ] Datasets or scripts to rebuild them; manifests with hashes.
- [ ] `algo_version` and commit hash printed in every results file.
- [ ] README with expected runtime and hardware.
- [ ] License file; citation file; DOI via a long-term archive.

## 12. Literature gaps (draft note for the related-work section; EP-01)

- Traceability research (IR, BERT, RAG links) stops at link recovery; it does not ask whether the linked tests would detect a fault in the linked code.
- Benchmark-strengthening work (UTBoost, PatchDiff, SWE-ABS, SWE-Bench+, SWE-Proof) shows that a large minority of test-passing agent patches are wrong, but uses the gold patch or LLM-generated tests at benchmark time. We found no work that predicts "plausible but incorrect" for a single PR at review time without a gold patch and evaluates calibration of that prediction.
- Conformal risk control has SE precedents (JIT defect prediction, code generation prediction sets) and agent-safety precedents, but we found none for PR acceptance with an error-rate-among-accepted guarantee; the one SE precedent reports a guarantee covering a small share of predictions.
- Process-aware agent evaluation (AgentLens, trajectory studies) evaluates runs that already pass or diagnoses failures with reference patches; we found no work that tests whether PR-time process signals improve prediction or calibration.
- Defect-prone-change ranking is mature, but we found no evidence-aware hunk ranking for agent-written PRs with a controlled user study.
- Open-source PR-verification tools exist (AgentProof, ScopeProof, Verik, SlopGate) but are unevaluated and unpeer-reviewed; a head-to-head evaluation is itself a gap.
- Limits of this note: search was not systematic; "we found no" is not "does not exist". Re-run the queries in `literature/README.md` before submission.

## Changelog

- 2026-11-02 (EP-02): added the pre-registration draft in `preregistration/` (`PREREGISTRATION.md`, `CHANGELOG.md` with the freeze mechanism); EP-02 marked DRAFT, not frozen.
- 2026-11-02 (EP-01): verified UTBoost/PatchDiff/SWE-ABS figures against arXiv pages and added them with license/artifact status; added datasets (SWE-Bench+, SWT-Bench, SWE-Mutation, ImpossibleBench, AIDev, AgentLens-Bench status) and baselines B7-B12 plus the AgentProof disambiguation; ticked EP-01; extended the novelty-risk threat; added section 12 (literature gaps). No numeric claim in this plan was found wrong (the plan contained none from snippets); the figures that were previously only in search snippets are now sourced.
