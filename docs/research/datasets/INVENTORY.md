# Dataset inventory (EP-03)

Access date for every external fact below: **2026-11-02**. Sources: Hugging Face dataset API and README front matter, GitHub repository pages, Zenodo record page, arXiv abstract pages (fetched during EP-03). Anything not fetched is marked UNVERIFIED. Machine-readable twins live in `benchmarks/datasets/manifests/<id>.json` (schema: `benchmarks/datasets/manifest.schema.json`; tool: `scripts/datasets.py`). Rule: if a licence is unknown it is written "UNKNOWN - do not redistribute", and no third-party dataset content is committed, only manifests, hashes and scripts.

Status: **available** = pinned revision and sha256 recorded, fetchable now; **requested** = exists but not yet pinned or hashed, or needs an action; **blocked** = no artifact located, owner must ask the authors.

## Summary

| id | Dataset | Licence verdict | Redistribute? | Status | RQs |
|---|---|---|---|---|---|
| swe-bench-verified | SWE-bench Verified | UNKNOWN (no licence on dataset) | no | available | RQ2, RQ3 |
| swe-bench-lite | SWE-bench Lite | UNKNOWN | no | available | RQ2, RQ3 |
| swe-bench-full | SWE-bench full | UNKNOWN | no | available | RQ2, RQ3 |
| swe-bench-experiments | Leaderboard submissions (patches, logs, trajectories) | UNKNOWN | no | requested | RQ2-RQ4 |
| swe-abs-verified | SWE-bench Verified with SWE-ABS tests | Apache-2.0 (card); base data UNKNOWN | conditional | available | RQ2, RQ3 |
| swe-abs-code | SWE-ABS code | MIT | yes (code) | requested | RQ2, RQ3 |
| utboost | UTBoost augmented tests | UNKNOWN | no | **blocked** | RQ2, RQ3 |
| patchdiff | PatchDiff data | UNKNOWN | no | **blocked** | RQ2, RQ3 |
| swe-bench-plus | SWE-Bench+ | UNKNOWN | no | **blocked** | RQ2 |
| swt-bench | SWT-Bench | repo MIT; data UNKNOWN | no | requested | RQ2 |
| impossiblebench-swebench | Impossible-SWEbench | UNKNOWN (repo MIT) | no | available | RQ2 (tamper) |
| swe-mutation | SWE-Mutation | UNKNOWN (paper CC BY-NC-SA 4.0) | no | **blocked** | RQ2 |
| aidev-hf | AIDev, Hugging Face | CC-BY-4.0 (embedded code keeps repo licences) | conditional | available | RQ4, CA-01 |
| aidev-zenodo | AIDev, Zenodo v3 | CC-BY-4.0 | conditional | requested | RQ4, CA-01 |
| agentlens-bench | AgentLens-Bench | UNKNOWN (not released) | no | **blocked** | RQ4 |
| radius-f14-intent-fixtures | Radius F-14 fixtures | internal, no licence (DEC-012) | no | available | RQ1, RQ2 |
| radius-real-benchmark | Radius benchmarks/real | internal, no licence (DEC-012) | no | available | RQ2, RQ3 (self-eval) |

Not inventoried (no primary fetch in EP-03): SWE-bench Multimodal/Multilingual, SWE-bench Pro and its ABS variant (`OpenAgentLab/SWE-bench_Pro-ABS`, named on the SWE-ABS page), c-CRAB, CR-Bench, EvalPlus, partner PR data (none exists; DEC-014 says no partner history without written opt-in and QS-06).

## Per-dataset detail

### swe-bench-verified
- Source: https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified, revision `78f471bf655a3137b2e8a75af1501690ec009ec3` (HF API, lastModified 2026-08-16). Paper arXiv 2310.06770.
- Size: 500 rows (`test`), 17 columns; one parquet, 6,304,616 bytes (sha256 in manifest).
- Licence: **UNKNOWN - do not redistribute.** The HF API and README front matter contain no licence field. The code repo github.com/SWE-bench/SWE-bench is MIT (README), but that statement is for the repository, not the dataset; instances derive from public GitHub repos with their own licences.
- Labels: FAIL_TO_PASS / PASS_TO_PASS tests, gold patch, human-validated task quality (per card).
- Obtain: `python scripts/datasets.py fetch --id swe-bench-verified --yes`.
- Risks: contamination (SWE-Bench+ abstract: over 94% of issues predate LLM cut-offs); weak tests and solution leakage (UTBoost, PatchDiff, SWE-ABS, SWE-Bench+); only 12 Python repos.

### swe-bench-lite
- https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite, revision `b0dde1093fe417d83b7184254edf8199c1f0dff5`. 323 rows (test 300, dev 23). Licence UNKNOWN (as above). Same risks; the UTBoost abstract says its corrections affect 40.9% of Lite leaderboard entries.

