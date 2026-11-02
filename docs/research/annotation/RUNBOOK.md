# Runbook: gold annotation for RQ1 (IN-09 / EP-04), for the owner

Status: tooling ready; **no real annotation exists**. This is what you (the owner) do, in order. Guidelines: `GUIDELINES.md`. Data layout and real-versus-synthetic rules: `../../../benchmarks/gold/README.md`.

All commands run from the repository root. Python 3.12, standard library only for the kit (the optional deterministic suggestions for the adjudicator need `PYTHONPATH` like CI: `packages/intent/src;packages/shared/src` on Windows, `:` on Linux).

## 1. What you need

| Role | Who | Notes |
|---|---|---|
| Annotator A | you or a colleague | not required to be you; see the Radius-developer rule below |
| Annotator B | a second person | independent of A |
| Adjudicator C | a third person | must differ from A and B; the tools refuse otherwise |

If only two people exist: A and B annotate, and the owner adjudicates only if the owner is neither A nor B; otherwise run a documented **consensus meeting** (GUIDELINES section 9, step 5) and record the deviation (PREREGISTRATION section on deviations).

**Radius developers are not neutral.** Anyone who wrote or tuned the extractors should not be A or B on the test role (GUIDELINES 10.4). If you must annotate, disclose it in the datasheet and plan a sensitivity analysis that excludes those PRs.

### Recruiting and briefing the second annotator

- Profile: reads pull requests daily (at least 2 years of professional or serious open-source experience), comfortable reading English, not a Radius contributor, no stake in the result, can commit about 20 hours over 2 to 3 weeks (see the estimate below).
- Briefing (45 minutes, do it once with A and B together):
  1. What the study asks and why independence matters (15 min). Explain that disagreements are expected and useful.
  2. Walk through `GUIDELINES.md` sections 1 to 6 with three invented examples each (20 min).
  3. Live demo of the tool on the synthetic fixture (see section 3), shortcuts via `?` (10 min).
- Give them: the guidelines, a personal id (`[a-z0-9_-]`), the instruction to declare conflicts in `benchmarks/gold/intent/conflicts.json` (GUIDELINES 10.3), and the three rules in one sentence: no system output, no talking about PRs with the other annotator, no looking up the PR on GitHub.
- Consent and disclosure: tell annotators that the tool logs active time per PR and their labels, stored under a pseudonymous id, and may be reported in aggregate in the paper. Get this acknowledged in writing (an email is enough). If the annotator is a student or employee of someone with authority over them, make participation voluntary and say so.
- Recognition: agree authorship or acknowledgement before starting (dataset papers usually credit annotators).

## 2. Time estimate (assumptions, not measurements)

Per-PR active time per annotator, **assumed** from the workload of the tool (read sources, mark about 4 criteria, set labels, one flag decision):

| Source richness | Assumed minutes |
|---|---|
| bare one-liner | 2 |
| issue link / spec file | 5 to 6 |
| structured template / long prose | 7 to 10 |
| **sample mean used below** | **6** |
| calibration PRs (first 10, read slowly, discussed) | 15 |

Adjudication, **assumed**: 1.5 disagreement items per PR, 2 minutes each, plus 0.5 minute per PR to open and finish = 3.5 minutes per PR.

| Scenario | Each annotator | Adjudicator | Total person-time |
|---|---|---|---|
| Gold only, 150 PRs (30 dev + 120 test) | 15 h | 8.8 h | about 39 h |
| Full preregistered plan: 30 pilot + 30 dev + 130 test = 190 PRs, plus calibration extra (1.5 h each) and a 2 h meeting for A, B, C | about 22.5 h | about 11.3 h | about 56 h |

Calendar: at 8 to 10 hours per week per person, 2.5 to 3 weeks for the full plan. The tool records real times (`gold_agreement.py compare` prints median and total per annotator), so replace these assumptions after the calibration round and update this table. Fetching sources is small: about 5 to 6 API calls per PR, roughly 1,100 calls for 190 PRs, within one hour of authenticated rate limit.

## 3. Try the tool on synthetic data first (10 minutes)

```
python scripts/gold_annotate.py serve --annotator demo --allow-synthetic \
    --gold-dir benchmarks/gold/synthetic --open
```

Everything in `benchmarks/gold/synthetic/` is fake and labelled `"synthetic": true`. Annotations made there are written into the fixture directory; revert with `git checkout benchmarks/gold/synthetic` and `git clean -fd benchmarks/gold/synthetic` (the committed fixture is checked by a test).

## 4. Pipeline (commands)

### 4.1 Candidates and exclusions

1. Export candidate PRs from AIDev (or another source) into CSV or JSONL with the fields listed in `scripts/gold_sample.py --help` (repo, number, agent/author type, language, additions/deletions, body, optional issue-link flags, licence). Downloading AIDev needs your `--yes`: `python scripts/datasets.py fetch --id aidev-hf --yes --path pull_request.parquet ...` (see its manifest). The kit never downloads for you.
2. Freeze the training/dev split first with `python scripts/datasets.py split ...` (DATA_HYGIENE section 3, default seed 20261102) and keep the report.
3. Prefer repositories with a permissive licence (the sampler warns when the licence is `UNKNOWN`).

### 4.2 Sample

```
python scripts/gold_sample.py sample --input candidates.jsonl \
    --out benchmarks/gold/samples/sample-v1.json --seed 20261102 \
    --exclude path/to/split_report.json --exclude path/to/train_records.jsonl \
    --dataset-manifest aidev-hf --n-pilot 30 --n-dev 30 --n-test 130
```

