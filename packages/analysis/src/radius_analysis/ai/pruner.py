import json
import google.generativeai as genai
from .prompts import SEMANTIC_PRUNER_PROMPT

class SemanticPruner:
    """Invokes Google Gemini to evaluate the semantic impact of a code change."""
    
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        # Using Flash as it is lightning fast for small context JSON tasks
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
    def evaluate_impact(self, caller_source: str, callee_diff: str) -> bool:
        """
        Returns True if the caller is semantically impacted by the callee diff.
        Returns False if the change is benign (pruning it from the blast radius).
        """
        prompt = SEMANTIC_PRUNER_PROMPT.format(
            caller_source=caller_source,
            callee_diff=callee_diff
        )
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text)
            return bool(data.get("impacted", True))
        except Exception as e:
            # Fallback for safety: if LLM parsing fails, we assume it IS impacted
            # This ensures we never accidentally drop a breaking change.
            print(f"LLM parsing failed: {e}")
            return True
