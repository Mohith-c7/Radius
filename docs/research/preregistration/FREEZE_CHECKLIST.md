# Freeze checklist (EP-02)

Status of this file: **a working list, not part of the pre-registration and not a freeze.** `PREREGISTRATION.md` is still `DRAFT -- not frozen` and nothing here changes that. Only the owner freezes (procedure: `CHANGELOG.md` section 1 and `PREREGISTRATION.md` 17.10).

This list restates `PREREGISTRATION.md` section 16 as concrete conditions, adds the ones the repository state showed to be missing, and says for each how to verify it, who has to act, and where it stands. The machine-checkable part is `scripts/prereg_check.py`:

```
python scripts/prereg_check.py            # PASS / FAIL / MANUAL per item; exit 1 if any FAIL
python scripts/prereg_check.py --only D   # one group
python scripts/prereg_check.py --json
```

`PASS` means a stated precondition holds, never that a result is good. `FAIL` is a machine-checkable condition that is not met. `MANUAL` needs a human decision or attestation; the line says what the script found. The script changes nothing, uses no network, and its grep-based absence checks name the tokens they looked for (a miss can be a naming difference).

**Status column** (snapshot of 2026-11-03 at the commit that added this file; rerun the script to refresh, its output is authoritative): `DONE` = the check passes; `TODO` = the check fails, work remains; `OWNER` = needs the owner (or annotators, or data that does not exist yet) to decide, supply or attest.

**Owner column**: `agent` = can be done in the repository without new data or a human; `owner` = the repository owner; `annotators` = the human annotators and adjudicator; `owner+data` = needs data that does not exist yet.

## Findings made while building this list

These are facts the checks surfaced. None is resolved here; they are for the owner to decide before the freeze.

1. **The documented hash procedure does not cover the whole document (A2b).** `CHANGELOG.md` section 1 computes the canonical hash with `sed '/<!-- FREEZE-BLOCK-START -->/,/<!-- FREEZE-BLOCK-END -->/d'`. `PREREGISTRATION.md` prints that very command in section 17.10 (line 482), and the pattern also matches there; with no end marker after it, sed deletes from that line to the end of the file. So 23 of 505 lines (end of 17.10, and section 18) are excluded from the hash and can change without changing it. The recorded draft hash `c01cb5fc...` is reproduced by this behaviour. Anchoring the patterns fixes it, and changes the hash (acceptable only before the freeze).
2. **The conformal loss in 7.1 is not non-increasing in the threshold (E5).** The CRC theorem needs that property; see `../evaluation/CALIBRATION_TOOLKIT.md`. The item "verified by the CA-05 implementer" cannot be ticked as written.
3. **The split tool does not implement the pre-registered split (B4).** `scripts/datasets.py split` is two-way with a default test fraction of 0.2, while 2.2 prescribes the earliest 40% as dev and the latest 60% as test, with dev split 60/40 into fit and calibration. The cut point can be set by flag; the third fold does not exist.
4. **Defaults differ from 17.3 (F4).** `MutationBudget.wall_clock_seconds` defaults to 900 s while 17.3(a) names a 20-minute per-patch cap, if that field is the per-patch cap. The operator ids are not named in `PREREGISTRATION.md`, so the operator set is not frozen by it.
5. **The thresholds' origin is undeclared (F1, F2).** `cap_static` and `tau_support` were fitted to the 8 F-14 fixtures (`docs/KNOWN_LIMITATIONS.md`); the pre-registration does not say so and does not record a config digest. 6.1 says the hyperparameters are set on dev data under rule 2.2.8 and recorded at "tuning closed"; until that entry exists no frozen configuration exists.
6. **Circularity protocol (F6, F7).** `design/MUTATION_EVIDENCE.md` section 12 says its protocol is "to be frozen with the pre-registration", but `PREREGISTRATION.md` does not reference it, and none of its controls (held-out mutant split, input-manifest rejection of label-store paths, site-overlap measurement) has a code occurrence. Separately, `MUTATION_EVIDENCE.md` section 3 calls the operator-set decision "open decision D1" while section 14 defines D1 as the engine choice and the header says D1 is decided (DEC-035); the labels disagree.
7. **Known editorial items still open (A3):** baseline numbering is not reconciled between `EVALUATION_PLAN.md` and `literature/novelty-assessment.md`; the repo count in 2.2 rule 2 is "to be read from the manifest"; the compute budget in 17.3 is blank by design until the timing pilot has run.

