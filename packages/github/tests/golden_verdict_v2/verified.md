<!-- radius-confidence-report -->
<!-- radius-verdict-v2 rev=1 digest=183f18ae -->
**Alpha - static evidence only - uncalibrated.** Support is static assertion strength with thresholds fitted to a few fixtures. It is not a proof of correctness; do not treat it as a merge gate on its own.

## Radius verdict (v2 alpha): Supported by static evidence (alpha)

**2 of 2 stated criteria supported** | unsupported intent mass **0.00** (limit 0.20) | intent coverage **100%** | evidence: static assertion strength only (no mutation testing)

**Why:** No rule found a problem. This rests on static assertion strength only; no mutation testing was run.

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `criterion text c1` | SUPPORTED | 0.73 / 0.50 | 1 test, strongest assertion strength 1.00 (strong) |
| C2 | `criterion text c2` | SUPPORTED | 0.60 / 0.50 | 1 test, strongest assertion strength 1.00 (strong) |

_Legend: supported = static assertion strength above threshold; not a proof of correctness._

<details><summary>Per-criterion evidence</summary>

**C1** support 0.730 = 1 item. C1 is supported by static evidence: support 0.73 meets the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong).

- `test_c1`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.730

**C2** support 0.600 = 1 item. C2 is supported by static evidence: support 0.60 meets the threshold 0.50. 1 linked test counted; strongest assertion strength 1.00 (strong).

- `test_c2`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80; freshness 1.0; link strength 0.90; contribution 0.600

</details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | profile alpha-static (thresholds uncalibrated) | head `4f2a9d1` | [details](https://dashboard.example/a/1)_
