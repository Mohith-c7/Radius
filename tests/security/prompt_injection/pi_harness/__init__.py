"""Prompt-injection harness (QS-02). See docs/security/PROMPT_INJECTION.md."""

from .core import (
    PLANTED_ENV,
    TEST_NONCE,
    Case,
    FeatureFactory,
    FeatureInput,
    FeatureOutcome,
    LlmFeatureUnderTest,
    LlmModel,
    PromptRecord,
    check_outcome,
    inputs_for,
    load_cases,
    sanitize_inputs,
)
from .features import GuardedCriteriaFeature, NaiveCriteriaFeature
from .stubs import NaiveCompliantModel, WellBehavedModel

__all__ = [
    "PLANTED_ENV",
    "TEST_NONCE",
    "Case",
    "FeatureFactory",
    "FeatureInput",
    "FeatureOutcome",
    "GuardedCriteriaFeature",
    "LlmFeatureUnderTest",
    "LlmModel",
    "NaiveCompliantModel",
    "NaiveCriteriaFeature",
    "PromptRecord",
    "WellBehavedModel",
    "check_outcome",
    "inputs_for",
    "load_cases",
    "sanitize_inputs",
]
