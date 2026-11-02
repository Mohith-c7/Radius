# Intent extraction metrics: synthetic-example

> **SYNTHETIC — not a research result.** This run used synthetic or fixture-derived data and exists only to exercise the harness.

## Run

- Dataset: `synthetic-demo` v1 (synthetic), 10 PRs, 18 gold criteria, 2 PRs without gold
- Dataset sha256: `1ab13d3aefdcb748cbd074c28da04a431a33e51f56988db3ea81c61932d75b86`
- Config sha256: `421b047c833dbd4eb7b51c879c60f74f17ca3eacd4ffae0678e414b0297f67ac`
- Matching: IoU >= 0.5, fuzzy text Jaccard >= 0.8
- Bootstrap: 1000 cluster (PR) resamples, 95% percentile intervals, seed 20261102
- Git: `c04ca824dda9159ef66056bd33efc7cd5be849d7`
- Harness: `intent-eval-v1`; created 2026-11-02T12:27:55.377845+00:00

### Dataset notes

- Hand-made synthetic cases for exercising the IN-10 harness; not annotated PRs and not a research result.
- $.cases[6][pr-007-compound]: criteria 'C1' and 'C2' share a span (compound/duplicate gold; one-to-one matching needs two predictions)

## Summary (primary: span IoU, micro over PRs, 95% CI)

| Extractor | Precision | Recall | F1 | F1 (fuzzy text) | Testability acc. | Empty-PR rate |
|---|---|---|---|---|---|---|
| `deterministic` | 1.000 [1.000, 1.000] | 0.889 [0.692, 1.000] | 0.941 [0.818, 1.000] | 0.941 [0.818, 1.000] | 0.875 [0.750, 1.000] | 0.300 [0.000, 0.600] |
| `llm-fake` | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.723 [0.571, 0.846] | 0.882 [0.765, 1.000] | 0.000 [0.000, 0.000] |
| `combined-fake` | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.723 [0.571, 0.846] | 0.882 [0.765, 1.000] | 0.000 [0.000, 0.000] |
| `sanity-oracle` | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.200 [0.000, 0.400] |
| `sanity-null` | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | n/a | 1.000 [1.000, 1.000] |

## Extractor `deterministic` (deterministic)

### Matching modes (all PRs)

|  | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| span IoU (primary) | 1.000 [1.000, 1.000] | 0.889 [0.692, 1.000] | 0.941 [0.818, 1.000] | 0.850 [0.575, 1.000] | 16/16/18 |
| normalized text equality | 1.000 [1.000, 1.000] | 0.889 [0.692, 1.000] | 0.941 [0.818, 1.000] | 0.850 [0.575, 1.000] | 16/16/18 |
| token Jaccard (fuzzy) | 1.000 [1.000, 1.000] | 0.889 [0.692, 1.000] | 0.941 [0.818, 1.000] | 0.850 [0.575, 1.000] | 16/16/18 |

### Per source type (span IoU)

| Source type | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| agent_prompt | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 3/3/3 |
| commit_message | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1/1/1 |
| issue | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 2/2/2 |
| pr_body | 1.000 [1.000, 1.000] | 0.833 [0.500, 1.000] | 0.909 [0.667, 1.000] | 0.760 [0.333, 1.000] | 10/10/12 |

### Per PR slice (span IoU)

| Slice | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| not_well_specified | 1.000 [1.000, 1.000] | 0.500 [0.000, 1.000] | 0.667 [0.000, 1.000] | 0.500 [0.000, 1.000] | 1/1/2 |
| well_specified | 1.000 [1.000, 1.000] | 0.938 [0.812, 1.000] | 0.968 [0.897, 1.000] | 0.967 [0.900, 1.000] | 15/15/16 |
| author:agent | 1.000 [1.000, 1.000] | 0.909 [0.725, 1.000] | 0.952 [0.841, 1.000] | 0.950 [0.849, 1.000] | 10/10/11 |
| author:human | 1.000 [1.000, 1.000] | 0.857 [0.250, 1.000] | 0.923 [0.400, 1.000] | 0.750 [0.250, 1.000] | 6/6/7 |

### Testability (matched criteria with a gold label)

| Metric | Value [95% CI] |
|---|---|
| n | 16 |
| accuracy | 0.875 [0.750, 1.000] |
| macro-F1 | 0.752 [0.466, 1.000] |
| Cohen's kappa | 0.722 [0.478, 1.000] |
| abstained (unrated) | 0.000 [0.000, 0.000] |

