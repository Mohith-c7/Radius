# Verdict v2 (alpha): how to read the verdict and the PR comment

Verdict v2 is an opt-in, per-criterion verdict. It is switched on with `RADIUS_FEATURE_VERDICT_V2` (`off` by default, `shadow` computes and stores it while v1 is still published, `on` publishes it instead of v1). This page explains what the verdict means and how the comment is laid out. It describes the **alpha**: the evidence is static assertion strength only, and every threshold is an uncalibrated default (profile `alpha-static`).

## How to enable

Set `RADIUS_FEATURE_VERDICT_V2` on **both** the API and the worker (same variable, same value):

| Value | What happens |
| --- | --- |
| `off` (default; unset, `false`, `0` or anything unrecognised) | Nothing changes. No v2 code runs, the v2 endpoint answers 404 `disabled`, and the v1 comment and Check Run are byte-for-byte what they were. |
| `shadow` | After each analysis the worker computes and stores v2, and the API serves it (`GET /api/v1/analyses/{id}/verdict-v2`, dashboard panel marked "shadow"). **v1 is still the only thing published to GitHub.** Use it to compare before you switch. |
| `on` (also `true`, `1`) | v2 is computed, stored and published **instead of** v1 for that analysis: one PR comment (the existing Radius comment, updated in place) and the `Radius confidence` Check Run. If v2 fails for any reason, or its head commit is stale, v1 is published as before. v1 is always computed and stored. |

A useful verdict also needs `RADIUS_FEATURE_INTENT_INGESTION=true` (otherwise there is no intent snapshot and the verdict is `Not verified - insufficient evidence`), and CI must upload per-case results (`POST /api/v1/analyses/{id}/tests/results`). When results arrive, the API leaves a small request for the worker, which re-scores (no new clone) and updates the same comment and Check Run within one poll interval. Replaying the same upload writes nothing new, and a result for a commit that is no longer the PR head is never published.

## What the verdict says, and what it does not

The verdict is computed by fixed rules from validated evidence (test outcomes uploaded from CI, links between criteria, code and tests, and tamper findings). No language model decides it.

**Wording.** The JSON contract keeps its internal values (`verified`, `proven`, ...), but everything a person reads says what the alpha actually measures. A comment starts with a one-line disclaimer ("Alpha - static evidence only - uncalibrated ... not a proof of correctness"), the internal state `proven` is shown as **SUPPORTED** (`unevidenced` as UNSUPPORTED), and the verdict `verified` is shown as **Supported by static evidence (alpha)**. Legend: *supported = static assertion strength above threshold; not a proof of correctness*. The API adds `alpha: true`, `calibrated: false`, `evidence_basis` and a `presentation` block with the same strings (`contract_version` `verdict-v2-contract-3`; all fields are optional additions).

- `Supported by static evidence (alpha)` (internal `verified`) means no rule found a problem, given the evidence Radius has. It does **not** mean the code is correct: tests were rated by the strength of their assertions, not by mutation testing, so a test that cannot fail can still count. The thresholds were fitted by eye to 8 hand-written fixtures and are uncalibrated.
- `Failed`, `Not verified - insufficient evidence` and `Needs human review` say why in one sentence and name the criteria involved.
- There is no probability and no percentage score in v2. The v1 heuristic score appears only in a collapsed "legacy" section, labelled uncalibrated.

## The four verdicts and the rules behind them

Rules are checked in this order. Every rule is evaluated and recorded; the first one that fires decides. Thresholds are the alpha defaults and can be changed in configuration.

