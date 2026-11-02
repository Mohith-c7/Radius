# Evidence features: assertion strength, freshness, independence

Implemented in `packages/evidence` (`radius_evidence`) for the Verdict v2 alpha. Design: `docs/research/design/VERDICT_V2_SLICE.md` (3.3, 3.5, 3.6), DEC-027. All values are hypotheses of the `alpha-static` profile, not results; every weight lives in `QualityConfig` and is part of the config digest.

## `a_static` (EV-06)

`a_static(features) = max over assertion facts of table[kind]`, in [0, 1].

| Kind | Weight | Rationale |
| --- | --- | --- |
| `value_equality` | 1.00 | Pins the exact computed value; fails when the behavior changes. |
| `approx_equality` | 0.90 | Exact up to a tolerance. |
| `exception_type_message` | 0.90 | Specific exception and message. |
| `exception_type` | 0.80 | Specific exception, message unchecked. |
| `membership`, `comparison_bound` | 0.35 | Accepts many wrong values (`<= 10`, `in [...]`). |
| `length_check`, `snapshot` | 0.30 | Shape only, or unreviewed golden output. |
| `truthiness`, `none_check` | 0.25 | Passes for almost any return value. |
| `mock_called`, `type_check` | 0.20 | Checks interaction or type, not behavior. |
| `tautology`, `no_assertion`, `other` | 0.00 | Cannot fail, or unknown. |

Why `max`: one strong assertion is a real constraint on the code under test; weak assertions around it do not weaken it. Adding a weaker fact never changes the score, so the score is monotone in each table entry.

Edge cases (a test with no facts scores `no_assertion` unless `expects_exception`, which scores `exception_type` with reason `exception_only`):

| Situation | Handling |
| --- | --- |
| `mock_only` (subject derives only from a mock created in the test) | LK-04 record becomes kind `mock_called` (0.20) |
| `circular` (expected computed by the same callee), `dead`, `swallowed` (inside `except AssertionError`) | kind `tautology` (0.00); the feature is kept as a note and reason code |
| `in_loop`, `property_based`, helper use, snapshot | score unchanged; reason codes `assertion_in_loop`, `property_based`, `via_helper`, `snapshot_only` |
| `has_skip_marker` | scored, reason `skip_marker`; the outcome is `SKIPPED` so `q` is 0 |
| parametrized | reason `parametrized`; no score change |
| unknown kind string | 0 (never optimistic) |

LK-04 to kind mapping lives in `domain/assertion_records.py` (plain dicts in, no `radius_testing` import): equality -> `value_equality`, approx -> `approx_equality`, exception with `match` -> `exception_type_message`, specific exception -> `exception_type`, broad exception -> `truthiness`, membership/regex/quantified -> `membership`, comparison -> `comparison_bound`, length -> `length_check`, identity/disjunction -> `truthiness`.

`cap_static` (0.6 in `alpha-static`) is applied by EV-08 as `d_eff = min(cap_static, a_static)`, not here.

## Freshness (EV-07)

`f = 1` when the item's bound SHA equals the current head SHA; `0` with reason `stale_sha` otherwise; `0` with reason `unbound` when the SHA is missing or not 40 lowercase hex. Optional decay hook (`FreshnessConfig.decay_enabled`, default off): for an item bound to an older commit, if no covered file (the test file and the files of the symbols it exercises) has a different git blob hash, `f = unchanged_factor ** commits_behind` (default 0.8); if any covered file changed or is missing, `f = 0`. Staleness is monotone: more changed files or more commits behind never raise `f`. `partition_by_freshness` returns the ignored (`f = 0`) items for audit.

## Independence, lite (EV-03-lite, `indep-lite-1`)

| Case | Factor |
| --- | --- |
| Test pre-existing and unchanged in the PR | 1.0 |
| Changed in the PR, author attested human | 1.0 |
| Changed in the PR, PR carries an agent trailer | 0.6 |
| Changed in the PR, no authorship signal | 0.8 |

Reason codes: `pre_existing_unchanged`, `test_added_in_pr`, `test_modified_in_pr`, `agent_trailer`, `human_attested`, `author_unknown`, and `implementation_changed_in_pr` (informational: the code under test changed in the same PR; the lite factor does not change). Agent trailers are detected by case-insensitive substring match with whitespace collapsed; default patterns: `co-authored-by: claude`, `co-authored-by: copilot`, `generated with [claude code]`, `[bot]`. The signal is per PR, so it under-weights agent PRs without trailers (decision D13). Independence discounts support, never a failure.
