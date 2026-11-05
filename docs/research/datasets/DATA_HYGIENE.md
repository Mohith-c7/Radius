# Data hygiene rules (EP-03)

Applies to every dataset in `INVENTORY.md`, to Radius's own benchmarks, and to anything we release. Tooling: `scripts/datasets.py` and `benchmarks/test_datasets.py`.

## 1. Manifests and hashing
- Every dataset has a manifest in `benchmarks/datasets/manifests/` with source URL, pinned revision (commit or version; never `main`), per-file size and sha256, licence verbatim, redistribution verdict and access date. Unverified values are written `UNVERIFIED`.
- Experiments reference datasets by manifest id plus revision and record the manifest sha256 in their output (EP-05).
- Run `python scripts/datasets.py verify` before every run; a hash or size mismatch fails the run. `fetch` needs `--yes`, does not run in CI without `--allow-ci`, refuses files without a url and sha256 (no trust on first use) and refuses downloads over 2 GiB unless `--max-bytes` is raised.
- Text files in the repo are hashed with CRLF normalised to LF (Windows checkouts).
- Third-party content is never committed. The cache lives in `.cache/datasets` (git-ignored) or `$RADIUS_DATASET_CACHE`.

## 2. Licensing
- Record the licence name verbatim and where it was read. If it cannot be established, write "UNKNOWN - do not redistribute"; `redistribution.allowed` must then be `no` (enforced by tests).
- A code-repo licence is not a dataset licence. Derived data inherits the base data's constraints (SWE-ABS rows are Apache-2.0 on the card but the base SWE-bench rows have no declared licence: conditional).
- Embedded third-party code (AIDev patches, SWE-bench repos) keeps its original licence: filter by repo licence before any redistribution.
- Non-commercial licences (for example CC BY-NC-SA 4.0 on the SWE-Mutation paper) are flagged as restricted for a commercial product; ask the owner before use.
- Radius's own fixtures and benchmarks have no licence until DEC-012 is decided; do not release before then.

## 3. Splits
- Use `scripts/datasets.py split` (default seed 20261102; any override is recorded in the report). Two modes: repo-based (whole repos on one side) and time-based (oldest train, newest test; a tie group straddling the cut goes to test).
- Hard rules, checked automatically (non-zero exit on violation): no instance id on both sides; no content hash on both sides; repo mode: no shared repo; time mode: latest train timestamp strictly before earliest test timestamp.
- Splits are fixed before looking at any model result. Calibration data (CA) is a third disjoint fold, never the test fold; thresholds are chosen on calibration only.
- For SWE-bench-derived data prefer repo-based splits for generalisation claims and report that 12 repos make them coarse. Time-based splits do not guarantee repo disjointness; report both when possible.
- Contamination: for LLM-based components report the model's training cut-off against dataset dates; prefer post-cut-off PRs (AIDev, own runs) for held-out claims.

## 4. Deduplication
- Dedupe by content hash (sha256 of canonical JSON of declared fields, default `repo` and `text`) before splitting; the lowest id wins and dropped ids are reported. Near-duplicates (forks, cherry-picks, the same patch in two repos) need hash fields chosen per dataset and are called out in its datasheet.

## 5. No label leakage into features
- Features use only information available at PR time. Forbidden inputs: merge/close state, review outcome, post-merge reverts, follow-up fixes, CI results of later commits, the gold patch, and FAIL_TO_PASS lists derived from the fix (for RQ2 evidence features use only tests visible in the PR).
- Label construction code lives apart from feature code; a test should assert that the feature extractor's input schema excludes label columns (to be added with EP-05).
- Strengthened tests and mutation outcomes (SWE-ABS, our `d_mut`) are labels when evaluating an a priori evidence score; they must not enter that score's features.
- Right-censoring: PRs younger than the label horizon (for example the revert window) are excluded or flagged, not treated as negatives.

## 6. PII, secrets and partner data (DEC-014, DEC-015)
- Public data only until a design partner opts in explicitly in writing and QS-06 (retention/privacy) is done (DEC-014). Partner data never enters this repo; it stays in the partner's environment or an access-controlled store.
- Public corpora still contain personal data in free text (names, emails in commit metadata, usernames in comments). Pseudonymise user ids and strip emails before sharing derived data; release ids and hashes, not raw text, where licences or privacy require it.
- Run a secret scanner over any text before it is stored in results or sent to an LLM; drop matches. Never place API keys, tokens or `.env` content in manifests or logs.
- LLM use on data: code does not leave the deployment by default (DEC-015); with third-party providers send only redacted intent text, only for datasets whose licence permits it, and log which provider saw which dataset.
- Retention: delete cached partner-derived files when the agreement ends; public caches may be kept.

## 7. Reproducibility
- Record per run: manifest ids and revisions, split seed and mode, algorithm version, Radius commit hash.
- Do not edit a dataset in place; create a new manifest revision. A changed upstream revision is a new dataset version.

## 8. Datasheet template

Follows Gebru et al., "Datasheets for Datasets" (2018) section headings (template written from memory of the paper's structure, not re-fetched in EP-03). Create one per dataset Radius will release, stored beside its manifest as `<id>.datasheet.md`. Do not fill with guesses; write UNVERIFIED.

```
# Datasheet: <name> (<id>, version <v>, <date>)

## Motivation
- Purpose / task it was created for (RQ served):
- Creators, funding:
## Composition
- Instance types and counts; fields; labels and how derived:
- Sampling strategy and representativeness (repos, languages, time range):
- Duplicates removed (rule); known errors or noise; equivalent mutants:
- Splits provided (mode, seed, leakage checks run):
- Does it contain confidential or personal data? What was removed?
- Third-party content and its licences:
## Collection process
- Sources, tools, versions, dates; who annotated, agreement (kappa), instructions:
- Consent / ethics approval (partner data: written opt-in reference):
## Preprocessing / cleaning / labeling
- Steps, raw data kept?, scripts (path + commit):
## Uses
- Intended uses; tasks it must not be used for (for example generalising beyond Python):
- Known risks: contamination, label leakage, staleness, bias:
## Distribution
- Where hosted, DOI, licence (verbatim) and why it is compatible with upstream licences; sha256 per file:
## Maintenance
- Owner and contact, update/erratum policy, versioning, deprecation:
```
