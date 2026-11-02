// Client for the Verdict v2 API (VS-09) through the same-origin proxy. The
// browser never holds the API key. Only this one GET route is allowlisted in
// lib/proxy.ts.

import { radiusRequest } from "./api.ts";
import { parseVerdictV2, type VerdictV2 } from "./verdict-v2-model.ts";

export type VerdictLoad = { verdict: VerdictV2; etag: string | null };

/**
 * Load the stored verdict. Rejects with RadiusApiError (404 with
 * `meta.reason` disabled / not_computed) or an Error when the payload is not
 * a v2 verdict; use classifyVerdictError to interpret it.
 */
export async function getVerdictV2(analysisId: string): Promise<VerdictLoad> {
  const result = await radiusRequest<unknown>(
    `/analyses/${encodeURIComponent(analysisId)}/verdict-v2`,
  );
  const parsed = parseVerdictV2(result.data);
  if (!parsed.ok) throw new Error(parsed.reason);
  return { verdict: parsed.value, etag: result.etag };
}
