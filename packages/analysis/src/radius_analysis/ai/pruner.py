import json
import os
from collections.abc import Mapping

from pydantic import BaseModel

try:
    from google import genai

    _USE_GENAI = True
except ImportError:
    import google.generativeai as genai

    _USE_GENAI = False

from .prompts import SEMANTIC_PRUNER_PROMPT

#: Explicit opt-in for the legacy Gemini pruner. It sends caller source code and
#: diffs to a third party, so the mere presence of GEMINI_API_KEY is not enough.
GEMINI_PRUNER_FLAG = "RADIUS_FEATURE_GEMINI_PRUNER"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def gemini_api_key_from_env(environ: Mapping[str, str] | None = None) -> str:
    """Return ``GEMINI_API_KEY`` only when ``RADIUS_FEATURE_GEMINI_PRUNER`` is on.

    Default is off. With the flag off the key is ignored and an empty string is
    returned, so ``SemanticPruner`` makes no network call.
    """

    env = os.environ if environ is None else environ
    if env.get(GEMINI_PRUNER_FLAG, "").strip().lower() not in _TRUE_VALUES:
        return ""
    return env.get(GEMINI_API_KEY_ENV, "").strip()


class PrunerDecision(BaseModel):
    impacted: bool
    reason: str
    confidence: float = 1.0
    category: str = "general"


class SemanticPruner:
    """Invokes Google Gemini to evaluate the semantic impact of a code change."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        self.model = None
        if not api_key:
            return
        if _USE_GENAI:
            self.client = genai.Client(api_key=api_key)
        else:
            genai.configure(api_key=api_key)
            # Using Flash as it is lightning fast for small context JSON tasks
            self.model = genai.GenerativeModel("gemini-1.5-flash")

    def evaluate_impact_detailed(self, caller_source: str, callee_diff: str) -> PrunerDecision:
        """
        Returns a detailed PrunerDecision evaluating if the caller is semantically impacted.
        """
        if not self.api_key or (_USE_GENAI and not self.client) or (not _USE_GENAI and not self.model):
            return PrunerDecision(impacted=True, reason="Missing API key or model initialization")

        # Cleanly escape/delimit code content to defend against prompt injection
        caller_source_clean = caller_source.replace("</source>", "<\\/source>")
        callee_diff_clean = callee_diff.replace("</diff>", "<\\/diff>")

        prompt = SEMANTIC_PRUNER_PROMPT.format(
            caller_source=caller_source_clean, callee_diff=callee_diff_clean
        )

        try:
            if _USE_GENAI:
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": PrunerDecision,
                    },
                )
            else:
                response = self.model.generate_content(
                    prompt, generation_config={"response_mime_type": "application/json"}
                )
            # Use Pydantic to parse and validate the JSON response
            data = json.loads(response.text)
            return PrunerDecision(**data)
        except Exception as e:
            # Fallback for safety: if LLM parsing fails, we assume it IS impacted
            # This ensures we never accidentally drop a breaking change.
            print(f"LLM parsing failed: {e}")
            return PrunerDecision(impacted=True, reason=f"Fallback due to error: {e}")

    def evaluate_impact(self, caller_source: str, callee_diff: str) -> bool:
        """
        Returns True if the caller is semantically impacted by the callee diff.
        Returns False if the change is benign (pruning it from the blast radius).
        """
        decision = self.evaluate_impact_detailed(caller_source, callee_diff)
        return decision.impacted

