# Author and maintainer requests (DRAFTS, NOT SENT)

Status: **no message below has been sent.** The owner reviews, edits and sends them from their own account. Contact details were taken on 2026-11-02 only from the arXiv abstract pages and the GitHub repository pages named below. arXiv pages show author names but no email addresses (only a "view email" link for the submitter, which was not opened), so where no address is listed it is marked **UNVERIFIED: find the address on the paper PDF's first page, the author's institutional page, or use the submitter link on arXiv**. Do not guess addresses.

Purpose (same in every message): Radius is an open-source tool (Apache-2.0, DEC-018) and an accompanying study that measures how strongly the tests in an agent-written pull request would catch a wrong change, evaluated against "plausible but incorrect" labels on SWE-bench patches (pre-registration `docs/research/preregistration/PREREGISTRATION.md`, labels `L_ABS`, `L_UTB`, `L_PD`). We use external datasets only locally for research, never commit or redistribute rows, record hashes and licences in a manifest, and cite the source in any publication. Related tracking: `INVENTORY.md` in this folder.

Before sending: replace `[OWNER NAME]`, `[AFFILIATION]`, `[REPO/PROJECT URL]` and the contact line; the owner decides whether to mention the pre-registration (recommended: say it is a draft that has not been frozen).

---

## 1. UTBoost (arXiv 2506.09289)

- Authors on the arXiv page: Boxi Yu, Yuxuan Zhu, Pinjia He, Daniel Kang. Affiliations are not shown on the page.
- Email: **UNVERIFIED** (arXiv shows only a "view email" link for the submitter, Boxi Yu). Repository or data link: none found on the arXiv page.
- Related contact route that exists: Boxi Yu and Pinjia He are also authors of SWE-ABS, whose repository is https://github.com/OpenAgentEval/SWE-ABS (issues and a Discord are listed there). Prefer one message to one author, copying the others if the owner wishes.

**Subject:** Request for UTBoost augmented tests and licence terms (research use)

Dear Dr. Yu, Dr. Zhu, Dr. He and Dr. Kang,

I am [OWNER NAME] ([AFFILIATION]) and I am building Radius ([REPO/PROJECT URL]), an open-source tool that estimates how much trustworthy evidence the tests in an agent-written pull request provide. We are preparing an evaluation on SWE-bench Verified patches and we would like to use UTBoost as one of the independent sources of "plausible but incorrect" labels, next to SWE-ABS. We found your paper (arXiv 2506.09289) but could not find a public repository or dataset link.

Could you tell us:

1. Whether the augmented test cases (the extra tests for the flagged SWE-bench Lite and Verified instances) and the list of patches whose verdict changed are available, and where (a repository, Hugging Face, Zenodo, or by request)?
2. Exactly which files they are: the augmented tests per instance, the intramorphic-testing outputs, the per-patch re-evaluation results (for example the 345 erroneous patches mentioned in the paper), and the leaderboard re-ranking?
3. Under which licence the code and data are released, and whether research use inside an open-source project is permitted? We would only use the data locally to compute labels, keep a hash manifest, never redistribute rows, and cite your paper. If you prefer a different arrangement we will follow it.
4. Whether there is a preferred citation or an attribution line in addition to the paper.

We also noticed that the number of flagged instances differs between versions or summaries of the paper (for example 26 versus 36); a pointer to the final counts would help us avoid misreporting.

Thank you for the work, and for any pointer, even a short one.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]

---

## 2. PatchDiff (arXiv 2503.15223, "Are 'Solved Issues' in SWE-bench Really Solved Correctly?")

- Authors on the arXiv page: You Wang, Michael Pradel, Zhongxin Liu. Affiliations are not on the page. The page also lists the ICSE 2026 DOI 10.1145/3744916.3764576.
- Email: **UNVERIFIED** (none on the arXiv page). Artifact link: none found on the arXiv page (check the ICSE artifact track and the PDF).

**Subject:** PatchDiff artifacts and licence: request for research use

Dear Dr. Wang, Dr. Pradel and Dr. Liu,