Confusion matrix (rows: gold, columns: system)

| gold \ system | behavioral_testable | structural_checkable | non_functional_measurable | subjective_or_vague | untestable_external | unrated |
|---|---|---|---|---|---|---|
| **behavioral_testable** | 11 | 0 | 0 | 1 | 0 | 0 |
| **non_functional_measurable** | 0 | 0 | 2 | 1 | 0 | 0 |
| **subjective_or_vague** | 0 | 0 | 0 | 1 | 0 | 0 |

### Abstention, coverage and PRs without gold

| Metric | Value [95% CI] |
|---|---|
| PRs with no predicted criterion | 0.300 [0.000, 0.600] |
| PRs with gold: any gold criterion matched | 0.875 [0.600, 1.000] |
| share of PRs without gold | 0.200 [0.000, 0.400] |
| PRs without gold with >= 1 prediction (false-positive rate) | 0.000 [0.000, 0.000] |
| mean predictions on PRs without gold | 0.000 [0.000, 0.000] |
| predictions left unrated | 0.000 [0.000, 0.000] |
| mean IoU of matched spans | 1.000 [1.000, 1.000] |
| matched spans with exact boundaries | 1.000 [1.000, 1.000] |

## Extractor `llm-fake` (llm)

### Matching modes (all PRs)

|  | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| span IoU (primary) | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |
| normalized text equality | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |
| token Jaccard (fuzzy) | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |

### Per source type (span IoU)

| Source type | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| agent_prompt | 0.750 [0.750, 0.750] | 1.000 [1.000, 1.000] | 0.857 [0.857, 0.857] | 0.857 [0.857, 0.857] | 3/4/3 |
| commit_message | 0.333 [0.333, 0.333] | 1.000 [1.000, 1.000] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 1/3/1 |
| issue | 0.667 [0.667, 0.667] | 1.000 [1.000, 1.000] | 0.800 [0.800, 0.800] | 0.800 [0.800, 0.800] | 2/3/2 |
| pr_body | 0.579 [0.267, 0.810] | 0.917 [0.769, 1.000] | 0.710 [0.421, 0.857] | 0.903 [0.832, 1.000] | 11/19/12 |

### Per PR slice (span IoU)

| Slice | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| not_well_specified | 0.222 [0.000, 1.000] | 1.000 [1.000, 1.000] | 0.364 [0.000, 1.000] | 0.700 [0.400, 1.000] | 2/9/2 |
| well_specified | 0.750 [0.625, 0.900] | 0.938 [0.812, 1.000] | 0.833 [0.750, 0.897] | 0.840 [0.756, 0.914] | 15/20/16 |
| author:agent | 0.714 [0.400, 1.000] | 0.909 [0.725, 1.000] | 0.800 [0.545, 0.929] | 0.879 [0.814, 0.964] | 10/14/11 |
| author:human | 0.467 [0.200, 0.750] | 1.000 [1.000, 1.000] | 0.636 [0.333, 0.857] | 0.731 [0.467, 0.964] | 7/15/7 |

### Testability (matched criteria with a gold label)

| Metric | Value [95% CI] |
|---|---|
| n | 17 |
| accuracy | 0.882 [0.765, 1.000] |
| macro-F1 | 0.808 [0.500, 1.000] |
| Cohen's kappa | 0.762 [0.544, 1.000] |
| abstained (unrated) | 0.000 [0.000, 0.000] |

Confusion matrix (rows: gold, columns: system)

| gold \ system | behavioral_testable | structural_checkable | non_functional_measurable | subjective_or_vague | untestable_external | unrated |
|---|---|---|---|---|---|---|
| **behavioral_testable** | 11 | 0 | 0 | 1 | 0 | 0 |
| **non_functional_measurable** | 0 | 0 | 2 | 1 | 0 | 0 |
| **subjective_or_vague** | 0 | 0 | 0 | 2 | 0 | 0 |

### Abstention, coverage and PRs without gold

| Metric | Value [95% CI] |
|---|---|
| PRs with no predicted criterion | 0.000 [0.000, 0.000] |
| PRs with gold: any gold criterion matched | 1.000 [1.000, 1.000] |
| share of PRs without gold | 0.200 [0.000, 0.400] |
| PRs without gold with >= 1 prediction (false-positive rate) | 1.000 [1.000, 1.000] |
| mean predictions on PRs without gold | 2.000 [2.000, 2.000] |
| predictions left unrated | 0.000 [0.000, 0.000] |
| mean IoU of matched spans | 1.000 [1.000, 1.000] |
| matched spans with exact boundaries | 1.000 [1.000, 1.000] |