| Order | Rule | Fires when | Verdict |
| --- | --- | --- | --- |
| 1 | R1a | a criterion is contradicted (a linked test failed) | Failed |
| 2 | R1b | any CI test case failed for this commit | Failed |
| 3 | R1c | an unwaived tamper finding at severity high or above | Failed |
| 4 | R2p | no CI test results received yet for this commit | Insufficient evidence, shown as "Awaiting CI test results" |
| 5 | R2a | no behavioral, testable criterion exists while behavioral code changed | Insufficient evidence |
| 6 | R2b | unproven intent mass above 0.20 | Insufficient evidence |
| 7 | R2c | less than 50% of the behavioral changes are covered by a stated criterion | Insufficient evidence |
| 8 | R2d | the analysis was incomplete (truncated, unsupported language, missing snapshot) | Insufficient evidence |
| 9 | R3a | an unwaived tamper finding at severity medium or above | Needs human review |
| 10 | R3b | a criterion counted as proven depends on a flaky test | Needs human review |
| 11 | R3c | a proven criterion rests on a weak criterion-to-code link (below 0.50) | Needs human review |
| 12 | R4 | none of the above | Supported by static evidence (alpha) (`verified`) |

Because failures come first, a tamper finding fails the verdict immediately, without waiting for CI. A pending PR (R2p) is published as a completed, neutral check, never left "in progress"; the comment updates itself when results arrive.

Unsupported intent mass (UIM; "unproven" in the design documents) is the weighted share of non-excluded criteria whose support is below 0.50. Intent coverage is the share of behavioral changes that a stated criterion accounts for.

## Criterion states

| State in the comment (internal value) | Meaning |
| --- | --- |
| SUPPORTED (`proven`) | static assertion strength reaches 0.50 and at least one counted test has a strong assertion. Not a proof of correctness |
| WEAK (`weak`) | some support, but below the threshold, or no strong assertion |
| UNSUPPORTED (`unevidenced`) | little or no support, often no linked test |
| CONTRADICTED | a linked test failed |
| EXCLUDED | not scored (for example too vague to test) |

Short tags after the state (`tampered`, `flaky`, `unconfirmed`, `awaiting CI`, `weak link`, `stale evidence`, `needs typed evidence`, `author-supplied hint`) are flags that apply to that criterion.

## The comment

One comment per pull request, updated in place. Layout:

0. The alpha disclaimer (first visible line).
1. Heading with the verdict, for example `Radius verdict (v2 alpha): Not verified - insufficient evidence`.
2. A summary line: criteria supported, unsupported intent mass with its limit, intent coverage (with a note when it is below the minimum) and the evidence basis (`static assertion strength only (no mutation testing)`). If any criterion relies on an unconfirmed test hint the author supplied, a line says `N criteria rely on author-supplied test hints`.
3. `Why`: one sentence from the deciding rule, naming criteria as C1, C2, ...
4. A table of criteria: state, support against the threshold, and what evidence backs it, followed by the legend.
5. `What to do next`: concrete actions per criterion.
6. Collapsible sections: tamper findings, changed code with no stated criterion, per-criterion evidence (every factor that went into the support number), legacy v1 signals.
7. A footer with the algorithm version, profile, short commit id and a link to the dashboard.

A full example (fixture 08) is in `packages/github/tests/golden_verdict_v2/fixture_08_worked_example.md`.

The Check Run keeps the name `Radius confidence`. Its title always carries the caveat, for example `Radius v2 alpha - static evidence only - uncalibrated: Supported by static evidence (alpha) (2/2 criteria supported)`, and its summary starts with the disclaimer.

### Check Run conclusion mapping

`RADIUS_VERDICT_V2_CHECK_CONCLUSIONS` (worker setting; `advisory` default, `strict`; any other value means `advisory`):

| Verdict (deciding rule) | `advisory` (default) | `strict` |
| --- | --- | --- |
| `verified` (R4) | `neutral` | `success` |
| `failed` (R1a failing linked test, R1b failing CI cases, R1c high tamper) | `failure` | `failure` |
| `failed` (any other rule; none exists today) | `neutral` | `neutral` |
| `insufficient_evidence` (R2*) | `neutral` | `neutral` |
| `needs_review` (R3*) | `neutral` | `neutral` |
| pending CI results, or v2 unavailable | `neutral` | `neutral` |

In the default mode nothing is ever green: the alpha cannot satisfy a required check by itself. Only hard evidence turns the check red. `strict` is for operators who accept the limits below and want `verified` to be a green check.

## Who supplied the evidence (provenance and the author-hint cap)