### swe-bench-full
- https://huggingface.co/datasets/SWE-bench/SWE-bench, revision `c6fe717fd7a4c3ac1daa4055a4fd082c6a1d28a2`; test parquet 33,293,897 bytes, dev 3,299,303 bytes. Row counts not verified here (paper: 2,294). Licence UNKNOWN.

### swe-bench-experiments (agent patches)
- https://github.com/SWE-bench/experiments (286 stars on the page). The repo holds entries; predictions (`all_preds.jsonl`), per-instance logs (`patch.diff`, `report.json`) and trajectories live in each submitter's repository (or S3 for entries before mid-2026). Revision UNVERIFIED (GitHub API was rate-limited during EP-03). Licence not stated; per-submission terms unknown.
- Obtain: clone, then `python -m analysis.download_logs evaluation/verified/<date_model>` (no credentials per the page).
- Labels: resolved/unresolved per instance, i.e. the official-test label that RQ2/RQ3 argue is unreliable. It is the input patch population, not ground truth.
- Risks: selection bias (leaderboard systems), missing or moved artifacts, per-submission licences.

### swe-abs-verified and swe-abs-code
- Dataset: https://huggingface.co/datasets/OpenAgentLab/SWE-Bench_Verified_ABS, revision `79fc07a8f4ce5e3720e069948073f5f910b7577b`, 500 rows, 3,168,881 bytes. HF card licence `apache-2.0` (verbatim "license: apache-2.0"). `test_patch` holds the SWE-ABS-generated test patch; `original_test_patch` keeps the original. The base data has no declared licence, so redistribution is **conditional**: do not copy rows into a release until resolved.
- Code: https://github.com/OpenAgentEval/SWE-ABS, MIT (repo page), 26 stars, no releases, revision UNVERIFIED. Agent patches are not hosted there; evaluation downloads them from the SWE-bench leaderboard (`bash eval_agent_leaderboard.sh` inside `swe-bench/`).
- Labels: re-running an agent patch under the strengthened tests gives a "plausible but incorrect" label (SWE-ABS paper per EP-01: 2,184 of 11,041 passing patches rejected). The page does not say whether mutation-equivalence labels or judge outputs are published.
- Risks: authors' own evaluation (closest prior art to claim 2; do not present as ours); LLM-generated tests could over-reject and precision is not independently audited; must be paired with a second label source.

### utboost - BLOCKED
- Paper arXiv 2506.09289 (ACL 2025; paper CC BY 4.0, which does not cover data). No repository or data link found on the arXiv page or by search; a SOTAVerified listing says "Code Available" without a URL (not confirmed). Licence UNKNOWN - do not redistribute.
- Count discrepancy to reconcile before citing: arXiv v1 text surfaced by search says 23/300 Lite and 26/500 Verified instances flagged; EVALUATION_PLAN says 36 instances with insufficient tests.
- Owner action: email the authors (Yu, Zhu, He, Kang) for the augmented tests and the 345-patch label list.

### patchdiff - BLOCKED
- arXiv 2503.15223 (v2; ICSE 2026, doi 10.1145/3744916.3764576 per EP-01). No artifact link on arXiv, Hugging Face papers, alphaXiv or the ICSE page. Licence UNKNOWN - do not redistribute.
- Owner action: email the authors (Wang, Pradel, Liu) for per-patch behaviour-difference labels and generated tests; check the ICSE artifact track.

### swe-bench-plus - BLOCKED
- arXiv 2410.06992 (v2, paper CC BY 4.0). No dataset or repo link on the page. The sample is one agent (SWE-Agent + GPT-4). Licence UNKNOWN - do not redistribute. Owner action: ask the authors for the leakage and weak-test flags.

### swt-bench
- Repo https://github.com/logic-star-ai/SWT-Bench is MIT per the README; datasets are on Hugging Face under `nmuendler/` (`SWT-Bench_{,Lite_,Verified_}bm25_27k_{zsb,zsp}`). HF cards and revisions were **not** fetched in EP-03 (a Verified API lookup failed): dataset licence UNVERIFIED, treated as UNKNOWN - do not redistribute. Instances per the README: Full 2294, Lite 276, Verified 433. Status requested: pin revision and hashes before use.

### impossiblebench-swebench
- https://huggingface.co/datasets/fjzzq2002/impossible_swebench, revision `9c2d34f364b7229e8c0ff807c646100bdc18bbb5` (lastModified 2025-10-06); splits `original`, `oneoff`, `conflicting` (about 1.6 MB each). No licence on the HF dataset (UNKNOWN - do not redistribute); the code repo github.com/safety-research/impossiblebench is MIT (README), 77 stars. Row counts UNVERIFIED. Use: tamper ground truth for EV rules.

