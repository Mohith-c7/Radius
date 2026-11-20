// Advisory AI review (DEC-041): parse and classify the API payload. Pure functions, no
// React, so they are unit tested (tests/ai-review.test.mjs).
//
// SECURITY: every text field was written by an LLM that read untrusted PR content. The
// API validated it, and the UI still renders it ONLY as React text nodes (no
// dangerouslySetInnerHTML, no markdown, no links).

export const AI_SECTIONS = [
  { key: "risks", title: "Main risks" },
  { key: "tests", title: "Tests that matter" },
  { key: "missing_evidence", title: "Missing evidence" },
  { key: "next_steps", title: "Next steps" },
] as const;

export type AiSectionKey = (typeof AI_SECTIONS)[number]["key"];

export type AiReviewItem = { text: string; files: string[] };

export type AiReview = {
  analysisId: string;
  status: "ok" | "unavailable";
  reasonCode: string | null;
  label: string;
  model: string | null;
  generatedAt: string;
  summary: string | null;
  sections: Record<AiSectionKey, AiReviewItem[]>;
  injectionFlagged: boolean;
  diffTruncated: boolean;
};

export const MAX_TEXT_CHARS = 700;
const MAX_ITEMS = 5;
const MAX_FILES = 5;

const DEFAULT_LABEL =
  "AI-generated and advisory. It does not change the Radius verdict, score or check result; verify every point yourself.";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function clip(value: unknown, max = MAX_TEXT_CHARS): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function items(value: unknown): AiReviewItem[] {
  if (!Array.isArray(value)) return [];
  const out: AiReviewItem[] = [];
  for (const raw of value.slice(0, MAX_ITEMS)) {
    if (!isObject(raw)) continue;
    const text = clip(raw.text, 400);
    if (!text) continue;
    const files = Array.isArray(raw.files)
      ? raw.files.filter((f): f is string => typeof f === "string" && f.length > 0).slice(0, MAX_FILES).map((f) => clip(f, 300))
      : [];
    out.push({ text, files });
  }
  return out;
}

/** Validate the API payload. Anything that is not an advisory AI review is rejected. */
export function parseAiReview(data: unknown): { ok: true; value: AiReview } | { ok: false; reason: string } {
  if (!isObject(data)) return { ok: false, reason: "The AI review payload is not an object." };
  if (data.advisory !== true || data.ai_generated !== true) {
    return { ok: false, reason: "The AI review payload is not marked advisory." };
  }
  const status = data.status === "ok" ? "ok" : data.status === "unavailable" ? "unavailable" : null;
  if (!status) return { ok: false, reason: "The AI review has an unknown status." };
  const notes = isObject(data.notes) ? data.notes : {};
  const sections = {} as Record<AiSectionKey, AiReviewItem[]>;
  for (const { key } of AI_SECTIONS) sections[key] = status === "ok" ? items(data[key]) : [];
  const summary = status === "ok" ? clip(data.summary) || null : null;
  if (status === "ok" && !summary) return { ok: false, reason: "The AI review has no summary." };
  return {
    ok: true,
    value: {
      analysisId: clip(data.analysis_id, 64),
      status,
      reasonCode: typeof data.reason_code === "string" ? clip(data.reason_code, 64) : null,
      label: clip(data.label) || DEFAULT_LABEL,
      model: typeof data.model === "string" ? clip(data.model, 128) : null,
      generatedAt: clip(data.generated_at, 40),
      summary,
      sections,
      injectionFlagged: Array.isArray(notes.injection_flags) && notes.injection_flags.length > 0,
      diffTruncated: notes.diff_truncated === true,
    },
  };
}

/** Plain-language reason for an unavailable review. */
export function unavailableText(reasonCode: string | null): string {
  const code = reasonCode ?? "";
  if (code === "provider_rate_limited" || code === "provider_budget")
    return "The AI provider's free-tier limit was reached; try a rerun later.";
  if (code === "deadline" || code === "provider_timeout")
    return "The AI provider did not answer in time.";
  if (code.startsWith("output_"))
    return "The AI answer did not pass Radius's safety checks and was discarded.";
  if (code === "provider_auth") return "The AI provider rejected the configured key.";
  return "The AI review could not be generated for this analysis.";
}

export type AiReviewErrorInfo = { kind: "absent" } | { kind: "other"; message: string };

/** 404 (`not_generated`, unknown analysis): render nothing. Anything else: an error line. */
export function classifyAiReviewError(error: unknown): AiReviewErrorInfo {
  const e = (isObject(error) || error instanceof Error ? error : {}) as { status?: unknown; message?: unknown };
  if (e.status === 404) return { kind: "absent" };
  const message = typeof e.message === "string" ? e.message : "The AI review could not be loaded.";
  return { kind: "other", message: clip(message, 300) };
}
