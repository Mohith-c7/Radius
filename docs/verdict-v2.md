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

**Wording.** The JSON contract keeps its internal values (`verified`, `proven`, ...), but everything a person reads says what the alpha actually measures. A comment starts with a one-line disclaimer ("Alpha - static evidence only - uncalibrated ... not a proof of correctness"), the internal state `proven` is shown as **SUPPORTED** (`unevidenced` as UNSUPPORTED), and the verdict `verified` is shown as **Supported by static evidence (alpha)**. Legend: *supported = static assertion strength above threshold; not a proof of correctness*. The API adds `alpha: true`, `calibrated: false`, `evidence_basis` and a `presentation` block with the same strings (`contract_version` `verdict-v2-contract-4`; all fields are optional additions).

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
| 5b | R2e | no in-scope criterion exists (none, or all excluded) and no behavioral code changed: reason `no_intent_criteria` ("no intent criteria were extracted; add a spec or confirm criteria"), or `not_applicable` when only documentation or inert files changed | Insufficient evidence (never `verified`; see DEC-031) |
| 6 | R2b | unproven intent mass above 0.20 | Insufficient evidence |
| 7 | R2c | less than 50% of the behavioral changes are covered by a stated criterion | Insufficient evidence |
| 8 | R2d | the analysis was incomplete (truncated, unsupported language, missing snapshot) | Insufficient evidence |
| 9 | R3a | an unwaived tamper finding at severity medium or above | Needs human review |
| 10 | R3b | a criterion counted as proven depends on a flaky test | Needs human review |
| 11 | R3c | a proven criterion rests on a weak criterion-to-code link (below 0.50) | Needs human review |
| 12 | R4 | none of the above | Supported by static evidence (alpha) (`verified`) |

With a repository policy that has `require` or `evidence` entries, two more rules sit between R2d and R3a: **P1** (a criterion or changed code under a required path is below the required state) and **P2** (a criterion has no counted test that is not agent-authored). Both give `Not verified - insufficient evidence`. Without such a policy the list is exactly the rules above (R2e included). See [Repository policy and waivers](policy.md).

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

A repository policy (`.radius/policy.yml` on the base branch, DEC-029) can set `mode`. Combined with the knob:

| Policy `mode` | `verified` | `failed` | `insufficient_evidence` / `needs_review` | pending CI |
| --- | --- | --- | --- | --- |
| none (default) | `neutral` (`strict` knob: `success`) | `failure` for R1a/R1b/R1c | `neutral` | `neutral` |
| `advisory` | `neutral` (`strict` knob: `success`) | `neutral` (never red) | `neutral` | `neutral` |
| `blocking` | `success` | `failure` | `failure` | `failure` (republished when CI results arrive) |

`blocking` is the repository's own opt-in to a required check, so it overrides the knob; an unavailable v2 result is always `neutral`. Policy `advisory` does not turn `verified` green by itself (DEC-030); that needs the `strict` knob.

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

The link strength of a `tests:` hint that is not `base_spec` or `human_confirmed` is capped at `author_hint_cap` (default 0.7; `LinkMapping.author_hint_cap`). A criterion that relies on a capped hint gets the flag and reason code `author_supplied_hint` and the comment says so. Confirm the criterion in the intent panel, or keep `.radius/intent.yml` on the base branch, to lift the cap. Confirming, editing or rejecting a criterion recomputes the stored verdict (next section). In the F-14 fixture harness the expected links are fed as hints on confirmed criteria, so gold results are unchanged (DEC-030); with the same hints marked `author_head_spec`, fixture 01 drops from `verified` to `insufficient_evidence`. The full threat model, what the cap does not stop and a recommended policy are in [docs/security/VERDICT_V2_THREAT_MODEL.md](security/VERDICT_V2_THREAT_MODEL.md).

With `.radius/policy.yml` on the base branch, `mode: blocking` maps every unverified result to `failure` (so a required check actually blocks) and `mode: advisory` never reports `failure`; the verdict is the same either way. The comment then shows a `Policy:` line (mode, source ref, number of settings applied) and a collapsible Policy section with the policy line each setting came from. Tamper findings accepted by a valid waiver are listed as `WAIVED` with the waiver id, owner, expiry and reason, and a Waivers section lists what was applied and what was ignored (expired, invalid). Details: [policy.md](policy.md).

