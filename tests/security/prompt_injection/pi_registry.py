"""Registry of LLM-assisted features that must pass the injection corpus.

To register a feature (e.g. IN-04):

1. Write an adapter implementing ``pi_harness.LlmFeatureUnderTest`` that calls
   your real code path with the injected ``model`` (a stub; never a network
   client) and returns a ``FeatureOutcome``.
2. Add a factory to ``REGISTERED_FEATURES`` below (import your package here).
3. Run ``python -m pytest tests/security/prompt_injection -q``. Every corpus
   case is executed against your feature with the worst-case naive model.

``KNOWN_BAD_FEATURES`` holds anti-patterns used only to prove the suite
catches them; do not register real features there.
"""

from __future__ import annotations

from pi_harness import FeatureFactory, GuardedCriteriaFeature, NaiveCriteriaFeature
from pi_intent_extract import IntentExtractAdapter

REGISTERED_FEATURES: dict[str, FeatureFactory] = {
    "reference-guarded": GuardedCriteriaFeature,
    "intent-extract-llm (IN-04)": IntentExtractAdapter,
}

KNOWN_BAD_FEATURES: dict[str, FeatureFactory] = {
    "reference-naive": NaiveCriteriaFeature,
}
