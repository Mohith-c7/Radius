<!-- radius-confidence-report -->
<!-- radius-verdict-v2 rev=2 digest=04cf8753 -->
## Radius verdict (v2 alpha): Not verified - insufficient evidence

**1 of 4 stated criteria proven** | unproven intent mass **0.75** (limit 0.20) | intent coverage **100%** | evidence: static assertion strength only (no mutation testing)

**Why:** 3 of 4 criteria are below the support threshold 0.50 (C2, C3, C4), so the unproven intent mass 0.75 exceeds 0.20. Passing tests alone are not enough: an unproven criterion is checked weakly or not at all.

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `a password needs at least 8 characters` | PROVEN | 0.60 / 0.50 | 2 tests, strongest assertion strength 1.00 (strong) |
| C2 | `a password needs at least one digit` | WEAK | 0.43 / 0.50 | 1 test, strongest assertion strength 1.00 (strong); one test alone stays under the threshold |
| C3 | `a password needs at least one uppercase letter` | UNPROVEN | 0.14 / 0.50 | 1 test, strongest assertion strength 0.20 (weak) |
| C4 | `a password must not be on the common-password list (case-insensitive)` | UNPROVEN | 0.00 / 0.50 | no linked test |

### What to do next
1. **C4**: No test checks the common-password rule. Add a test that a listed password is rejected, in a different letter case, or add a tests hint in .radius/intent.yml.
2. **C3**: test_uppercase_rule_runs would pass for any boolean result. Assert the exact value for a password without an uppercase letter.
3. **C2**: Add a second case for the digit rule, or a boundary case.

<details><summary>Per-criterion evidence</summary>

**C1** support 0.604 = 2 items. C1 is proven: support 0.60 meets the threshold 0.50. 2 linked tests counted; strongest assertion strength 1.00 (strong).

- `test_rejects_seven_characters`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.432
- `test_accepts_eight_characters`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.302

**C2** support 0.432 = 1 item. C2 is weak: support 0.43 is below the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong).

- `test_rejects_missing_digit`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.432

**C3** support 0.144 = 1 item. C3 is unproven: support 0.14 is below the threshold 0.50. 1 linked test counted; strongest assertion strength 0.20 (weak).

- `test_uppercase_rule_runs`: outcome passed; assertion strength 0.20; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.144

</details>

<details><summary>Legacy v1 signals (file-level selection, uncalibrated heuristic score)</summary>

Verification status `insufficient_evidence`; heuristic confidence score 40.0 (uncalibrated, not a probability); risk level `medium`.

</details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | profile alpha-static (thresholds uncalibrated) | head `4f2a9d1` | [details](https://dashboard.example/analyses/5b0b9c6e-0000-4000-8000-000000000008)_
