"""Per-PR scoring and metric definitions for RQ1 extraction (IN-10).

Everything here is additive-count based so one PR is a sparse vector that the
cluster bootstrap (``stats``) can resample:

``{group}|{mode}|{field}``
    ``mode`` is ``iou`` (primary: span IoU >= threshold), ``text_exact``
    (normalized text equality) or ``text_fuzzy`` (token Jaccard >= threshold).
    ``group`` is ``all``, ``well_specified``, ``not_well_specified``,
    ``kind:<source kind>`` or ``author:<author type>``. Fields: ``pred``,
    ``gold``, ``tp_p`` (matched predictions), ``tp_g`` (matched gold items) and
    the per-PR macro sums ``p_sum/p_n``, ``r_sum/r_n``, ``f1_sum/f1_n``.

Metric definitions (names are ``{mode}.{group}.{metric}``):

* ``precision`` = tp_p / pred, ``recall`` = tp_g / gold, ``f1`` = 2 tp / (pred +
  gold) with tp = tp_p = tp_g inside one group (micro, pooled over PRs).
  Undefined ratios are ``None``; F1 is 0 whenever gold + pred > 0 and nothing
  matches, so an empty extractor scores recall 0 and F1 0.
* ``macro_precision`` / ``macro_recall`` / ``macro_f1``: mean of the per-PR
  value over PRs that have predictions (precision) or gold criteria (recall,
  F1). A PR without predictions has per-PR F1 0.

Testability (primary IoU matches whose gold has a label): ``tx.accuracy``,
``tx.macro_f1``, ``tx.kappa`` (Cohen), ``tx.abstain_rate`` (system left it
``unrated``; counted as an error in accuracy), ``tx.n``.

Abstention / coverage: ``abstention.empty_prediction_rate`` (PRs with no
predicted criterion), ``coverage.any_hit_rate`` (PRs with gold where at least
one gold criterion was matched), ``nogold.fp_rate`` (PRs without gold that got
at least one prediction), ``nogold.mean_predictions``, ``nogold.share``.
Span quality: ``span.mean_iou`` and ``span.exact_rate`` over IoU matches.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_intent.domain import Testability

from .gold import EvalCase
from .matching import Match, SpanRef, match_by_iou, match_by_text
from .stats import cohen_kappa

MODES = ("iou", "text_exact", "text_fuzzy")
UNRATED = "unrated"
RATED_LABELS = tuple(
    t.value for t in dict.fromkeys(Testability) if t is not Testability.UNRATED
)
DEFAULT_IOU_THRESHOLD = 0.5  # PREREGISTRATION 5.1 (initial guess)
DEFAULT_TEXT_THRESHOLD = 0.8


@dataclass(frozen=True)
class MatchConfig:
    """Matching thresholds (recorded in every manifest)."""

    iou_threshold: float = DEFAULT_IOU_THRESHOLD
    text_threshold: float = DEFAULT_TEXT_THRESHOLD

    def __post_init__(self) -> None:
        for name in ("iou_threshold", "text_threshold"):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")

    def as_dict(self) -> dict[str, float]:
        return {
            "iou_threshold": self.iou_threshold,
            "text_threshold": self.text_threshold,
        }


@dataclass(frozen=True)
class PredictedCriterion:
    """What an extractor produced for one PR, reduced to what scoring needs."""

    source_id: str
    start: int
    end: int
    text: str
    testability: str | None = None  # canonical Testability value, None = unrated
    method: str = "deterministic"


@dataclass(frozen=True)
class CaseScore:
    """One PR's additive count vector plus error-analysis detail."""

    case_id: str
    vector: dict[str, float]
    n_pred: int
    n_gold: int
    false_positives: tuple[dict[str, Any], ...] = ()
    false_negatives: tuple[str, ...] = ()


def _groups_for_case(case: EvalCase) -> list[str]:
    groups = ["all"]
    if case.well_specified is True:
        groups.append("well_specified")
    elif case.well_specified is False:
        groups.append("not_well_specified")
    if case.author_type:
        groups.append(f"author:{case.author_type}")
    return groups


def _add(vec: dict[str, float], key: str, value: float) -> None:
    if value:
        vec[key] = vec.get(key, 0) + value