## A. The document

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| A1 | Freeze block present and parseable; status DRAFT until the owner freezes | `prereg_check` A1 | agent | DONE |
| A2 | Recorded hash equals the hash from the documented procedure | `prereg_check` A2 (recompute with the command in `CHANGELOG.md` 1) | agent | DONE (draft tracking hash only) |
| A2b | The hash procedure excludes only the freeze block (finding 1) | `prereg_check` A2b | owner | TODO |
| A3 | Placeholder phrases resolved: baseline numbering reconciled, repo count read from the manifest, compute budget written (finding 7) | `prereg_check` A3; read `PREREGISTRATION.md` 2.2, 4, 17.3 | owner | TODO |
| A4 | Pre-freeze pilots listed (at least the timing pilot on 100 dev patches, 17.3) | `prereg_check` A4; `CHANGELOG.md` section 4 | owner | TODO |
| A5 | "Tuning closed" entry: commit, `algo_version`, manifest hash, date | `prereg_check` A5; `CHANGELOG.md` section 5 | owner | TODO |

## B. Data and splits

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| B1 | All dataset manifests validate against `manifest.schema.json` | `prereg_check` B1; `python scripts/datasets.py verify` for downloaded hashes | agent | DONE |
| B2 | SWE-bench Verified, SWE-ABS (`L_ABS`) and public agent patches pinned with sha256 | `prereg_check` B2 (`swe-bench-experiments` has no pinned files) | owner | TODO |
| B3 | UTBoost, PatchDiff, SWE-Bench+, SWE-Mutation obtained or declared unavailable | author requests in `../datasets/AUTHOR_REQUESTS.md` (drafts not sent); manifests say `blocked` | owner | OWNER |
| B4 | Split tool implements 2.2 (40/60 time split, 60/40 fit/calibration, seed) (finding 3) | `prereg_check` B4; `scripts/datasets.py split --help` | agent | TODO |
| B5 | Cut points computed from the manifest and recorded | a split report in the repo; `prereg_check` B5 | owner+data | TODO |
| B6 | Master seed 20261102 consistent across documents and tools | `prereg_check` B6 | agent | DONE |
| B7 | Manifest facts re-measured (patches, positives, instances, repos, agents); power table (section 12) recomputed | run the harness on the pinned manifests | owner+data | OWNER |

## C. Gold set (RQ1)

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| C1 | Gold schema loads; synthetic fixture validates (tooling works) | `prereg_check` C1; `python -m pytest tests/test_gold_*.py` | agent | DONE |
| C2 | Guidelines revised after the 10-PR calibration round | `docs/research/annotation/GUIDELINES.md` change log; `prereg_check` C2 | annotators | TODO |
| C3 | At least 120 adjudicated test PRs and 30 pilot PRs (plus the dev PRs of the sample) | `prereg_check` C3; `python scripts/gold_validate.py check --complete` | annotators | TODO |
| C4 | Pilot presence and testability kappa >= 0.60 on the 30-PR pilot (5.4) | `prereg_check` C4; `scripts/gold_agreement.py compare` | annotators | TODO |
| C5 | Three distinct people as A, B and C; written acknowledgements; conflicts declared; Radius-developer disclosure | RUNBOOK sections 1 and 6; `benchmarks/gold/README.md` batch notes | owner | OWNER |

Tooling for the human steps is ready and tested on synthetic data only: `../annotation/RUNBOOK.md`, `../datasets/ANNOTATION_GUIDE.md`, `scripts/gold_pack.py` (offline kit), `scripts/gold_to_eval.py` (adapter). No real annotation exists.

## D. Baselines B0 to B12 (4 and EP-06)

Condition for each: implemented and validated, or listed as not run with a reason. The script can only see whether code exists; `MANUAL` means code exists and validation is not recorded.

