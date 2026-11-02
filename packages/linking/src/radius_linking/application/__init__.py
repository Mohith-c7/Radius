"""Linking use cases (depend on the domain only)."""

from radius_linking.application.chain import (
    ChainConfig,
    aggregate_support,
    build_support_links,
    explain,
    score_chain,
)
from radius_linking.application.combine import (
    COMBINER_VERSION,
    DEFAULT_WEIGHTS,
    CombineConfig,
    combine_scores,
)
from radius_linking.application.evaluate import (
    RankMetrics,
    ablation,
    evaluate_linkset,
    evaluate_rankings,
    gold_from_expected,
    links_as_expected,
    rankings_from_linkset,
)
from radius_linking.application.relevance import (
    RelevanceConfig,
    connected_pairs,
    relevance_from_links,
    relevant_tests,
    score_relevance,
)
from radius_linking.application.service import (
    LinkingConfig,
    link_criteria,
    select_candidates,
)

__all__ = [
    "RelevanceConfig",
    "connected_pairs",
    "relevance_from_links",
    "relevant_tests",
    "score_relevance",
    "ChainConfig",
    "aggregate_support",
    "build_support_links",
    "explain",
    "score_chain",
    "COMBINER_VERSION",
    "DEFAULT_WEIGHTS",
    "CombineConfig",
    "LinkingConfig",
    "RankMetrics",
    "ablation",
    "combine_scores",
    "evaluate_linkset",
    "evaluate_rankings",
    "gold_from_expected",
    "link_criteria",
    "links_as_expected",
    "rankings_from_linkset",
    "select_candidates",
]
