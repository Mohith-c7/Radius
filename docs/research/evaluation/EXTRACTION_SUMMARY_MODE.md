# Summary extraction mode: what it finds on this repository's own PRs

**Status: engineering sanity check, NOT a research result.** One rater (the author of the change), author-written text from one repository (this one, largely written with an AI assistant), no ground truth, no gold set, no confidence intervals. Do not cite the numbers as accuracy.

Decision: DEC-032. Mode: `RADIUS_INTENT_EXTRACTION_MODE=summary` (default `sections`). Rules and caps: `packages/intent/src/radius_intent/infrastructure/extraction/summary.py`.

## Setup

- Input: the 29 merged PRs of the 2026-11 replay (`REPLAY_2026-11.md`), title and body read from the local replay metadata cache (no network, nothing written to the repository). The text passes through the product source sanitiser (`pull_request_outcomes`) before extraction.
- Tool: `python scripts/intent_summary_eval.py --meta-dir <cache>` (reads `meta-<n>.json`).
- Mode comparison: `sections` (current product) vs `summary`.

## Recall proxy: criteria per PR

| Mode | PRs with at least 1 criterion | Total criteria | Max per PR |
| --- | --- | --- | --- |
| `sections` | 0 of 29 | 0 | 0 |
| `summary` | 12 of 29 | 19 | 4 |
| (reference) `bullets` sensitivity pass, REPLAY | not stated per PR | 83 | 15 cap |

"Criteria per PR" is a proxy for recall only in the sense of "is the intent layer empty". It says nothing about whether the right criteria were found. The 17 PRs with none are mostly docs, CI and chore PRs whose titles are not `feat|fix|perf` and whose bodies have no Summary bullets that read as behaviour, plus PRs whose bullets are noun phrases.

## Precision: manual spot-check of all 19 criteria

Judged by one person, "would a reviewer accept this as a plausible, testable statement of what the PR is meant to do". Good = yes; borderline = true statement but structural, compound or not behaviour a test would check; bad = not a behavioural intent.

