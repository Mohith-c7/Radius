// Client for the Intent API (IN-08) through the same-origin proxy. The browser
// never holds the API key; `ifMatch` and `actor` are validated again by the
// proxy before they are forwarded (lib/proxy.ts).

import { radiusRequest } from "./api.ts";
import type {
  BuildResult,
  CriterionChange,
  CriterionResult,
  IntentSnapshot,
  IntentSourceDetail,
  SnapshotDiff,
  SnapshotSummary,
} from "./intent-model.ts";

export type SubmittableKind = "agent_prompt" | "spec_file" | "pr_body" | "pr_title" | "issue";

export type WriteOptions = {
  /** ETag of the snapshot the user was looking at. */
  ifMatch?: string | null;
  /** Audit label from the signed-in session, or null to omit. */
  actor?: string | null;
};

const base = (analysisId: string) => `/analyses/${encodeURIComponent(analysisId)}/intent`;

/** Latest snapshot. Rejects with RadiusApiError code INTENT_NOT_FOUND when none exists yet. */
export async function getIntent(
  analysisId: string,
): Promise<{ snapshot: IntentSnapshot; etag: string | null }> {
  const result = await radiusRequest<IntentSnapshot>(base(analysisId));
  return { snapshot: result.data, etag: result.etag ?? result.data.etag ?? null };
}

export async function getIntentSources(analysisId: string): Promise<IntentSourceDetail[]> {
  return (await radiusRequest<IntentSourceDetail[]>(`${base(analysisId)}/sources`)).data;
}

export async function listSnapshots(
  analysisId: string,
  cursor?: number,
): Promise<{ snapshots: SnapshotSummary[]; nextCursor: number | null }> {
  const query = cursor ? `?cursor=${encodeURIComponent(String(cursor))}` : "";
  const result = await radiusRequest<SnapshotSummary[]>(`${base(analysisId)}/snapshots${query}`);
  const next = result.meta.nextCursor;
  return { snapshots: result.data, nextCursor: typeof next === "number" ? next : null };
}

/** `from` and `to` are snapshot version numbers. */
export async function getIntentDiff(
  analysisId: string,
  fromVersion: number,
  toVersion: number,
): Promise<SnapshotDiff> {
  const query = `?from=${encodeURIComponent(String(fromVersion))}&to=${encodeURIComponent(String(toVersion))}`;
  return (await radiusRequest<SnapshotDiff>(`${base(analysisId)}/diff${query}`)).data;
}

export async function submitIntentSource(
  analysisId: string,
  payload: { kind: SubmittableKind; text: string; sourceId?: string },
  options: WriteOptions = {},
): Promise<BuildResult> {
  const body: Record<string, string> = { kind: payload.kind, text: payload.text };
  if (payload.sourceId) body.sourceId = payload.sourceId;
  return (
    await radiusRequest<BuildResult>(`${base(analysisId)}/sources`, {
      method: "POST",
      body: JSON.stringify(body),
      ifMatch: options.ifMatch,
      actor: options.actor,
    })
  ).data;
}

export async function rebuildIntent(
  analysisId: string,
  options: WriteOptions = {},
): Promise<BuildResult> {
  return (
    await radiusRequest<BuildResult>(`${base(analysisId)}/rebuild`, {
      method: "POST",
      ifMatch: options.ifMatch,
      actor: options.actor,
    })
  ).data;
}

export type CriterionPatch =
  | { action: "confirm" | "reopen"; reason?: string }
  | { action: "reject"; reason?: string }
  | { action: "edit"; text: string; reason?: string };

export async function patchCriterion(
  analysisId: string,
  criterionId: string,
  patch: CriterionPatch,
  options: WriteOptions = {},
): Promise<CriterionResult> {
  return (
    await radiusRequest<CriterionResult>(
      `${base(analysisId)}/criteria/${encodeURIComponent(criterionId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(patch),
        ifMatch: options.ifMatch,
        actor: options.actor,
      },
    )
  ).data;
}

export async function addCriterion(
  analysisId: string,
  payload: { text: string; reason?: string },
  options: WriteOptions = {},
): Promise<CriterionResult> {
  return (
    await radiusRequest<CriterionResult>(`${base(analysisId)}/criteria`, {
      method: "POST",
      body: JSON.stringify(payload),
      ifMatch: options.ifMatch,
      actor: options.actor,
    })
  ).data;
}

export async function getCriterionHistory(
  analysisId: string,
  criterionId: string,
): Promise<CriterionChange[]> {
  return (
    await radiusRequest<CriterionChange[]>(
      `${base(analysisId)}/criteria/${encodeURIComponent(criterionId)}/history`,
    )
  ).data;
}
