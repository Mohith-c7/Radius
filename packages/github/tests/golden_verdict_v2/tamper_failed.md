<!-- radius-confidence-report -->
<!-- radius-verdict-v2 rev=1 digest=1fd0bfaf -->
**Alpha - static evidence only - uncalibrated.** Support is static assertion strength with thresholds fitted to a few fixtures. It is not a proof of correctness; do not treat it as a merge gate on its own.

## Radius verdict (v2 alpha): Failed

**0 of 2 stated criteria supported** | unsupported intent mass **1.00** (limit 0.20) | intent coverage **100%** | evidence: static assertion strength only (no mutation testing)

**Why:** 1 tamper finding(s) at severity high or above (T004). Radius treats changes like these as failures because they can hide a defect; see the tamper findings below.

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `criterion text c1` | UNSUPPORTED (tampered) | 0.00 / 0.50 | no linked test |
| C2 | `criterion text c2` | WEAK (tampered) | 0.20 / 0.50 | 1 test, strongest assertion strength 1.00 (strong); one test alone stays under the threshold |

_Legend: supported = static assertion strength above threshold; not a proof of correctness._

<details><summary>Tamper findings (1)</summary>

- `T004` **high** in `tests/test_a.py` (`test_a`): assertion weakened to \`is not None\` (before: `assert f(1) == 2`; after: `assert f(1) is not None`)

</details>

<details><summary>Per-criterion evidence</summary>

**C2** support 0.200 = 1 item. C2 is weak: support 0.20 is below the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong). A tamper finding touches its evidence.

- `test_c2`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.200

</details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | profile alpha-static (thresholds uncalibrated) | head `4f2a9d1`_