| ID | Baseline | Evidence found by the script | Owner | Status |
|---|---|---|---|---|
| D.B0 | CI pass/fail only | none; degenerate on test-passing patches (6.3), so list it as a constant predictor or not run | agent | TODO |
| D.B1 | Coverage of changed lines | `confidence/domain/coverage.py` only (no baseline predictor) | owner | OWNER |
| D.B2 | Radius v1 heuristic score | `confidence/infrastructure/scoring.py` (not run as a baseline) | owner | OWNER |
| D.B3 | LLM-as-judge | none | owner | TODO |
| D.B4 | AgentProof-style mapping | none (licence decision recorded, DEC-018) | owner | TODO |
| D.B5 | Tamper rules only | tamper package exists; no rules-only predictor | owner | OWNER |
| D.B6 | Whole-file mutation score | mutation matrix exists; whole-file variant not built | owner | OWNER |
| D.B7 | Rubric verifier | none | owner | TODO |
| D.B8 | Fail-to-pass reproduction-test verifier | none | owner | TODO |
| D.B9 | ScopeProof-style retrieval | own linker only | owner | OWNER |
| D.B10 | Linking baselines | BM25 inside the linker; no standalone or neural baselines | owner | OWNER |
| D.B11 | Calibration baselines | Platt, isotonic, LTT, CRC in the new toolkit (unvalidated on real data); temperature scaling and held-out-threshold selective baseline missing | agent | OWNER |
| D.B12 | Triage baselines | none | owner | TODO |

## E. Analysis code

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| E1 | Named procedures (DeLong, McNemar, Wilcoxon, Holm, BH, Clopper-Pearson, bootstrap) implemented | `prereg_check` E1 (DeLong, McNemar, Wilcoxon, BH not found) | agent | TODO |
| E2 | An analysis script exists for each RQ | `prereg_check` E2 (RQ1 and RQ3 partly; RQ2, RQ4, RQ5, RQ6 none by file name) | agent | TODO |
| E3 | Harness emits `algo_version`, seed, commit, dataset and config hashes | `prereg_check` E3 (RQ1 harness only) | agent | OWNER |
| E4 | Feature-provenance test (no gold at inference, 2.2 rule 5) exists and passes | `prereg_check` E4 | agent | TODO |
| E5 | Conformal loss verified by the CA-05 implementer (finding 2) | decision recorded in `PREREGISTRATION.md` 7.1 | owner | OWNER |
| E6 | ECE noise floor recomputed with real dev scores (7.5) | `scripts/calibration_report.py` prints the floor for the supplied scores | owner+data | OWNER |

## F. System under test and circularity

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| F1 | Digest of the frozen Verdict v2 config recorded in the pre-registration | `prereg_check` F1 prints the current default digest | owner | TODO |
| F2 | Thresholds frozen with the fitting data declared (finding 5) | `prereg_check` F2 | owner | TODO |
| F3 | Frozen `algo_version` tagged in git | `git tag --list`; `prereg_check` F3 | owner | OWNER |
| F4 | Operator set and mutation budgets named in the pre-registration and equal to the code (finding 4) | `prereg_check` F4 prints a digest of operators and budget defaults | owner | TODO |
| F5 | Circularity protocol documented | `design/MUTATION_EVIDENCE.md` section 12; `prereg_check` F5 | agent | DONE |
| F6 | Pre-registration references and freezes that protocol (finding 6) | `prereg_check` F6 | owner | TODO |
| F7 | The protocol's controls exist in code (held-out mutant split by id hash, input-manifest rejection of label-store paths, site-overlap measurement, negative controls) | `prereg_check` F7 | agent | TODO |

## G. Fixtures

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| G1 | The 8 F-14 fixtures complete (they are regression tests, not evaluation data) | `prereg_check` G1; `python -m pytest benchmarks/test_intent_fixtures.py` | agent | DONE |

## H. Owner acts and attestations

| ID | Condition | How to verify | Owner | Status |
|---|---|---|---|---|
| H1 | Label agreement between sources measured; `L_audit` sample drawn | needs two label sources and CA-09 | owner+data | OWNER |
| H2 | RQ2 compute budget declared from the timing pilot (17.3) | the figure is written into `PREREGISTRATION.md` | owner | OWNER |
| H3 | User-study materials, ethics determination or exemption, consent form, recruitment plan | TR-05 | owner | OWNER |
| H4 | RQ6 hardware and sandbox configuration declared | measurement machine described | owner | OWNER |
| H5 | Attestation that no test-split labels or results have been viewed | owner statement in `CHANGELOG.md` | owner | OWNER |
| H6 | Freeze: hash in the block, version-table row, signed tag, external deposit (17.10) | owner act only | owner | OWNER |

## Counts at the snapshot

`python scripts/prereg_check.py` on 2026-11-03: 7 PASS, 24 FAIL, 20 MANUAL. The document is not ready to freeze, which is the expected state: the dominant blockers are data and human work (gold set, labels, pilots, user study), not code.
