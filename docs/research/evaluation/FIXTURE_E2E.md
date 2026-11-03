# Fixture end-to-end through the real services

Status: an engineering check, not a research result. It shows that the shipped pipeline
(webhook, worker poll loop, Verdict v2, API, PR comment and Check Run) reproduces, for the
eight F-14 fixtures, the verdicts in `docs/research/design/verdict_v2.fixture_expectations.json`,
except for the differences listed below. It says nothing about accuracy on real pull requests.

## What ran

`python scripts/smoke_e2e.py --all` (one process and one fresh PostgreSQL 16 database per
fixture; GitHub is the only fake). For each fixture the origin repository is built from the
fixture `base/` and `head/`; `.radius/intent.yml` with the fixture's gold links as hints is
committed on the base and the head (so the hints are `base_spec`); the PR is opened through a
signed webhook; the worker loop runs; the fixture's head test outcomes are uploaded as a JUnit
report through the API; the worker loop runs again; then every criterion is confirmed through
the intent API and the worker republishes. After the CI upload and again after the confirm the
served `GET /analyses/{id}/verdict-v2` is compared with the expectations file (verdict,
deciding rule, per-criterion state, S within 0.001, uim, intent coverage). Fixture 01 runs the
longer flow (summary-mode inferred criterion, confirm, failing-CI regression) and is compared
on verdict, rule, states and S after the confirm.

Differences from the gold harness (`test_verdict_v2_acceptance.py`): the real worker also runs
VS-04 test relevance next to the hints (gold turns relevance off), uses the real testability
rater, and has no package registry. Fixture runtimes below are wall-clock on one developer
machine (about 20 s each, 179 s for all eight).

## Result of the run (2026-11-03, all eight compared)

| Fixture | Expected (rule) | Observed (rule) | Match |
| --- | --- | --- | --- |
| 01 correct, strong tests | verified (R4) | verified (R4) | yes; S C1 0.740 vs 0.734, C2 0.621 vs 0.604 (documented) |
| 02 correct, weak tests | insufficient_evidence (R2b) | insufficient_evidence (R2b) | yes; S C2 0.014 vs 0.0 (documented) |
| 03 incorrect, weak tests | insufficient_evidence (R2b) | insufficient_evidence (R2b) | yes, states and S within 0.001 |
| 04 test tampering | failed (R1c) | failed (R1c) | yes; already failed before CI results |
| 05 scope creep | insufficient_evidence (R2c) | insufficient_evidence (R2c) | yes |
| 06 hallucinated dependency | failed (R1c) | needs_review (R3a) | no, documented offline variant |
| 07 vague intent | insufficient_evidence (R2a) | insufficient_evidence (R2a) | verdict yes; C2 state, uim, coverage differ (documented) |
| 08 multi-criterion partial | insufficient_evidence (R2b) | insufficient_evidence (R2b) | yes, states and S within 0.001 |

Check Run conclusion was `failure` for 04 (R1c) and `neutral` for the others except that 06 is
`neutral` (R3a). Each PR got exactly one comment and one Check Run, edited in place after the CI
upload and after the confirm. An idle worker made no further GitHub calls.

## Differences, with causes

* 01 and 02, S only. The real worker adds VS-04 relevance to the hints. In 01 a further test
  (`test_discount_rejects_negative_percent`, relevance 0.15) adds to C1 and C2; in 02 a lexical
  link on the word "address" gives the test-less C2 S = 0.014. States and verdicts are unchanged.
  The expectations file already lists the 02 link as a fixture disagreement.
* 06. The worker has no package registry, so the guarded import is `unverified_guarded_import`
  (medium) and the verdict is `needs_review` by R3a. That is the `offline_registry_variant` of the
  expectations file and DEC-028. The `failed` outcome with a registry was not exercised through the
  real services (no registry is wired into the worker); it is covered only by the acceptance test
  with a static registry.
* 07. The testability rater lists "faster" among vague adjectives, so "report generation is
  faster" is rated vague and excluded, while the fixture labels it non-functional (unevidenced).
  All criteria are excluded, so uim and coverage are 0 instead of 1. The verdict is still
  insufficient_evidence by R2a. Whether the rater or the fixture label is right is a judgement
  call (the sentence has no threshold); no code was changed.

## Findings

No product defect was found by this run: no verdict, rule or state differed unexplained. One
observation, not a bug: when a confirm changes nothing visible in the rendering (07, every
criterion excluded), the stored verdict gets a new revision but the PR comment keeps its older
marker revision, because the publisher skips an unchanged rendering. The smoke allows that case.

## Limits

Gold links are supplied as hints in `.radius/intent.yml`; criteria extraction from PR text and
the API "add criterion" path are not exercised for these fixtures. Test execution is off (CI
results are uploaded). No real GitHub, browser or dashboard. One run each, on one machine; the
timings are not a benchmark.

## Running

`python scripts/smoke_e2e.py` (fixtures 01 and 04, about 50 s, the required CI check),
`--fixture 03` or `--all`. `.github/workflows/smoke.yml` runs `--all` weekly and on manual dispatch only.
