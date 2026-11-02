"""Verdict v2 parameters with the ``alpha-static`` defaults (design 3.8).

One immutable object holds every tunable number. Defaults are hypotheses, not
results; the DESIGN/pre-registration values are kept in ``DESIGN_DEFAULTS_*`` so
a second profile can select them (decision D2). Changing a default here is a
contract change (bump the component version, see design 3.10).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radius_evidence.domain.serialization import (
    Serializable,
    canonical_json,
    sha256_hex,
)
from radius_evidence.domain.versions import PROFILE_ALPHA_STATIC

#: DESIGN 6.3 / 6.4 values, selectable as a second profile later.
DESIGN_DEFAULT_CAP_STATIC = 0.4
DESIGN_DEFAULT_TAU_SUPPORT = 0.6

#: Assertion strength table (design 3.6); keys are ``AssertKind`` values.
DEFAULT_ASSERTION_SCORES: dict[str, float] = {
    "value_equality": 1.00,
    "approx_equality": 0.90,
    "exception_type_message": 0.90,
    "exception_type": 0.80,
    "membership": 0.35,
    "comparison_bound": 0.35,
    "length_check": 0.30,
    "snapshot": 0.30,
    "truthiness": 0.25,
    "none_check": 0.25,
    "mock_called": 0.20,
    "type_check": 0.20,
    "tautology": 0.00,
    "no_assertion": 0.00,
    "other": 0.00,
}

#: Penalty per tamper severity label (design 3.5).
DEFAULT_TAMPER_PENALTY: dict[str, float] = {
    "critical": 1.0,
    "high": 1.0,
    "medium": 0.5,
    "low": 0.2,
    "info": 0.0,
}

#: Case-insensitive substrings marking an agent-authored PR (EV-03-lite).
DEFAULT_AGENT_TRAILER_PATTERNS: tuple[str, ...] = (
    "co-authored-by: claude",
    "co-authored-by: copilot",
    "generated with [claude code]",
    "[bot]",
)

#: Severity labels in increasing order (used to compare against thresholds).
SEVERITY_ORDER: tuple[str, ...] = ("info", "low", "medium", "high", "critical")


@dataclass(frozen=True, slots=True)
class QualityConfig(Serializable):
    cap_static: float = 0.60
    iota_human: float = 1.0
    iota_agent: float = 0.6
    iota_unknown: float = 0.8
    pre_existing_unchanged_factor: float = 1.0
    flaky_discount_max: float = 0.5
    assertion_scores: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ASSERTION_SCORES)
    )
    tamper_penalty: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TAMPER_PENALTY)
    )
    lambda_kind: dict[str, float] = field(
        default_factory=lambda: {"test_outcome": 1.0}
    )
    agent_trailer_patterns: tuple[str, ...] = DEFAULT_AGENT_TRAILER_PATTERNS


@dataclass(frozen=True, slots=True)
class LinkMapping(Serializable):
    """Raw producer scores to link strengths (one function later: LK-06)."""

    link_min_cs: float = 0.20
    link_sat_cs: float = 0.40
    min_test_link: float = 0.50
    relevance_gate: float = 0.5
    relevance_sat: float = 1.5
    max_symbols_per_criterion: int = 3
    hint_test_weight: float = 1.0


@dataclass(frozen=True, slots=True)
class SupportConfig(Serializable):
    tau_support: float = 0.50
    tau_weak: float = 0.20
    rho: float = 0.70
    s_cap: float = 0.90
    strong_min: float = 0.50


@dataclass(frozen=True, slots=True)
class RuleConfig(Serializable):
    uim_max: float = 0.20
    min_intent_coverage: float = 0.50
    fail_on_tamper_at_least: str = "high"
    review_on_tamper_at_least: str = "medium"
    link_review_min: float = 0.50
    max_criteria: int = 50
    max_symbols: int = 5000
    max_tests: int = 3000
    max_bundle_bytes: int = 2 * 1024 * 1024
    timeout_s: int = 120


@dataclass(frozen=True, slots=True)
class VerdictV2Config(Serializable):
    profile: str = PROFILE_ALPHA_STATIC
    quality: QualityConfig = field(default_factory=QualityConfig)
    support: SupportConfig = field(default_factory=SupportConfig)
    rules: RuleConfig = field(default_factory=RuleConfig)
    link: LinkMapping = field(default_factory=LinkMapping)

    def digest(self) -> str:
        """SHA-256 (64 hex) of the canonical JSON; stored on every verdict."""

        return sha256_hex(canonical_json(self))