I am [OWNER NAME] ([AFFILIATION]), working on Radius ([REPO/PROJECT URL]), an open-source tool that measures how strongly tests support a code change. In our planned evaluation we want to use PatchDiff's finding that some plausible patches behave differently from the gold patch as a secondary label source, and to compare against it. We could not find an artifact link for your paper (arXiv 2503.15223, ICSE 2026).

Could you tell us:

1. Whether the per-patch labels (which plausible patches were judged behaviourally different and certainly incorrect) and the generated differential tests are released, and where?
2. Exactly which files exist (the patch list with identifiers and labels, the generated tests, the manual review notes, the scripts)?
3. The licence of the data and code, and whether research use in an open-source project is permitted? We would use them locally, store only hashes in a manifest, never redistribute, and cite your paper.
4. Whether you would prefer a particular attribution or citation form.

Thank you for your time and for the study.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]

---

## 3. SWE-Bench+ (arXiv 2410.06992)

- Authors on the arXiv page: Reem Aleithan, Haoran Xue, Mohammad Mahdi Mohajer, Elijah Nnorom, Gias Uddin, Song Wang. Submitter: Song Wang. Affiliations not on the page.
- Email: **UNVERIFIED** (only a "view email" link for the submitter). Artifact link: none found on the arXiv page.

**Subject:** SWE-Bench+ leakage and weak-test flags: availability and licence

Dear Dr. Wang and co-authors,

I am [OWNER NAME] ([AFFILIATION]), building Radius ([REPO/PROJECT URL]), an open-source tool for assessing how well tests support agent-written changes. We would like to use the SWE-Bench+ analysis (solution leakage and weak-test flags on SWE-bench instances, arXiv 2410.06992) as a leakage-filtered sensitivity subset in our evaluation. We could not find a released dataset or repository.

Could you tell us:

1. Whether the SWE-Bench+ instance flags (solution leakage, weak or insufficient tests, and the filtered benchmark) are released, and where?
2. Exactly which files: the per-instance classification, the filtered instance list, the manual-analysis sheets for the SWE-Agent + GPT-4 patches, and any code?
3. The licence of the data and code, and whether research use inside an open-source project is permitted? We would only use them locally, keep hashes in a manifest, not redistribute, and cite your paper.
4. The attribution you would like.

Thank you for your work and for any pointer.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]

---

## 4. SWE-Mutation (arXiv 2605.22175)

- Authors on the arXiv page (9): Yuxuan Sun, Yuze Zhao, Yufeng Wang, Yao Du, Zhiyuan Ma, Jinbo Wang, Mengdi Zhang, Kai Zhang, Zhenya Huang. Affiliations not on the page. The inventory notes the paper is CC BY-NC-SA 4.0 and ACL 2026 Findings.
- Email: **UNVERIFIED** (only a "view email" link for the submitter). Artifact link: none found on the arXiv page.

**Subject:** SWE-Mutation data availability and licence (non-commercial clause question)

Dear Dr. Sun and co-authors,

I am [OWNER NAME] ([AFFILIATION]), building Radius ([REPO/PROJECT URL]), an open-source tool (Apache-2.0) that measures how strongly tests detect faulty changes. SWE-Mutation (arXiv 2605.22175; 2,636 mutated variants from 800 instances) is closely related to our mutation-based evidence measure, and we would like to use it as an external test of our mutant handling. We could not find a public artifact.

Could you tell us:

1. Whether the SWE-Mutation dataset and code are released, and where?
2. Exactly which files: the mutated variants, the instance list, the multilingual subset, the evaluation scripts?
3. The licence of the data and code. We noticed the paper is CC BY-NC-SA 4.0; does that licence also apply to the dataset? Our project is open source and will also have a commercial offering, so we will not use non-commercially licensed data in the product or in any redistributed artifact. For academic evaluation only, would you permit use, and is there a licence or permission form we should follow?
4. The attribution you would like.

If the terms do not allow our use, we will simply not use the data. Thank you for your time.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]

---

## 5. SWE-ABS (arXiv 2603.00520) and the SWE-Bench Verified ABS dataset

