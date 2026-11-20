// Client for the advisory AI review (DEC-041) through the same-origin proxy. The browser
// never holds the API key. Only this one GET route is allowlisted in lib/proxy.ts.

import { radiusRequest } from "./api.ts";
import { parseAiReview, type AiReview } from "./ai-review-model.ts";

/** Load the stored review. Rejects with RadiusApiError (404 = none) or an Error. */
export async function getAiReview(analysisId: string): Promise<AiReview> {
  const result = await radiusRequest<unknown>(`/analyses/${encodeURIComponent(analysisId)}/ai-review`);
  const parsed = parseAiReview(result.data);
  if (!parsed.ok) throw new Error(parsed.reason);
  return parsed.value;
}