## Extractor `combined-fake` (combined)

### Matching modes (all PRs)

|  | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| span IoU (primary) | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |
| normalized text equality | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |
| token Jaccard (fuzzy) | 0.586 [0.406, 0.778] | 0.944 [0.833, 1.000] | 0.723 [0.571, 0.846] | 0.805 [0.655, 0.918] | 17/29/18 |

### Per source type (span IoU)

| Source type | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| agent_prompt | 0.750 [0.750, 0.750] | 1.000 [1.000, 1.000] | 0.857 [0.857, 0.857] | 0.857 [0.857, 0.857] | 3/4/3 |
| commit_message | 0.333 [0.333, 0.333] | 1.000 [1.000, 1.000] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 1/3/1 |
| issue | 0.667 [0.667, 0.667] | 1.000 [1.000, 1.000] | 0.800 [0.800, 0.800] | 0.800 [0.800, 0.800] | 2/3/2 |
| pr_body | 0.579 [0.267, 0.810] | 0.917 [0.769, 1.000] | 0.710 [0.421, 0.857] | 0.903 [0.832, 1.000] | 11/19/12 |

### Per PR slice (span IoU)

| Slice | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| not_well_specified | 0.222 [0.000, 1.000] | 1.000 [1.000, 1.000] | 0.364 [0.000, 1.000] | 0.700 [0.400, 1.000] | 2/9/2 |
| well_specified | 0.750 [0.625, 0.900] | 0.938 [0.812, 1.000] | 0.833 [0.750, 0.897] | 0.840 [0.756, 0.914] | 15/20/16 |
| author:agent | 0.714 [0.400, 1.000] | 0.909 [0.725, 1.000] | 0.800 [0.545, 0.929] | 0.879 [0.814, 0.964] | 10/14/11 |
| author:human | 0.467 [0.200, 0.750] | 1.000 [1.000, 1.000] | 0.636 [0.333, 0.857] | 0.731 [0.467, 0.964] | 7/15/7 |

### Testability (matched criteria with a gold label)

| Metric | Value [95% CI] |
|---|---|
| n | 17 |
| accuracy | 0.882 [0.765, 1.000] |
| macro-F1 | 0.808 [0.500, 1.000] |
| Cohen's kappa | 0.762 [0.544, 1.000] |
| abstained (unrated) | 0.000 [0.000, 0.000] |

Confusion matrix (rows: gold, columns: system)

| gold \ system | behavioral_testable | structural_checkable | non_functional_measurable | subjective_or_vague | untestable_external | unrated |
|---|---|---|---|---|---|---|
| **behavioral_testable** | 11 | 0 | 0 | 1 | 0 | 0 |
| **non_functional_measurable** | 0 | 0 | 2 | 1 | 0 | 0 |
| **subjective_or_vague** | 0 | 0 | 0 | 2 | 0 | 0 |

### Abstention, coverage and PRs without gold

| Metric | Value [95% CI] |
|---|---|
| PRs with no predicted criterion | 0.000 [0.000, 0.000] |
| PRs with gold: any gold criterion matched | 1.000 [1.000, 1.000] |
| share of PRs without gold | 0.200 [0.000, 0.400] |
| PRs without gold with >= 1 prediction (false-positive rate) | 1.000 [1.000, 1.000] |
| mean predictions on PRs without gold | 2.000 [2.000, 2.000] |
| predictions left unrated | 0.000 [0.000, 0.000] |
| mean IoU of matched spans | 1.000 [1.000, 1.000] |
| matched spans with exact boundaries | 1.000 [1.000, 1.000] |

## Extractor `sanity-oracle` (oracle)

### Matching modes (all PRs)

|  | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| span IoU (primary) | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 18/18/18 |
| normalized text equality | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 18/18/18 |
| token Jaccard (fuzzy) | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 18/18/18 |

### Per source type (span IoU)

| Source type | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| agent_prompt | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 3/3/3 |
| commit_message | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1/1/1 |
| issue | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 2/2/2 |
| pr_body | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 12/12/12 |

### Per PR slice (span IoU)

