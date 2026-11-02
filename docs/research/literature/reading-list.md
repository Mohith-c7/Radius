# Reading List (EP-01)

Prioritized, at most 25. Order = read first. Tag: P/S (see `README.md`). Keys refer to `references.bib`. "Why" is one line.

## Tier 1: read before writing the pre-registration (EP-02)

1. **Yu et al., SWE-ABS (2026, arXiv 2603.00520)** [P] `Yu2026sweabs`: closest prior work on mutation-driven exposure of weak test evidence; code is MIT; defines what we must differentiate from.
2. **Wang, Pradel, Liu, PatchDiff study (ICSE 2026, arXiv 2503.15223)** [P] `Wang2026patchdiff`: plausible-but-incorrect patch rates and causes on SWE-bench Verified; label source.
3. **Yu et al., UTBoost (ACL 2025, arXiv 2506.09289)** [P] `Yu2025utboost`: test augmentation labels; compare with SWE-ABS (UTBoost strengthened 10/500 instances there).
4. **Sahoo et al., AgentLens (arXiv 2605.12925)** [P] `Sahoo2026`: process quality of passing runs; the main overlap for claim 4; check the artifact release.
5. **Shahini, Metzger, Pohl, JIT conformal defect prediction (MSR 2024)** [P] `Shahini2024`: only SE precedent for conformal guarantees; warns about low guaranteed coverage.
6. **Angelopoulos et al., Conformal Risk Control (ICLR 2024)** [P] `Angelopoulos2024crc`: the method behind CA-04; read assumptions (exchangeability, monotone loss).
7. **Angelopoulos et al., Learn then Test (2021)** [P] `Angelopoulos2021ltt`: alternative when risk is not monotone.
8. **Spiess et al., Calibration and correctness of LMs for code (ICSE 2025)** [P] `Spiess2025`: calibration practice in SE; Platt scaling needs correctness data.
9. **Guo et al., On calibration of modern neural networks (ICML 2017)** [P] `Guo2017`: ECE and temperature scaling; defines our RQ3 metrics.
10. **Niedermayr et al., Will my tests tell me if I break this code? (CSED 2016)** [P] `Niedermayr2016`: pseudo-tested methods, ancestor of "covered but unproven".

## Tier 2: read before experiments (EP-03 to EP-08)

11. **Inozemtseva & Holmes, Coverage is not strongly correlated with test suite effectiveness (ICSE 2014)** [S] `Inozemtseva2014`: why B1 (coverage) is a weak baseline.
12. **Just et al., Are mutants a valid substitute for real faults? (FSE 2014)** [S] `Just2014`: validity of `d_mut`; read for the uncoupled-fault share.
13. **Aleithan et al., SWE-Bench+ (arXiv 2410.06992)** [P] `Aleithan2024`: solution leakage and weak tests; dataset hygiene (EP-03).
14. **Jimenez et al., SWE-bench (ICLR 2024)** [P] `Jimenez2024`: base benchmark.
15. **Mundler et al., SWT-Bench (arXiv 2406.12952)** [P] `Mundler2024`: issue reproduction tests as verifier baseline.
16. **Fuchss et al., LiSSA (ICSE 2025)** [P] `Fuchss2025`: strongest LLM traceability baseline for RQ1.
17. **Lin et al., T-BERT (ICSE 2021)** [P] `Lin2021`: learning-based link recovery baseline.
18. **Li, Zhang, Hassan, AIDev (arXiv 2602.09185)** [P] `Li2026aidev`: candidate real-PR corpus for CA-01; check license and fields.
19. **Zhong, Raghunathan, Carlini, ImpossibleBench (arXiv 2510.20270)** [P] `Zhong2025`: test-exploitation ground truth for tamper rules.

## Tier 3: read before writing related work and the threat model

20. **Zheng et al., LLM-as-a-judge (NeurIPS D&B 2023)** [P] `Zheng2023` and **Jin & Chen, LLM failures verifying code against NL specs (ASE 2025 NIER)** [P] `Jin2025`: why the LLM stays off the verdict path; B3 caveats.
21. **Isbarov et al., GitInject (arXiv 2606.09935)** [P] `Isbarov2026`: injection against AI review in live GitHub workflows; QS-02.
22. **Zhang et al., c-CRAB (arXiv 2603.23448)** [P] `Zhang2026ccrab`: review-agent evaluation protocol for RQ5.
23. **Pornprasit & Tantithamthavorn, JITLine (MSR 2021)** [S] `Pornprasit2021` with **Kamei et al. (TSE 2013)** [S] `Kamei2013`: line-level and effort-aware ranking baselines for RQ5.
24. **Kim et al., Coherence Collapse (arXiv 2603.24631)** [P] `Kim2026coherence` and **Majgaonkar et al. (arXiv 2511.00197)** [P] `Majgaonkar2025`: trajectory features and failure structure for PR-06.
25. **Competitor repositories to re-read before every release:** AgentProof (RengGyu) `AgentProofRengGyu`, ScopeProof `ScopeProof`, AgentProof (GenRamzi) `AgentProofGenRamzi`, Verik `Verik`, SlopGate `SlopGate` [all P repos, snapshots of 2026-11-02]: fast-moving; licenses and rules matter for B4/B5 and QS-13.

## Not on the list on purpose

Classical background (Antoniol 2002, Qi 2015, Smith 2015, Papadakis 2019, Platt, Niculescu-Mizil & Caruana, selective classification) is cited in `related-work.md`; skim, do not prioritize.
