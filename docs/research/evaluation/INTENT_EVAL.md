# Intent extraction metrics harness (IN-10, RQ1)

Status: **harness ready; real numbers pending IN-09** (the human-annotated gold set). Everything the harness has produced so far comes from synthetic cases and the F-14 golden fixtures and is labelled `SYNTHETIC - not a research result`. No number in this repository is a result for the paper.

The harness is the EP-05 piece for RQ1 extraction: it runs the production extraction code (`DeterministicCriterionExtractor`, `LlmCriterionExtractor`, the production merge and the production testability rater) over a gold set and reports precision, recall and F1 with seeded cluster-bootstrap intervals. Code: `packages/intent/src/radius_intent/evaluation/`; CLI: `scripts/intent_eval.py` (or `python -m radius_intent.evaluation`).

## How to run

```bash
# from the repository root; PYTHONPATH as in CI, or use scripts/intent_eval.py which sets it
python scripts/intent_eval.py list-extractors
python scripts/intent_eval.py run --config benchmarks/configs/intent_synthetic.json
python scripts/intent_eval.py run --config benchmarks/configs/intent_f14_fixtures.json
python scripts/intent_eval.py report benchmarks/results/intent/<run-id>            # re-render
python scripts/intent_eval.py compare RUN_A RUN_B --a-extractor combined --b-extractor deterministic
```

`run` prints the markdown report and writes `benchmarks/results/intent/<run-id>/` (git-ignored): `run.json` (full record incl. per-PR count vectors), `report.json` (manifest + metrics, no per-PR data), `report.md`, and for recording providers `<extractor>.llm_recordings.json`. Default run id: `<name>-<config sha[:8]>-<dataset sha[:8]>`. Overrides: `--gold`, `--adapter`, `--seed`, `--resamples`, `--run-id`, `--out-root`. A small SYNTHETIC example report is committed at `docs/research/evaluation/examples/synthetic_report.md`.

CI runs only the unit and end-to-end tests (`packages/intent/tests/test_eval_*.py`), which use 20-50 resamples. The preregistered 10,000 resamples take roughly half a minute per extractor on 150 PRs.

## Extractors and options

`list-extractors` prints the registry. Kinds: `deterministic` (`det-extract-v1`), `llm` (the guarded IN-04 extractor alone, prompt `intent-extract-llm-v1`), `combined` (deterministic criteria plus LLM proposals through the production `merge_proposals`), and two sanity baselines `oracle` (returns the gold; F1 must be 1) and `null` (returns nothing; recall must be 0). Testability is rated with the production `rate_criteria` (`testability-rules-v1`) unless `rate_testability` is false.

LLM providers (`provider.type`): `fake-lines` (offline stand-in that quotes each substantive line; exercises the full guarded path), `replay` (answers from a recordings file keyed by a hash of the source blocks, independent of the per-call nonce) and `anthropic` (real network). **The real provider is opt-in twice**: the config alone can never use it. It needs `--allow-real-llm` on the command line AND `RADIUS_EVAL_ALLOW_REAL_LLM=1` in the environment AND `ANTHROPIC_API_KEY`; otherwise `run` exits with code 2 before any call. Real runs record every response so they can be replayed offline (`replay`) and reproduced without spend; token usage per extractor is reported and an optional `price_per_mtok: [in, out]` in the config turns it into a cost estimate. Tests and CI never enable the real provider.

## Experiment config (JSON)

```json
{
  "name": "synthetic-smoke",
  "seed": 20261102,
  "gold": {"path": "packages/intent/tests/fixtures/evaluation/synthetic_gold.json", "adapter": "native"},
  "matching": {"iou_threshold": 0.5, "text_threshold": 0.8},
  "bootstrap": {"resamples": 1000, "confidence": 0.95},
  "rate_testability": true,
  "extractors": [
    {"id": "deterministic", "kind": "deterministic"},
    {"id": "combined", "kind": "combined", "provider": {"type": "replay", "recordings": "recordings.json"}}
  ]
}
```

Defaults are the preregistered values: master seed 20261102, IoU 0.5 (PREREGISTRATION 5.1, "initial guess"), 10,000 resamples (section 2), 95% percentile intervals. Unknown keys are rejected. The config hash covers the effective values after CLI overrides. Paths in `gold.path` resolve against the working directory, then the config file's directory.

