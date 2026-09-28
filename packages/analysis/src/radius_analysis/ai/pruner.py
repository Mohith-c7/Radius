import json

try:
    from google import genai

    _USE_GENAI = True
except ImportError:
    import google.generativeai as genai

    _USE_GENAI = False

from .prompts import SEMANTIC_PRUNER_PROMPT


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

    def evaluate_impact(self, caller_source: str, callee_diff: str) -> bool:
        """
        Returns True if the caller is semantically impacted by the callee diff.
        Returns False if the change is benign (pruning it from the blast radius).
        """
        if not self.api_key or (_USE_GENAI and not self.client) or (not _USE_GENAI and not self.model):
            return True

        prompt = SEMANTIC_PRUNER_PROMPT.format(
            caller_source=caller_source, callee_diff=callee_diff
        )

        try:
            if _USE_GENAI:
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
            else:
                response = self.model.generate_content(
                    prompt, generation_config={"response_mime_type": "application/json"}
                )
            data = json.loads(response.text)
            return bool(data.get("impacted", True))
        except Exception as e:
            # Fallback for safety: if LLM parsing fails, we assume it IS impacted
            # This ensures we never accidentally drop a breaking change.
            print(f"LLM parsing failed: {e}")
            return True