| # | PR | Rule | Criterion (truncated) | Label |
| --- | --- | --- | --- | --- |
| 1 | 18 | lead_verb | Remove NEXT_PUBLIC_RADIUS_API_KEY; add /api/radius/* server proxy with path/method allowlist... | good |
| 2 | 18 | marker | Middleware requires a session cookie in production | good |
| 3 | 18 | title | keep the API key server-side behind a proxy (F-05) | good |
| 4 | 28 | lead_verb | Fixes two small defects: GITHUB_SINGLE_TENANT was never passed to the API in compose... | good |
| 5 | 35 | marker | Default branch no longer hardcoded to main: corrected from push/PR deliveries... | good |
| 6 | 35 | marker | Worker publishes an in-progress Check Run at job start... | good |
| 7 | 40 | marker | uv.lock re-locked against pyproject.toml (uv lock --check passes; adds ...) | bad |
| 8 | 40 | marker | Root conftest.py clears env_file on the settings classes so tests no longer depend on a developer's .env | good |
| 9 | 40 | lead_verb | Removes the unused TraceCarrierStore / TRACE_CARRIERS... | borderline |
| 10 | 40 | title | refresh uv.lock, make settings/tests independent of a local .env, drop unused trace carrier | good |
| 11 | 51 | marker | New workflows: CodeQL (...), OpenSSF Scorecard (...) | borderline |
| 12 | 82 | marker | Next.js 15.5.22 -> 15.5.28 (fixes 3 critical + highs...) | bad |
| 13 | 82 | title | patch Next.js and transitive JS advisories (0 critical/high), tune Dependabot | borderline |
| 14 | 84 | title | accept comma-separated scopes in the commit check | good |
| 15 | 87 | marker | container-scan.yml: builds images (no push) and runs Trivy (pinned) on Dockerfile/dependency PRs... | borderline |
| 16 | 91 | marker | Dashboard: per-request nonce CSP (...) and static security headers; pages now render per request | good |
| 17 | 102 | marker | Storage: HMAC-SHA256 fingerprint with a server-side pepper (...)... | good |
| 18 | 103 | marker | docker-compose.yml now forwards the HTTP-hardening, flag and sign-in/SMTP variables... | good |
| 19 | 105 | marker | docs/integrations/github-action.md with recommended permissions, pytest/jest/maven examples... | bad |

Tally: 12 good, 4 borderline, 3 bad. Precision 12/19 = 63% strict, 16/19 = 84% counting borderline. Wide uncertainty (n = 19, one rater, who also wrote the heuristic).

An earlier version accepted every conventional-commit title. Of its 27 criteria 16 were good, 6 borderline and 5 bad, and most of the borderline and bad ones were noun-phrase titles ("Verdict v2 alpha - per-criterion verdict, store, API, ..."). Titles now go through the same verb/modal/marker heuristic, which removed 8 criteria (including some good ones such as "HTTP hardening ...", which have no leading verb). That change was made after seeing these 27, so the 63% is not an out-of-sample figure.

## Recurring failure modes

- A marker word matched in a descriptive sentence ("adds defusedxml" in a lockfile note, "fixes 3 critical" in a version bump): dependency, lockfile and docs bullets pass as behaviour.
- Compound bullets (several claims joined by `;`) become one criterion; the testability rater later treats them as one.
- Bullets that are noun phrases without a verb ("Tests: lifecycle, scopes, ...", "Managed keys (...): create, list, rotate") are skipped, which is a recall loss by design.
- Continuation lines of a bullet are not read; headings other than the listed ones are ignored.

## F-14 fixtures and the gold harness

`scripts/intent_eval.py` run with the `deterministic` extractor in both modes (new `mode` option) on the 8 F-14 fixtures (18 gold criteria, synthetic, harness exercise only): identical in both modes (precision 1.00, recall 0.11, 2 of 2 predictions matched). The fixtures have no conventional titles and no Summary-style headings, so the new mode adds nothing there. This shows the mode does not disturb acceptance-style inputs; it does not show it helps. There is no real gold set in the repository (`benchmarks/gold/README.md`), so a real precision/recall measurement is still open (IN-09/IN-10).

## Downstream effect (replay, summary mode)

Replayed with `scripts/verdict_v2_replay.py --intent-mode summary` semantics on the pre-R2e base (`aeec856`). The run was stopped because the machine was low on memory: **22 PRs completed** (PR 100 timed out; 6 PRs were not reached). It also ran with the earlier title rule that accepted every conventional title, so its criteria counts are somewhat higher than the 19 above. Verdicts are compared against the deterministic column of `REPLAY_2026-11.results.json` for the same PRs, where present.

| Verdict (22 completed PRs) | summary mode |
| --- | --- |
| verified | 7 (all with 0 criteria: the vacuous `verified` that DEC-031 later closed) |
| insufficient_evidence | 8 |
| failed | 7 (decided by tamper rule R1c, independent of intent) |

Observed changes against the deterministic run: PRs 82 (`verified` to `insufficient_evidence` by R2b), 28 and 84 (R2a to R2b), 18 (no deterministic result to compare). In every changed case summary mode made the verdict equal or more cautious; it never turned a non-verified verdict into `verified`, which is the intended property (and in addition guaranteed by the `unconfirmed_inferred_intent` block, which was not the deciding rule in any of these PRs). The replay does not exercise that block. It is covered by `apps/worker/tests/test_verdict_v2_summary_mode.py`. The run has not been repeated after merging DEC-031 (R2e).

## Honest limits

- Author-written text from one team and one style; a different repository's PR habits will behave differently.
- The criteria are the author's own claims. A criterion that is "supported" means the PR's tests touch the code the claim names, not that the claim is true.
- No ground truth, one rater, heuristics tuned after looking at this same sample.
- Weight 0.5 is a label of low extraction confidence; the evidence package does not weight coverage by it.