## Gold contract (`radius.intent.gold/1`)

Schema: `docs/research/evaluation/intent_gold.schema.json`; validator: `radius_intent.evaluation.gold.parse_gold` (reports every error, with JSON paths). Per case (= one PR = one bootstrap cluster): `sources` (`source_id`, `kind`, `text`), `criteria` (`id`, `span`, optional `alt_spans`, `testability`, `text`), `well_specified`, `author_type`, `group`. A PR with `criteria: []` is a "no gold" PR. Spans are half-open code-point ranges into the source text (the unit of `radius_intent.domain.Span`); `offset_unit: "utf16"` or `"utf8"` is converted on load (offsets that split a character are errors). Compound or duplicated requirements: two gold items may share a span (the harness warns, and matching then needs two predictions); `alt_spans` lists other acceptable annotations of one criterion, including the same requirement stated in another source. Gold testability uses the five IN-05 categories (legacy `testable`/`vague`/`non_functional` accepted; `unrated` is not a label).

Loaders: `native` (a JSON file, or a directory of case files plus an optional `dataset.json` header) and `f14-fixtures` (derives a SYNTHETIC gold from `benchmarks/fixtures/intent`: the fixtures have criterion text but no spans, so each criterion is aligned to the list item or paragraph of `intent.md` with the best token overlap, and criteria that cannot be aligned are dropped and noted). The dataset hash is the SHA-256 of the canonical normalized content (case order does not matter); the SHA-256 of the files themselves is recorded as well.

### Plugging in the real gold (IN-09)

IN-09 owns the annotation format (`benchmarks/gold/`, `scripts/gold_*.py`). When it lands, write a small adapter that maps its files to the dict above and select it by import path (`module:function`; `scripts/` is on `sys.path` when the CLI is started as `python scripts/intent_eval.py`); nothing else changes:

```python
# scripts/in09_adapter.py (example; any importable module works)
from pathlib import Path
import json

def adapt_in09(path: Path) -> dict:
    cases = []
    for f in sorted(path.glob("pr_*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        cases.append({
            "case_id": raw["pr_id"],
            "well_specified": raw["well_specified"],
            "author_type": raw["author_kind"],
            "sources": [{"source_id": s["id"], "kind": s["kind"], "text": s["text"]} for s in raw["sources"]],
            "criteria": [{"id": c["id"], "span": {"source_id": c["source"], "start": c["start"], "end": c["end"]},
                          "testability": c.get("testability")} for c in raw["adjudicated"]],
        })
    return {"schema": "radius.intent.gold/1", "name": "radius-intent-gold", "version": "1", "split": "test",
            "synthetic": False, "offset_unit": "codepoint", "cases": cases}
```

```bash
python scripts/intent_eval.py run --config exp.json --gold benchmarks/gold --adapter in09_adapter:adapt_in09
```

Checklist for the adapter: use the adjudicated annotations only; copy the sanitized source text the offsets index into (the text the extractor sees); set `well_specified` from the annotators' pre-annotation judgement; keep `synthetic: false` only for the real set; set `split` to `dev` or `test` and never tune on `test`. Where source text cannot be redistributed, the adapter must fetch/reconstruct it by reference and hash (IN-09), the harness only needs the resulting dict. If IN-09 stores UTF-16 or byte offsets, set `offset_unit` instead of converting by hand.

## Matching (PREREGISTRATION 5.1)

A predicted criterion matches a gold criterion when their spans in the same source have character IoU >= 0.5 (configurable, inclusive). With `alt_spans`, the best-overlapping span of the gold item counts. Matching is **one-to-one and greedy**: candidate pairs are ordered by score descending, then predicted index, then gold index, and taken when both are free. This is deterministic and order-independent; it can in rare crossing cases find fewer matches than an optimal assignment (documented limitation; same rule as the IN-03 hook). Touching spans (`[0,5)` and `[5,9)`) have IoU 0. A prediction can never be credited twice, so a prediction that spans two gold items matches one of them, and a duplicated gold item needs two predictions.