- Paper authors (from the GitHub page): Boxi Yu, Yang Cao, Yuzhong Zhang, Liting Lin, Junjielong Xu, Zhiqing Zhong, Qinghua Xu, Guancheng Wang, Jialun Cao, Shing-Chi Cheung, Pinjia He, Lionel Briand.
- Contact route verified on the repository page https://github.com/OpenAgentEval/SWE-ABS: GitHub issues (https://github.com/OpenAgentEval/SWE-ABS/issues) and a Discord (https://discord.gg/r3wDPRPaS4). No maintainer email is listed: **email UNVERIFIED**. Code licence: MIT (repository). Dataset https://huggingface.co/datasets/OpenAgentLab/SWE-Bench_Verified_ABS carries an `apache-2.0` card (per INVENTORY.md); the base SWE-bench data inside it has no declared licence.
- Suggested channel: a GitHub issue titled "Artifact and licence questions" (public), or the Hugging Face dataset discussion tab (not verified to be enabled).

**Subject / issue title:** Artifacts and licence terms for SWE-ABS labels and patches

Dear SWE-ABS authors,

I am [OWNER NAME] ([AFFILIATION]), building Radius ([REPO/PROJECT URL]), an open-source tool that measures how strongly the tests in an agent-written change support its intent. Our planned evaluation uses SWE-ABS as the primary "plausible but incorrect" label source (patches that pass the original tests but fail the strengthened suite), and we credit SWE-ABS as the closest prior work on benchmark-time strengthening; our contribution is a PR-time predictor that does not use the gold patch.

Could you tell us:

1. Whether the per-patch outcomes of re-running leaderboard patches under the strengthened suites (the 11,041 passing patches and the 2,184 rejected, as reported in the paper) are released, or only the strengthened tests and the scripts to regenerate them? If only scripts, which command and which patch source do you recommend?
2. Exactly which files exist: the strengthened `test_patch`, the mutation-equivalence labels and judge outputs, the SWE-bench Pro ABS variant, and the leaderboard results?
3. How the Apache-2.0 licence on the Hugging Face card relates to the underlying SWE-bench instance data, and whether you are comfortable with us using the data locally and publishing only derived aggregate results, hashes and our own scripts?
4. The attribution you would like in our paper and README.

Thank you for releasing the code and data.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]

---

## 6. SWE-bench maintainers: dataset licence

- Contact persons listed on https://github.com/SWE-bench/SWE-bench (verified 2026-11-02): Carlos E. Jimenez (carlosej@princeton.edu) and John Yang (johnby@stanford.edu). The page also says to file an issue or pull request. The repository is MIT; the page makes no separate statement about the datasets, and the Hugging Face dataset cards (SWE-bench, Lite, Verified) have no licence field (per INVENTORY.md). A public GitHub issue is the lowest-friction alternative to email.

**Subject:** Licence of the SWE-bench datasets on Hugging Face (Full, Lite, Verified)

Dear Dr. Jimenez and Dr. Yang,

I am [OWNER NAME] ([AFFILIATION]), building Radius ([REPO/PROJECT URL]), an open-source tool (Apache-2.0) that studies how well the tests in agent-written patches detect wrong changes. We use SWE-bench Verified tasks and the public submissions in `SWE-bench/experiments`.

We noticed that the repository is MIT-licensed but the Hugging Face dataset cards for SWE-bench, SWE-bench Lite and SWE-bench Verified do not declare a licence, and the instances derive from public repositories with their own licences. Could you tell us:

1. Which licence or terms apply to the datasets (the task instances, the FAIL_TO_PASS and PASS_TO_PASS lists, the gold patches)?
2. Whether the public leaderboard submissions in `SWE-bench/experiments` (patches, logs, trajectories) may be used for research evaluation, and whether any per-submission terms apply?
3. Whether we may publish derived artifacts: instance identifiers, hashes, per-patch labels and aggregate results (we would not republish the raw task text or patches)?
4. Whether adding a licence statement to the dataset cards is planned. It would help everyone who builds on the benchmark.

We cite SWE-bench (Jimenez et al., ICLR 2024) in all our work and will follow whatever attribution you prefer.

Thank you for maintaining the benchmark.

Best regards,
[OWNER NAME]
[AFFILIATION, contact]