## After a confirm, edit or reject (DEC-033)

The verdict is first computed when the analysis runs, from the criteria as they were then. A human decision in the intent panel (`PATCH /api/v1/analyses/{id}/intent/criteria/{criterion_id}`: confirm, edit, reject or reopen) changes the criterion state in the database; with the flag on (`shadow` or `on`) that successful call also leaves one request in the same republish outbox that CI uploads use (`verdict_v2_requests`, reason `intent_changed`), a few seconds in the future so that several quick decisions are scored once. The worker then, without a new clone:

- reads the current criterion states and applies them to the stored Stage A bundle: `confirmed` and `edited` criteria (and their `tests:` hints) become provenance `human_confirmed` (the author-hint cap no longer applies), an edit also updates the text, `rejected` criteria and their links are removed, and a criterion put back to `proposed` loses `human_confirmed` again;
- recomputes the `unconfirmed_inferred_intent` block (DEC-032) from the same states: it lifts only when no summary-mode criterion is left unconfirmed;
- re-scores Stage B and stores a new revision, if the inputs changed (an unchanged result stores nothing);
- with the flag `on` and a GitHub target, edits the existing PR comment and Check Run in place.

Safety: `human_confirmed` is never read from a request. The worker derives it from the stored criterion state, which only the authenticated, `write`-scoped intent API changes (a missing, read-only or other-organization key changes nothing and enqueues nothing; a body with extra fields is a 422). If the request cannot be written, or the recompute fails, the criterion change still succeeds: the failure is logged and the previous revision stays. While a request is queued, `GET .../verdict-v2` adds `meta.refresh_pending: true` (with `refresh_reason`, `refresh_attempts` and `refresh_failed` once the worker has failed at least once) and the dashboard shows that the verdict is out of date; after the dashboard's own confirm it re-reads the verdict a few times (about 30 seconds at most, widening intervals) until the new revision arrives. The worker retries a failing recompute with backoff and stops after 5 attempts; the request then stays queued, so the verdict stays marked stale until it is retried.

Limits: this is a state refresh, not a new analysis. Links between criteria and code are not recomputed, so a hint or text edited after the analysis does not create new links, a criterion that was rejected when the analysis ran is not brought back by reopening it, and a criterion added manually afterwards is not in the stored bundle. A new analysis (new commit) picks all of these up. Adding a criterion, submitting a source or rebuilding the intent does not trigger a recompute.

## Policy and waivers (VD-04, VD-05)

`.radius/policy.yml` and `.radius/waivers.yml` are read from the **base branch**, never from the pull request, so a PR cannot weaken its own rules or waive its own findings. They change thresholds within safe bounds, require criterion states per path, set tamper severities (lowering or disabling a `high` finding needs a recorded `allow_disable` reason), require a non-agent-authored test, exclude paths from coverage, and set advisory or blocking mode. A waiver is owned, expires (90 days at most), is shown as WAIVED, is stored in the verdict's audit record, and can never cover a contradicted criterion or a failed CI case. The API payload gains optional `policy`, `waivers`, `summary.tamper_waived` and `tamper_findings[].waived/.waiver` fields (contract 3). Full guide: [policy.md](policy.md); samples: `.radius/policy.example.yml`, `.radius/waivers.example.yml`.

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

## Optional: inferred criteria from ordinary PR text (`RADIUS_INTENT_EXTRACTION_MODE=summary`)

By default (`sections`) the extractor reads only acceptance-style sections, checklists, Gherkin and spec files, which finds nothing in typical PR descriptions. The worker setting `RADIUS_INTENT_EXTRACTION_MODE=summary` (default `sections`) also proposes criteria from a conventional-commit PR title and from behavioural bullets under Summary, Changes, What, Why or Description headings (DEC-032). They are the author's own words read by fixed rules, so they are `proposed`, weight 0.5, provenance `author_pr_body`, and show the `unconfirmed` flag. While any such criterion is unconfirmed the verdict cannot be `verified`: the analysis carries the blocking degraded reason `unconfirmed_inferred_intent` (rule R2d). Confirm or edit the criterion in the intent panel to lift it (the verdict is recomputed a few seconds later, see above). The mode is a recall experiment, not a measured improvement; see `docs/research/evaluation/EXTRACTION_SUMMARY_MODE.md`.