Secondary text modes use the criterion text (the extractor's statement) against the annotator's `text` and the span texts, inside the same source: `text_exact` (NFKC, casefolded, whitespace-collapsed equality) and `text_fuzzy` (token Jaccard >= 0.8).

## Metrics

Names are `{mode}.{group}.{metric}` with `mode` in `iou` (primary), `text_exact`, `text_fuzzy`; groups: `all`, `well_specified`, `not_well_specified`, `kind:<source kind>` (per source type), `author:<type>`.

| Metric | Definition |
|---|---|
| `precision`, `recall`, `f1` (micro) | counts pooled over PRs: matched predictions / predictions; matched gold / gold; 2 tp / (pred + gold). Undefined ratios are `n/a`; F1 is 0 when there is gold or a prediction and nothing matches (an empty extractor has recall 0, F1 0, precision `n/a`). |
| `macro_precision`, `macro_recall`, `macro_f1` | mean of the per-PR value over PRs with predictions (precision) or with gold (recall, F1); a PR with gold and no predictions has F1 0. This is the "per-PR macro" the plan asks for. |
| per source type | the same, restricted to criteria whose source has that kind (gold attributed by its primary span, predictions by their source). |
| `tx.accuracy`, `tx.macro_f1`, `tx.kappa`, confusion matrix | over primary (IoU) matches whose gold has a testability label; predicted `unrated` is a separate column and counts as an error (`tx.abstain_rate`). Macro-F1 averages the labels present in gold or predictions; kappa is Cohen's kappa of gold vs system labels. |
| `abstention.empty_prediction_rate` | share of PRs with no predicted criterion. |
| `coverage.any_hit_rate` | share of PRs with gold where at least one gold criterion was matched. |
| `nogold.share`, `nogold.fp_rate`, `nogold.mean_predictions` | share of PRs with no gold; among them the share that got at least one prediction; mean predictions there. |
| `span.mean_iou`, `span.exact_rate` | mean IoU and share of exact boundaries among primary matches. |

## Statistics (PREREGISTRATION 2 and 5.4)

Cluster (PR) bootstrap with percentile intervals: each replicate draws PRs with replacement (`random.Random(seed)`, clusters in sorted case-id order), sums the per-PR count vectors and recomputes every metric, so micro ratios and per-PR macro means are resampled at the PR level. Intervals are linear-interpolation percentiles; replicates where a metric is undefined are dropped (`n_valid` is stored). Same seed and data give bit-identical intervals; every extractor in a run uses the same seed, hence the same resamples.

`compare` is the paired version: both runs' per-PR vectors are aligned on case id (a different dataset hash is an error unless `--allow-dataset-mismatch`, then only shared PRs count), each replicate applies the same drawn PRs to both extractors, and `metric(A) - metric(B)` gets a percentile interval plus an approximate two-sided bootstrap p-value (floored at 1/(resamples+1)) for the Holm step of the analysis plan. It is not an exact test; confirmatory claims follow PREREGISTRATION 5.4 (Holm over the confirmatory family). The McNemar test for H1c belongs to the linking harness and is not part of IN-10.

## Reproducibility checklist (EP-05)

Every `run.json` manifest records: config (and its SHA-256), seeds, dataset name/version/split and content SHA-256 plus file hash, gold adapter, git commit and dirty flag, extractor versions (`det-extract-v1`, `testability-rules-v1`, LLM prompt `intent-extract-llm-v1` and model id), harness version (`intent-eval-v1`), Python/platform, per-extractor timing, LLM calls/cache hits/tokens (and optional cost), per-extractor errors, and the synthetic label. To reproduce a table: check out the recorded commit, point at the same gold (hash must match), run the same config with the same seed (`report` re-renders from `run.json` without recomputation); for LLM extractors replay the stored recordings. Before reporting a number: confirm `dirty` is false, the dataset hash equals the frozen manifest, kappa of the gold is reported first (PREREGISTRATION 5.4), and the split is `test` and was not used for tuning.

## Known limitations

* Greedy one-to-one matching (see above); text modes are token based and English-centric.
* Gold spans are compared in the sanitized source text the extractor receives; if upstream sanitization changes offsets the adapter must use the sanitized text.
* `well_specified` is taken from the gold file; the harness does not infer it.
* The F-14 derived gold is approximate, tiny and not human annotated; on it the deterministic extractor misses most bullets because the fixtures have no "Acceptance criteria" heading. That is a property of the fixtures, not a finding.
* Linking (Top-3, MRR), the 10% manual audit of matches and the annotation-agreement statistics are out of scope for IN-10.
