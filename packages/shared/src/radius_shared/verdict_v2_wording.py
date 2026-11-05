"""User-visible wording of Verdict v2 (alpha): one place, stdlib only.

The JSON contract keeps the internal enum values (``proven``, ``verified``, ...)
for compatibility; this module is the *presentation* mapping used by the API
summary text. The Markdown renderer (``radius_github.verdict_v2.markdown``) and
the dashboard (``apps/dashboard/lib/verdict-v2-model.ts``) carry the same strings;
tests in ``apps/api`` and ``apps/dashboard`` keep the three in step.

Honesty rule: the alpha measures static assertion strength only, with thresholds
that are not calibrated, so nothing here says "proven" or "verified".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DISCLAIMER = (
    "Alpha: static evidence only (assertion strength, no mutation testing); "
    "thresholds are uncalibrated. This is not a proof of correctness."
)
#: Contract 5: used instead of ``DISCLAIMER`` only when mutation measured a criterion.
MUTATION_DISCLAIMER = (
    "Alpha: static assertion strength plus sampled mutation testing; thresholds are "
    "uncalibrated. Where marked mutation-measured, how well a test detects faults was "
    "measured on a bounded sample of seeded faults in the changed code. This is not a "
    "proof of correctness."
)
LEGEND = "supported = static assertion strength above threshold; not a proof of correctness"

STATE_LABELS: Mapping[str, str] = {
    "proven": "SUPPORTED",
    "weak": "WEAK",
    "unevidenced": "UNSUPPORTED",
    "contradicted": "CONTRADICTED",
    "excluded": "EXCLUDED",
}
VERDICT_LABELS: Mapping[str, str] = {
    "verified": "Supported by static evidence (alpha)",
    "failed": "Failed",
    "insufficient_evidence": "Not verified - insufficient evidence",
    "needs_review": "Needs human review",
}


def presentation(
    verdict: str | None,
    supported: int,
    total: int,
    *,
    author_hint_criteria: int = 0,
    evidence_basis: str = "static_only",
) -> dict[str, Any]:
    """The additive ``presentation`` block of the served payload."""

    label = VERDICT_LABELS.get(verdict or "", "Verdict unavailable")
    mutation = evidence_basis == "static_and_mutation"
    how = "static evidence and sampled mutation testing" if mutation else "static evidence"
    text = f"{label}: {supported} of {total} stated criteria supported by {how}."
    if author_hint_criteria:
        noun = "criterion relies" if author_hint_criteria == 1 else "criteria rely"
        text += f" {author_hint_criteria} {noun} on author-supplied test hints."
    return {
        "verdict_label": label,
        "state_labels": dict(STATE_LABELS),
        "legend": LEGEND,
        "disclaimer": MUTATION_DISCLAIMER if mutation else DISCLAIMER,
        "summary_text": text,
    }
