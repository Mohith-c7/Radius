"""Static assertion strength ``a_static`` (EV-06, design 3.6).

Formula (exactly the design): ``a_static = max over assertion facts of table[kind]``.
A test with no facts and no ``expects_exception`` scores ``no_assertion`` (0). The
table lives in ``QualityConfig.assertion_scores`` (defaults: ``DEFAULT_ASSERTION_SCORES``)
so every weight is configurable and digested with the config.

``cap_static`` is NOT applied here (EV-08 applies ``d_eff = min(cap_static, a_static)``).

Every contribution is explained with a reason code. The LK-04 "strength features"
(``mock_only``, ``circular``, ``dead``, ``swallowed``, ``in_loop``, ``snapshot``,
``property_based``) enter through the *kind* of each fact (see
``radius_evidence.domain.assertion_records``) and are surfaced as reason codes from
the fact ``note`` tokens; they never raise the score.
"""

from __future__ import annotations

from dataclasses import dataclass

from radius_evidence.domain.config import QualityConfig
from radius_evidence.domain.enums import AssertKind
from radius_evidence.domain.model import AssertionFeatures, Reason

#: Tokens recognised in ``AssertionFact.note`` (comma/space separated) -> reason code.
NOTE_TOKENS: dict[str, str] = {
    "mock_only": "mock_only",
    "circular": "circular_expectation",
    "dead": "dead_assertion",
    "swallowed": "swallowed_assertion",
    "in_loop": "assertion_in_loop",
    "property_based": "property_based",
    "snapshot": "snapshot_only",
    "helper": "via_helper",
}


@dataclass(frozen=True, slots=True)
class StrengthResult:
    score: float  # a_static in [0, 1]
    best_kind: AssertKind
    reasons: tuple[Reason, ...]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def kind_score(kind: AssertKind | str, config: QualityConfig | None = None) -> float:
    """Table lookup; an unknown kind scores 0 (never optimistic)."""

    table = (config or QualityConfig()).assertion_scores
    key = kind.value if isinstance(kind, AssertKind) else str(kind)
    return _clamp(float(table.get(key, 0.0)))


def _note_reasons(note: str | None, ref: str) -> list[Reason]:
    if not note:
        return []
    tokens = note.replace(",", " ").replace(";", " ").lower().split()
    out = []
    for token in tokens:
        code = NOTE_TOKENS.get(token)
        if code:
            out.append(Reason(code=code, detail=f"assertion feature: {token}", ref=ref))
    return out


def explain_a_static(
    features: AssertionFeatures, config: QualityConfig | None = None
) -> StrengthResult:
    """Return ``a_static`` and the reason codes behind it (deterministic)."""

    cfg = config or QualityConfig()
    reasons: list[Reason] = []
    best = AssertKind.NO_ASSERTION
    best_score = -1.0

    for fact in sorted(features.assertions, key=lambda f: (f.line, f.kind.value)):
        score = kind_score(fact.kind, cfg)
        ref = f"{features.test_id}:{fact.line}"
        reasons.append(
            Reason(
                code=f"assert_{fact.kind.value}", detail=f"score {score:.2f}", ref=ref
            )
        )
        reasons.extend(_note_reasons(fact.note, ref))
        if score > best_score:
            best, best_score = fact.kind, score

    if not features.assertions:
        if features.expects_exception:
            best = AssertKind.EXCEPTION_TYPE
            best_score = kind_score(best, cfg)
            reasons.append(
                Reason(
                    "exception_only",
                    "expects an exception, type unknown",
                    features.test_id,
                )
            )
        else:
            best = AssertKind.NO_ASSERTION
            best_score = kind_score(best, cfg)
            reasons.append(
                Reason("no_assertion", "test has no assertion", features.test_id)
            )
    elif best_score <= 0.0:
        reasons.append(
            Reason(
                "no_effective_assertion", "every assertion scores 0", features.test_id
            )
        )

    if features.has_skip_marker:
        reasons.append(
            Reason(
                "skip_marker",
                "scored, but the outcome is skipped so q is 0",
                features.test_id,
            )
        )
    if features.is_parametrized:
        detail = (
            f"{features.n_param_cases} cases"
            if features.n_param_cases
            else "cases unknown"
        )
        reasons.append(Reason("parametrized", detail, features.test_id))

    return StrengthResult(_clamp(best_score), best, tuple(reasons))


def a_static(features: AssertionFeatures, config: QualityConfig | None = None) -> float:
    """``a_static`` in [0, 1] for one test function (EV-06)."""

    return explain_a_static(features, config).score
