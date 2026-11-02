"""Extraction metrics harness (IN-10, RQ1).

Pure computation lives in ``gold``, ``matching``, ``stats``, ``metrics``,
``config``, ``compare`` and ``report``; reading files is confined to
``loader`` and ``provenance``; ``extractors``/``runner``/``cli`` wire the
production extraction code. See docs/research/evaluation/INTENT_EVAL.md.
"""

from radius_intent.evaluation.compare import CompareError, compare_runs
from radius_intent.evaluation.config import (
    MASTER_SEED,
    ConfigError,
    ExperimentConfig,
    ExtractorSpec,
    parse_config,
)
from radius_intent.evaluation.gold import (
    GOLD_SCHEMA_ID,
    EvalCase,
    GoldCriterion,
    GoldDataset,
    GoldFormatError,
    parse_gold,
)
from radius_intent.evaluation.matching import match_by_iou, match_by_text, span_iou
from radius_intent.evaluation.metrics import (
    MatchConfig,
    PredictedCriterion,
    compute_metrics,
    score_case,
)
from radius_intent.evaluation.stats import bootstrap_metrics, paired_bootstrap_diff

__all__ = [
    "GOLD_SCHEMA_ID",
    "MASTER_SEED",
    "CompareError",
    "ConfigError",
    "EvalCase",
    "ExperimentConfig",
    "ExtractorSpec",
    "GoldCriterion",
    "GoldDataset",
    "GoldFormatError",
    "MatchConfig",
    "PredictedCriterion",
    "bootstrap_metrics",
    "compare_runs",
    "compute_metrics",
    "match_by_iou",
    "match_by_text",
    "paired_bootstrap_diff",
    "parse_config",
    "parse_gold",
    "score_case",
    "span_iou",
]