def score_case(
    case: EvalCase,
    preds: Sequence[PredictedCriterion],
    config: MatchConfig | None = None,
) -> CaseScore:
    """Match one PR's predictions against its gold and return count vectors."""
    cfg = config or MatchConfig()
    gold = case.criteria
    gold_spans = [
        [SpanRef(s.source_id, s.start, s.end) for s in g.all_spans] for g in gold
    ]
    gold_sources = [{s.source_id for s in g.all_spans} for g in gold]
    gold_texts = [
        ([g.text] if g.text else []) + [case.slice(s) for s in g.all_spans]
        for g in gold
    ]
    pred_spans = [SpanRef(p.source_id, p.start, p.end) for p in preds]
    pred_texts = [p.text for p in preds]

    def same_source(i: int, j: int) -> bool:
        return preds[i].source_id in gold_sources[j]

    matches: dict[str, list[Match]] = {
        "iou": match_by_iou(pred_spans, gold_spans, cfg.iou_threshold),
        "text_exact": match_by_text(pred_texts, gold_texts, 1.0, same_source),
        "text_fuzzy": match_by_text(
            pred_texts, gold_texts, cfg.text_threshold, same_source
        ),
    }

    case_groups = _groups_for_case(case)

    def kind_group(source_id: str) -> str:
        kind = case.kind_of(source_id)
        return f"kind:{kind.value}" if kind else "kind:unknown"

    pred_groups = [[*case_groups, kind_group(p.source_id)] for p in preds]
    gold_groups = [[*case_groups, kind_group(g.span.source_id)] for g in gold]

    vec: dict[str, float] = {}
    for mode in MODES:
        matched_p = {m.pred_index for m in matches[mode]}
        matched_g = {m.gold_index for m in matches[mode]}
        per_group: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        for i, groups in enumerate(pred_groups):
            for g in groups:
                per_group[g][0] += 1
                per_group[g][1] += i in matched_p
        for j, groups in enumerate(gold_groups):
            for g in groups:
                per_group[g][2] += 1
                per_group[g][3] += j in matched_g
        for g, (pred, tp_p, gold_n, tp_g) in per_group.items():
            _add(vec, f"{g}|{mode}|pred", pred)
            _add(vec, f"{g}|{mode}|tp_p", tp_p)
            _add(vec, f"{g}|{mode}|gold", gold_n)
            _add(vec, f"{g}|{mode}|tp_g", tp_g)
            if pred:
                vec[f"{g}|{mode}|p_sum"] = vec.get(f"{g}|{mode}|p_sum", 0) + tp_p / pred
                vec[f"{g}|{mode}|p_n"] = vec.get(f"{g}|{mode}|p_n", 0) + 1
            if gold_n:
                f1 = 2 * tp_g / (pred + gold_n)
                for field, value in (("r_sum", tp_g / gold_n), ("f1_sum", f1)):
                    vec[f"{g}|{mode}|{field}"] = (
                        vec.get(f"{g}|{mode}|{field}", 0) + value
                    )
                vec[f"{g}|{mode}|r_n"] = vec.get(f"{g}|{mode}|r_n", 0) + 1
                vec[f"{g}|{mode}|f1_n"] = vec.get(f"{g}|{mode}|f1_n", 0) + 1

    # PR-level counts
    for g in case_groups:
        _add(vec, f"{g}|cases", 1)
    n_pred, n_gold = len(preds), len(gold)
    iou_matches = matches["iou"]
    _add(vec, "all|pred_total", n_pred)
    _add(vec, "all|unrated_pred", sum(1 for p in preds if p.testability is None))
    if n_pred == 0:
        _add(vec, "all|empty_pred_cases", 1)
    if n_gold:
        _add(vec, "all|gold_cases", 1)
        if iou_matches:
            _add(vec, "all|hit_cases", 1)
    else:
        _add(vec, "all|nogold_cases", 1)
        _add(vec, "all|nogold_pred", n_pred)
        if n_pred:
            _add(vec, "all|nogold_fp_cases", 1)

    # span quality and testability on primary matches
    for m in iou_matches:
        _add(vec, "all|span_n", 1)
        _add(vec, "all|span_iou_sum", m.score)
        if m.score >= 1.0 - 1e-12:
            _add(vec, "all|span_exact_n", 1)
        label = gold[m.gold_index].testability
        if label is not None:
            got = preds[m.pred_index].testability or UNRATED
            _add(vec, f"tx|{label.value}>{got}", 1)

    matched_p = {m.pred_index for m in iou_matches}
    matched_g = {m.gold_index for m in iou_matches}
    fps = tuple(
        {
            "source_id": p.source_id,
            "start": p.start,
            "end": p.end,
            "text": p.text[:120],
        }
        for i, p in enumerate(preds)
        if i not in matched_p
    )
    fns = tuple(g.criterion_id for j, g in enumerate(gold) if j not in matched_g)
    return CaseScore(case.case_id, vec, n_pred, n_gold, fps, fns)


