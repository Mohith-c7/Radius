"""LLM input/output guard (QS-02): sanitise, delimit, validate.

See ``docs/security/PROMPT_INJECTION.md``. Every LLM-assisted feature must route
untrusted text through :func:`sanitize_untrusted` -> :func:`build_prompt` and
model output through :func:`validate_criteria_output` (or an equally strict
validator), and must register in ``tests/security/prompt_injection``.
"""

from radius_shared.llm_guard.output import (
    Criterion,
    OutputLimits,
    OutputRejected,
    contains_secret,
    validate_criteria_output,
)
from radius_shared.llm_guard.prompt import (
    BuiltPrompt,
    NonceCollision,
    PromptBuildError,
    build_prompt,
    new_nonce,
    parse_data_blocks,
)
from radius_shared.llm_guard.sanitize import (
    Finding,
    UntrustedText,
    collect_env_secrets,
    decode_candidates,
    sanitize_untrusted,
)

__all__ = [
    "BuiltPrompt",
    "Criterion",
    "Finding",
    "NonceCollision",
    "OutputLimits",
    "OutputRejected",
    "PromptBuildError",
    "UntrustedText",
    "build_prompt",
    "collect_env_secrets",
    "contains_secret",
    "decode_candidates",
    "new_nonce",
    "parse_data_blocks",
    "sanitize_untrusted",
    "validate_criteria_output",
]
