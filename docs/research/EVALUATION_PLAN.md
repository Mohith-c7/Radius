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

Hypothesis thresholds above are *initial guesses* and are fixed in the pre-registration (EP-02) before running the experiments.

## 3. Datasets (EP-03)

| Dataset | Use | Notes |
|---|---|---|
| SWE-bench Verified/Lite instances with agent patches | RQ2, RQ3 | Official tests pass for some wrong patches; analyses of this exist (UTBoost, PatchDiff, SWE-ABS). Verify exact numbers and licenses from the original papers before using or citing; the figures we saw came from search snippets. |
| UTBoost / PatchDiff / SWE-ABS augmented tests and labels | Ground truth for "plausible but incorrect" | Use their released artifacts; re-run their validation where feasible. |
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

Fair comparison: same inputs, same splits, tuned with the same budget, report seeds and variance.

## 5. Experiments

| ID | Task | Needs |
|---|---|---|
| EP-01 | Literature review (traceability, mutation testing for AI code, PR verification tools, calibration/conformal, process mining of agents). Confirm or narrow the novelty claim. Maintain a reading list and a table of related work with dates and artifacts. | none (start now) |
| EP-02 | Pre-registration: RQs, hypotheses, metrics, analysis plan, stopping rules, exclusion criteria. Freeze before running. | EP-01 |
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
- **Novelty risk:** related tools (AgentProof, Verik, SlopGate) are fast-moving; re-check before submission.

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