The pull request author controls the description, a `.radius/intent.yml` in the PR, the tests they add and the `tests:` hints that point at them. So every criterion and every `tests:` / `paths:` hint carries a provenance tag in the payload (`criteria[].provenance`, `criteria[].hints[].provenance`):

| Tag | Meaning | Hint cap |
| --- | --- | --- |
| `author_pr_body` | from the PR title, description, commits, comments or linked issues | capped |
| `author_head_spec` | from `.radius/intent.yml` at the PR head, added or changed by the PR (or no base ref to compare) | capped |
| `base_spec` | from `.radius/intent.yml` identical on the base ref | not capped |
| `human_confirmed` | the criterion was confirmed or edited in the intent panel (authenticated API) | not capped |
| `llm_proposed` | proposed by the optional LLM extractor | capped |

The link strength of a `tests:` hint that is not `base_spec` or `human_confirmed` is capped at `author_hint_cap` (default 0.7; `LinkMapping.author_hint_cap`). A criterion that relies on a capped hint gets the flag and reason code `author_supplied_hint` and the comment says so. Confirm the criterion in the intent panel, or keep `.radius/intent.yml` on the base branch, to lift the cap. In the F-14 fixture harness the expected links are fed as hints on confirmed criteria, so gold results are unchanged (DEC-029); with the same hints marked `author_head_spec`, fixture 01 drops from `verified` to `insufficient_evidence`. The full threat model, what the cap does not stop and a recommended policy are in [docs/security/VERDICT_V2_THREAT_MODEL.md](security/VERDICT_V2_THREAT_MODEL.md).

## Limits and safety

- The comment is capped at 60,000 characters (GitHub allows 65,536). If a PR has more criteria or findings than fit, lists are cut with a "+N more, see the dashboard" line and low-priority collapsible sections are dropped with a notice.
- Everything that comes from the pull request (criterion text, test names, file paths, tamper reasons and code snippets) is escaped: @mentions, issue references, links, images, HTML and hidden or direction-changing characters cannot take effect, and long text is shortened.
- The comment carries two hidden markers: the v1 marker, so v1 and v2 update the same comment, and `radius-verdict-v2 rev=N digest=...`, so republishing identical content is skipped.

## Known limits of the alpha

- **Alpha, off by default.** The result is not calibrated and is not a probability; do not use it as a required check yet. The default Check Run conclusion is `neutral` for this reason.
- **Thresholds fitted to 8 fixtures.** `cap_static` 0.60 and `tau_support` 0.50 were chosen so the F-14 fixtures behave as designed; there is no held-out set, so no error rate is known.
- **The author controls much of the evidence.** See the provenance section and the threat model; an author who writes both trivial criteria and strong-looking tests still gets a supported verdict.
- **Static evidence only.** A test counts by the strength of its assertions, not by whether it would catch a bug (no mutation testing). A weak but passing test can never prove a criterion; a strong one still does not prove correctness.
- **Python only.** Behavioral changes in other languages give `Not verified` (analysis incomplete).
- **Dependencies offline.** A new dependency imported behind `try/except ImportError` that cannot be checked against a package registry is reported as a medium finding (`Needs human review`); only a registry that says the package does not exist (or a near-miss of a popular name) fails the PR. No registry adapter ships yet (DEC-028).
- **Linking without hints is conservative.** On the F-14 fixtures, auto-linking alone leaves a correct PR as `Not verified` because the matched tests get low relevance; adding `tests:` hints to `.radius/intent.yml` fixes it. The verified differences are listed in `apps/worker/tests/test_verdict_v2_acceptance.py` (`KNOWN_AUTO_DEVIATIONS`).
- **Not browser- or live-GitHub-validated** yet: the tests use a fake GitHub client and SQLite.

Per-case test results must be uploaded from CI. Linking a criterion to its tests is lexical unless you add `tests:` hints in `.radius/intent.yml`; a criterion with no linked test is reported as such, never credited. Thresholds are hypotheses that have not been calibrated, and `needs_review` is reached only through the rules above, not through a calibrated abstention band.

Design and rationale: `docs/research/design/VERDICT_V2_SLICE.md`.