# --------------------------------------------------------------------- metrics


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _tx_metrics(total: Mapping[str, float]) -> dict[str, float | None]:
    confusion: dict[tuple[str, str], float] = {}
    for key, value in total.items():
        if key.startswith("tx|"):
            gold, _, got = key[3:].partition(">")
            confusion[(gold, got)] = value
    n = sum(confusion.values())
    out: dict[str, float | None] = {"tx.n": n}
    if not n:
        out.update(
            {
                "tx.accuracy": None,
                "tx.macro_f1": None,
                "tx.kappa": None,
                "tx.abstain_rate": None,
            }
        )
        return out
    correct = sum(v for (g, p), v in confusion.items() if g == p)
    out["tx.accuracy"] = correct / n
    out["tx.abstain_rate"] = sum(v for (_, p), v in confusion.items() if p == UNRATED) / n
    f1s = []
    for label in RATED_LABELS:
        tp = confusion.get((label, label), 0)
        actual = sum(v for (g, _), v in confusion.items() if g == label)
        predicted = sum(v for (_, p), v in confusion.items() if p == label)
        if actual or predicted:
            f1s.append(2 * tp / (actual + predicted))
    out["tx.macro_f1"] = sum(f1s) / len(f1s) if f1s else None
    out["tx.kappa"] = cohen_kappa(confusion)
    return out


def compute_metrics(total: Mapping[str, float]) -> dict[str, float | None]:
    """All metrics for an aggregated count vector (sorted by name)."""
    groups = sorted({k.split("|", 1)[0] for k in total if "|" in k} - {"tx"})
    out: dict[str, float | None] = {}
    for g in groups:
        for mode in MODES:
            pre = f"{g}|{mode}|"
            pred, gold = total.get(pre + "pred", 0), total.get(pre + "gold", 0)
            tp_p, tp_g = total.get(pre + "tp_p", 0), total.get(pre + "tp_g", 0)
            if pred == 0 and gold == 0 and f"{pre}pred" not in total:
                if f"{pre}gold" not in total:
                    continue
            name = f"{mode}.{g}."
            out[name + "precision"] = _ratio(tp_p, pred)
            out[name + "recall"] = _ratio(tp_g, gold)
            out[name + "f1"] = _ratio(2 * tp_g, pred + gold)
            out[name + "macro_precision"] = _ratio(
                total.get(pre + "p_sum", 0), total.get(pre + "p_n", 0)
            )
            out[name + "macro_recall"] = _ratio(
                total.get(pre + "r_sum", 0), total.get(pre + "r_n", 0)
            )
            out[name + "macro_f1"] = _ratio(
                total.get(pre + "f1_sum", 0), total.get(pre + "f1_n", 0)
            )
    cases = total.get("all|cases", 0)
    gold_cases = total.get("all|gold_cases", 0)
    nogold = total.get("all|nogold_cases", 0)
    out["abstention.empty_prediction_rate"] = _ratio(
        total.get("all|empty_pred_cases", 0), cases
    )
    out["coverage.any_hit_rate"] = _ratio(total.get("all|hit_cases", 0), gold_cases)
    out["nogold.share"] = _ratio(nogold, cases)
    out["nogold.fp_rate"] = _ratio(total.get("all|nogold_fp_cases", 0), nogold)
    out["nogold.mean_predictions"] = _ratio(total.get("all|nogold_pred", 0), nogold)
    out["testability.unrated_pred_rate"] = _ratio(
        total.get("all|unrated_pred", 0), total.get("all|pred_total", 0)
    )
    span_n = total.get("all|span_n", 0)
    out["span.mean_iou"] = _ratio(total.get("all|span_iou_sum", 0), span_n)
    out["span.exact_rate"] = _ratio(total.get("all|span_exact_n", 0), span_n)
    out.update(_tx_metrics(total))
    return dict(sorted(out.items()))


def confusion_matrix(total: Mapping[str, float]) -> dict[str, dict[str, int]]:
    """``{gold label: {predicted label: count}}`` from an aggregated vector."""
    out: dict[str, dict[str, int]] = {}
    for key, value in total.items():
        if key.startswith("tx|"):
            gold, _, got = key[3:].partition(">")
            out.setdefault(gold, {})[got] = int(value)
    return {g: dict(sorted(row.items())) for g, row in sorted(out.items())}


def group_counts(total: Mapping[str, float], group: str, mode: str) -> dict[str, int]:
    """Raw pred/gold/tp counts of one group and mode (for report tables)."""
    pre = f"{group}|{mode}|"
    return {
        "pred": int(total.get(pre + "pred", 0)),
        "gold": int(total.get(pre + "gold", 0)),
        "tp": int(total.get(pre + "tp_g", 0)),
    }


def group_names(total: Mapping[str, float]) -> list[str]:
    """Groups present in an aggregated vector, ``all`` first."""
    names = {k.split("|", 1)[0] for k in total if "|" in k} - {"tx"}
    return sorted(names, key=lambda n: (n != "all", n))
