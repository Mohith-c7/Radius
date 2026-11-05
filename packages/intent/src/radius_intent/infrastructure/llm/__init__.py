"""Guarded LLM-assisted criterion extraction (IN-04). Optional, default off."""

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
from radius_intent.infrastructure.llm.fake import FakeProvider
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
    ProviderConfigError,
    ProviderError,
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
    "InMemoryResponseCache",
    "InMemoryUsageLedger",
    "LlmCriterionExtractor",
    "LlmExtractionConfig",
    "LlmExtractionResult",
    "LlmModeSetup",
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "LlmRunRecord",
    "MergeResult",
    "PrTextLlmExtractor",
    "ProviderAuthError",
    "ProviderConfigError",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderRequestError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "ResponseCache",
    "UsageLedger",
    "backoff_delay",
    "build_llm_mode_extractors",
    "merge_proposals",
]
