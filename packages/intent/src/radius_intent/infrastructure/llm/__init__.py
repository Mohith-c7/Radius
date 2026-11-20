"""Guarded LLM-assisted criterion extraction (IN-04) and the provider-neutral LLM layer.

Optional, default off. ``factory.build_llm_provider`` builds the configured provider
(``RADIUS_LLM_PROVIDER``: ``anthropic`` or ``openai_compatible``) behind ``GuardedProvider``.
"""

from radius_intent.infrastructure.llm.config import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    EgressPolicy,
    EnvEgressPolicy,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmExtractionConfig,
    ResponseCache,
    UsageLedger,
)
from radius_intent.infrastructure.llm.extractor import (
    LlmCriterionExtractor,
    LlmExtractionResult,
)
from radius_intent.infrastructure.llm.factory import (
    LlmProviderSettings,
    build_llm_provider,
)
from radius_intent.infrastructure.llm.fake import FakeProvider
from radius_intent.infrastructure.llm.guarded import GuardedProvider, RateGate
from radius_intent.infrastructure.llm.merge import (
    AssistedCriterionExtractor,
    AssistedExtraction,
    DroppedProposal,
    MergeResult,
    merge_proposals,
)
from radius_intent.infrastructure.llm.pr_text import (
    LlmModeSetup,
    LlmRunRecord,
    PrTextLlmExtractor,
    build_llm_mode_extractors,
)
from radius_intent.infrastructure.llm.provider import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    ProviderAuthError,
    ProviderBudgetExhausted,
    ProviderConfigError,
    ProviderError,
    ProviderOutputTruncated,
    ProviderRateLimited,
    ProviderRequestError,
    ProviderTimeout,
    ProviderUnavailable,
)
from radius_intent.infrastructure.llm.resilience import CircuitBreaker, backoff_delay

__all__ = [
    "DEFAULT_MODEL",
    "PROMPT_VERSION",
    "AssistedCriterionExtractor",
    "AssistedExtraction",
    "CircuitBreaker",
    "DroppedProposal",
    "EgressPolicy",
    "EnvEgressPolicy",
    "FakeProvider",
    "GuardedProvider",
    "InMemoryResponseCache",
    "InMemoryUsageLedger",
    "LlmCriterionExtractor",
    "LlmExtractionConfig",
    "LlmExtractionResult",
    "LlmModeSetup",
    "LlmProvider",
    "LlmProviderSettings",
    "LlmRequest",
    "LlmResponse",
    "LlmRunRecord",
    "MergeResult",
    "PrTextLlmExtractor",
    "ProviderAuthError",
    "ProviderBudgetExhausted",
    "ProviderConfigError",
    "ProviderError",
    "ProviderOutputTruncated",
    "ProviderRateLimited",
    "ProviderRequestError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateGate",
    "ResponseCache",
    "UsageLedger",
    "backoff_delay",
    "build_llm_mode_extractors",
    "build_llm_provider",
    "merge_proposals",
]
