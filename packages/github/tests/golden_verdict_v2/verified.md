<!-- radius-confidence-report -->
<!-- radius-verdict-v2 rev=1 digest=3f77b60e -->
## Radius verdict (v2 alpha): Verified

**2 of 2 stated criteria proven** | unproven intent mass **0.00** (limit 0.20) | intent coverage **100%** | evidence: static assertion strength only (no mutation testing)

**Why:** No rule found a problem. This rests on static assertion strength only; no mutation testing was run.

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `criterion text c1` | PROVEN | 0.73 / 0.50 | 1 test, strongest assertion strength 1.00 (strong) |
| C2 | `criterion text c2` | PROVEN | 0.60 / 0.50 | 1 test, strongest assertion strength 1.00 (strong) |

<details><summary>Per-criterion evidence</summary>

**C1** support 0.730 = 1 item. C1 is proven: support 0.73 meets the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong).

- `test_c1`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.730

**C2** support 0.600 = 1 item. C2 is proven: support 0.60 meets the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong).

- `test_c2`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.600

</details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | profile alpha-static (thresholds uncalibrated) | head `4f2a9d1` | [details](https://dashboard.example/a/1)_