Read the printed warnings and `power_check` in the output. It checks the preregistered requirements (>= 120 test PRs, >= 461 expected criteria at the assumed 4 per PR, at least 5 test PRs in every richness x author stratum) and flags shortfalls; fix them by supplying more candidates, not by weakening the check. The default `--n-test 130` leaves a margin. The manifest has no timestamps: rerunning with the same input and seed gives identical bytes. Commit the manifest once frozen (it contains ids and strata, no text).

### 4.3 Fetch sources (network, needs your decision)

```
set GITHUB_TOKEN=...          (read-only token, public repositories; never commit or paste it)
python scripts/gold_sample.py fetch-sources --sample benchmarks/gold/samples/sample-v1.json --yes
```

It writes `benchmarks/gold/intent/<pr-id>/sources.json` (git-ignored): PR title and body, issues referenced in them, commit messages (merge commits skipped) and `.radius/intent.yml` at the head commit if present, sanitized with the product sanitizer when `PYTHONPATH` includes `packages/shared/src` (so annotators see what the extractor will see; the sanitizer name is stored). It waits for rate-limit resets, is safe to rerun (existing sources are kept; if upstream text changed after annotation started it warns and does not overwrite), and never prints the token. Texts are stored for local annotation only (`text_redistributable: false`).

### 4.4 Conflicts and queues

Create `benchmarks/gold/intent/conflicts.json` (GUIDELINES 10.3). Then one queue per annotator (different order, calibration PRs first):

```
python scripts/gold_sample.py queue --sample benchmarks/gold/samples/sample-v1.json \
    --annotator alice --out queue-alice.txt
```

### 4.5 Independent annotation

```
python scripts/gold_annotate.py serve --annotator alice --queue queue-alice.txt --open
python scripts/gold_annotate.py status --annotator alice
```

The server listens only on 127.0.0.1 with a per-run token in the URL; stop it with Ctrl+C. It is blinded: it never reads other annotators' files or any Radius output. Keyboard shortcuts: press `?`. Files are saved after every change and resumed on restart.

### 4.6 Calibration, pilot gate

```
python scripts/gold_agreement.py compare --prs calib.txt --out calib-report.json --md calib-report.md
```

(`calib.txt` = the 10 `calibration: true` ids from the sample.) Meet, discuss every listed disagreement, revise `GUIDELINES.md` (bump version, change log). Then annotate the other 20 pilot PRs and run `compare` on all 30: the report prints the gate (kappa >= 0.60). Below 0.60: revise and use a fresh pilot, once. Pilot and calibration PRs are not part of the analysis sets.

### 4.7 Agreement and adjudication

```
python scripts/gold_agreement.py compare --out agreement.json --md agreement.md
python scripts/gold_agreement.py skeleton --adjudicator carol
python scripts/gold_annotate.py serve --adjudicator carol --open        # resolve pending items
```

Optional for C only and off by default: `--prefill-from-radius` adds deterministic-extractor suggestions (documented anchoring risk; accepted suggestions are flagged `from_radius_suggestion`; it is refused in annotate mode).

### 4.8 Validate, report, release

```
python scripts/gold_validate.py check --complete
python scripts/gold_validate.py export-public --out benchmarks/gold/public     # text-free
```

`agreement.json` (with 95% bootstrap CIs over PRs) goes into the paper's annotation section. A datasheet (`DATA_HYGIENE.md` section 8) must accompany any release. Do not release before DEC-012 (licence) is decided.

## 5. Ethical and licensing notes

- The texts are public GitHub content written by third parties. Reading them through the API for research is within GitHub's terms; redistributing them is not automatically allowed. The repository ignores `benchmarks/gold/intent/*/` so raw text is not committed. Publish ids, offsets, hashes and labels (the `export-public` output) plus a script that re-fetches the text and checks the hashes.
- AIDev is CC-BY-4.0 as a collection, but embedded text and code keep their authors' and repositories' rights (INVENTORY.md). Filter by repository licence before releasing anything derived.
- Personal data: PR bodies may contain names, emails or handles. Logins are stored only as sha256; do not copy text into issues, chats or LLM tools. The deterministic suggestion path is local and sends nothing out; no LLM is used anywhere in this kit.
- Annotators are research participants in a minor sense (their labels and timing are data): pseudonymous ids, written acknowledgement, right to withdraw. If your institution requires ethics review for annotator studies, ask before recruiting.
- Report the conflicts declared and any annotator who is a Radius developer.

## 6. What you must do (checklist)

1. [ ] Decide the candidate source and produce the candidate CSV/JSONL (AIDev export needs your `--yes`).
2. [ ] Freeze the train/dev split and keep the report; run the sampler; resolve every `power_check` shortfall; commit `benchmarks/gold/samples/sample-v1.json`.
3. [ ] Create a read-only GitHub token; run `fetch-sources --yes`.
4. [ ] Recruit annotator B and adjudicator C (three distinct people); brief them; collect written acknowledgement; collect conflict declarations into `conflicts.json`.
5. [ ] Run the 10-PR calibration, meeting and guideline revision; annotate the other 20 pilot PRs and check the kappa gate.
6. [ ] Annotate dev and test independently (A and B), each from a personal queue.
7. [ ] Adjudicate (C), then `check --complete`.
8. [ ] Record real times; update section 2 of this runbook.
9. [ ] Write the datasheet, decide release (DEC-012), set IN-09 to `[x]` and EP-04 to done only when kappa and counts meet the preregistration.
10. [ ] Tell the next agent task (IN-10) that the gold set exists and where.