| Slice | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| not_well_specified | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 2/2/2 |
| well_specified | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 16/16/16 |
| author:agent | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 11/11/11 |
| author:human | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 7/7/7 |

### Testability (matched criteria with a gold label)

| Metric | Value [95% CI] |
|---|---|
| n | 18 |
| accuracy | 1.000 [1.000, 1.000] |
| macro-F1 | 1.000 [1.000, 1.000] |
| Cohen's kappa | 1.000 [1.000, 1.000] |
| abstained (unrated) | 0.000 [0.000, 0.000] |

Confusion matrix (rows: gold, columns: system)

| gold \ system | behavioral_testable | structural_checkable | non_functional_measurable | subjective_or_vague | untestable_external | unrated |
|---|---|---|---|---|---|---|
| **behavioral_testable** | 13 | 0 | 0 | 0 | 0 | 0 |
| **non_functional_measurable** | 0 | 0 | 3 | 0 | 0 | 0 |
| **subjective_or_vague** | 0 | 0 | 0 | 2 | 0 | 0 |

### Abstention, coverage and PRs without gold

| Metric | Value [95% CI] |
|---|---|
| PRs with no predicted criterion | 0.200 [0.000, 0.400] |
| PRs with gold: any gold criterion matched | 1.000 [1.000, 1.000] |
| share of PRs without gold | 0.200 [0.000, 0.400] |
| PRs without gold with >= 1 prediction (false-positive rate) | 0.000 [0.000, 0.000] |
| mean predictions on PRs without gold | 0.000 [0.000, 0.000] |
| predictions left unrated | 0.000 [0.000, 0.000] |
| mean IoU of matched spans | 1.000 [1.000, 1.000] |
| matched spans with exact boundaries | 1.000 [1.000, 1.000] |

## Extractor `sanity-null` (null)

### Matching modes (all PRs)

|  | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| span IoU (primary) | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/18 |
| normalized text equality | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/18 |
| token Jaccard (fuzzy) | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/18 |

### Per source type (span IoU)

| Source type | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| agent_prompt | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/3 |
| commit_message | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/1 |
| issue | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/2 |
| pr_body | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/12 |

### Per PR slice (span IoU)

| Slice | Precision | Recall | F1 (micro) | F1 (per-PR macro) | tp/pred/gold |
|---|---|---|---|---|---|
| not_well_specified | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/2 |
| well_specified | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/16 |
| author:agent | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/11 |
| author:human | n/a | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/0/7 |

### Testability (matched criteria with a gold label)

No matched criterion carries a gold testability label.

### Abstention, coverage and PRs without gold

| Metric | Value [95% CI] |
|---|---|
| PRs with no predicted criterion | 1.000 [1.000, 1.000] |
| PRs with gold: any gold criterion matched | 0.000 [0.000, 0.000] |
| share of PRs without gold | 0.200 [0.000, 0.400] |
| PRs without gold with >= 1 prediction (false-positive rate) | 0.000 [0.000, 0.000] |
| mean predictions on PRs without gold | 0.000 [0.000, 0.000] |
| predictions left unrated | n/a |
| mean IoU of matched spans | n/a |
| matched spans with exact boundaries | n/a |

## Reproducibility

| Extractor | Versions | Seconds | LLM calls | Tokens in/out | Errors |
|---|---|---|---|---|---|
| `deterministic` | extractor_version=det-extract-v1, testability_rules=testability-rules-v1 | 1.2388 | 0 (+0 cached) | 0/0 | 0 |
| `llm-fake` | model=fake-lines-1, prompt_version=intent-extract-llm-v1, provider=fake-lines, testability_rules=testability-rules-v1 | 1.4685 | 10 (+0 cached) | 1000/500 | 0 |
| `combined-fake` | extractor_version=det-extract-v1, model=fake-lines-1, prompt_version=intent-extract-llm-v1, provider=fake-lines, testability_rules=testability-rules-v1 | 1.51 | 10 (+0 cached) | 1000/500 | 0 |
| `sanity-oracle` | testability_rules=testability-rules-v1 | 1.504 | 0 (+0 cached) | 0/0 | 0 |
| `sanity-null` | testability_rules=testability-rules-v1 | 1.0045 | 0 (+0 cached) | 0/0 | 0 |

> **SYNTHETIC — not a research result.** This run used synthetic or fixture-derived data and exists only to exercise the harness.