### swe-mutation - BLOCKED
- arXiv 2605.22175 (ACL 2026 Findings; 2,636 mutated variants from 800 instances; multilingual subset of nine languages). No artifact link. The paper is CC BY-NC-SA 4.0 (non-commercial, share-alike); if the data follows suit it conflicts with a commercial product. Licence UNKNOWN - do not redistribute. Owner action: ask the authors for data and licence.

### aidev-hf and aidev-zenodo
- HF: https://huggingface.co/datasets/hao-li/AIDev, revision `b8dc67df93e7c11f6f20c84129db7232eb1ec253` (lastModified 2026-10-21). Licence `cc-by-4.0` (front matter, verbatim "license: cc-by-4.0"). The card says each source repository retains its original copyright and licence and does not relicense the collection, so raw patches must not be redistributed without filtering by the repo licence in `all_repository`. The card says the user table has PII removed; free text (PR bodies, comments) still needs the hygiene rules.
- Sizes (HF API, bytes): all_pull_request 6,730,346,702; pr_commit_details 12,449,618,050; pr_timeline 1,100,479,400; pr_comments 690,491,134; pull_request (AIDev-pop) 362,078,556; smaller tables are in the manifest with sha256. `fetch` refuses more than 2 GiB unless `--max-bytes` is raised; use `--path` to select tables.
- Paper (arXiv 2602.09185): 932,791 agent-authored PRs, 5 agents, 116,211 repos, 72,189 developers, cutoff 2025-08-01; AIDev-pop: 33,596 PRs from repos with more than 100 stars.
- Zenodo record https://zenodo.org/records/16899501: v3, 2025-11-05, CC BY 4.0, 975.4 MB total, MD5 only. The page displayed DOI 10.5281/zenodo.16919272 while a search result cited 10.5281/zenodo.16899501 (which is the concept DOI and which the version DOI is UNVERIFIED). **HF and Zenodo snapshots differ** (for example all_pull_request 6.7 GB vs 331 MB), so pin one and never mix.
- Labels: agent, PR state, merged_at/closed_at, reviews, comments, timeline, commits, linked issues. No acceptance criteria. Merge is a noisy proxy for correctness; right-censoring needed (CA-01).
- Risks: stale vs newer agents, PII in free text, repo-licence heterogeneity, possible overlap with SWE-bench repos (check before mixing).

### agentlens-bench - BLOCKED
- arXiv 2605.12925; not released as of v4 (2026-10-05) per EP-01 (not re-fetched). Do not plan on it. Re-check periodically.

### radius-f14-intent-fixtures
- `benchmarks/fixtures/intent` (8 hand-authored scenarios); hashes of every `expected.json` and the schema are in the manifest (LF-normalised). Licence: none granted (DEC-012: undecided, no LICENSE file), so not redistributable until decided. Use: development, regression, RQ1/RQ2 smoke tests. Risk: tiny, authored by the system designer (circularity); not evidence of generalisation.

### radius-real-benchmark
- `benchmarks/real` (4 own packages, 120 mutants, 16 structural scenarios; subjects pinned to `6e354274b5b42497e88c44bca9d7e6121c9e82fe`). Hashes of `corpus.json` and `results/*.jsonl` are in the manifest; regenerating results changes them and requires a manifest update. Labels: full-suite detected vs undetected (undetected may be equivalent mutants). Self-evaluation on own Python code only; no intent annotations yet. No licence (DEC-012).

## Label-source plan (DEC-014: public data first)

1. Primary "plausible but incorrect" labels for SWE-bench Verified patches: SWE-ABS strengthened suites (available now; agent patches must come from swe-bench-experiments and be re-run).
2. Second source: UTBoost and/or PatchDiff, **both blocked**. Until obtained, the EVALUATION_PLAN requirement of at least two label sources is not met. SWE-Bench+ flags are a possible third.
3. Real-PR outcomes: AIDev-pop (merged/closed, reviews) plus revert/SZZ mining on public repos (CA-01). No design-partner data.
4. Expect disagreement between sources (SWE-ABS reports UTBoost strengthened only 10/500 instances, per EP-01); audit in CA-09.

## What the owner must request or decide

- Authors of UTBoost, PatchDiff, SWE-Bench+, SWE-Mutation: artifacts and licence terms (no links found).
- SWE-bench maintainers: confirm the dataset licence (none declared on Hugging Face); until then treat as UNKNOWN.
- Decide DEC-012 (Radius licence) before releasing fixtures or benchmark outputs.
- Optional: confirm the AIDev DOI mapping and whether AIDev-pop overlaps SWE-bench repos.
