// Pure helpers for the Intent panel (IN-11): types mirroring the IN-08 API,
// state/action legality, testability and state presentation, span highlighting,
// text truncation, optimistic updates and typed error classification.
//
// SECURITY: every string here that originates from intent sources, criteria or
// the API is UNTRUSTED. Nothing in this module produces HTML or markdown; the
// UI renders results as React text nodes only. Span offsets are validated
// against the text before slicing.

export const MAX_CRITERION_CHARS = 2000;
export const MAX_SOURCE_BYTES = 64 * 1024;
export const DISPLAY_TRUNCATE_CHARS = 280;

export type CriterionState =
  | "proposed"
  | "confirmed"
  | "rejected"
  | "edited"
  | "needs_reconfirmation"
  | "orphaned";

export const CRITERION_STATES: readonly CriterionState[] = [
  "needs_reconfirmation",
  "orphaned",
  "proposed",
  "edited",
  "confirmed",
  "rejected",
];

export type Testability =
  | "unrated"
  | "behavioral_testable"
  | "structural_checkable"
  | "non_functional_measurable"
  | "subjective_or_vague"
  | "untestable_external";

export type ExtractionMethod = "deterministic" | "llm" | "human";

export type CriterionAction = "confirm" | "reject" | "reopen" | "edit";

export type IntentOrigin = {
  method: ExtractionMethod | string;
  extractor_version: string;
  source_kind: string;
  source_id: string;
  source_hash: string;
  retrieved_at: string;
};

export type IntentSpan = { source_id: string; start: number; end: number };

export type IntentCriterion = {
  id: string;
  text: string;
  origin: IntentOrigin;
  span: IntentSpan;
  weight: number;
  testability: Testability | string;
  testability_rationale: string | null;
  state: CriterionState | string;
  hints: { paths: string[]; tests: string[]; label: string | null };
  /** B-11: verbatim source text at `span` for an LLM-proposed criterion (untrusted text). */
  source_quote?: string | null;
  source_quote_truncated?: boolean;
};

export type IntentSourceSummary = {
  kind: string;
  source_id: string;
  raw_text_hash: string;
  length: number | null;
  truncated: boolean;
  suspicious_content_removed: boolean;
  fetched_at: string | null;
};

export type IntentSourceDetail = IntentSourceSummary & { text: string };

export type SnapshotSummary = {
  id: string;
  analysis_id: string;
  version: number;
  parent_snapshot_id: string | null;
  created_at: string;
  criteria_count: number;
  state_counts: Record<string, number>;
  source_count: number;
};

export type IntentSnapshot = SnapshotSummary & {
  etag: string;
  criteria: IntentCriterion[];
  sources: IntentSourceSummary[];
};

export type CriterionSummary = {
  criterion_id: string;
  text: string;
  state: string;
  source: string;
};

export type CriterionDelta = {
  criterion_id: string;
  changed_fields: string[];
  text_before: string;
  text_after: string;
  state_before: string;
  state_after: string;
};

export type SnapshotDiff = {
  from_snapshot_id: string;
  to_snapshot_id: string;
  from_version: number;
  to_version: number;
  added: CriterionSummary[];
  removed: CriterionSummary[];
  changed: CriterionDelta[];
  state_changed: CriterionDelta[];
  moved: string[];
  sources_added: string[];
  sources_removed: string[];
  sources_changed: string[];
};

export type BuildResult = {
  snapshot: IntentSnapshot;
  created: boolean;
  report: {
    diagnostics: Array<{ code: string; source: string | null; detail: string }>;
    carry_events: Array<{
      action: string;
      criterion_id: string;
      previous_id: string | null;
      state: string;
    }>;
    absent_sources: string[];
  };
  sanitization: { removed: string[]; flagged: string[] };
};

export type CriterionResult = {
  criterion: IntentCriterion;
  snapshot_id: string;
  snapshot_version: number;
  etag: string;
  created: boolean;
};

export type CriterionChange = {
  snapshot_id: string;
  snapshot_version: number;
  criterion_id: string;
  old_state: string;
  new_state: string;
  actor: string;
  changed_at: string;
  old_text: string | null;
  new_text: string | null;
  reason: string | null;
};

// ---------------------------------------------------------------------------
// State machine (mirrors radius_intent.domain.criterion.ALLOWED_TRANSITIONS)
// ---------------------------------------------------------------------------

const TRANSITIONS: Record<CriterionState, readonly CriterionState[]> = {
  proposed: ["confirmed", "rejected", "edited"],
  edited: ["confirmed", "rejected", "edited", "needs_reconfirmation", "orphaned"],
  confirmed: ["edited", "rejected", "needs_reconfirmation", "orphaned"],
  needs_reconfirmation: ["confirmed", "rejected", "edited", "orphaned"],
  orphaned: ["rejected"],
  rejected: ["proposed"],
};

const ACTION_TARGET: Record<CriterionAction, CriterionState> = {
  confirm: "confirmed",
  reject: "rejected",
  reopen: "proposed",
  edit: "edited",
};

export function isCriterionState(value: string): value is CriterionState {
  return Object.prototype.hasOwnProperty.call(TRANSITIONS, value);
}

/** True when the server state machine would accept `action` from `state`. */
export function canApply(state: string, action: CriterionAction): boolean {
  if (!isCriterionState(state)) return false;
  return TRANSITIONS[state].includes(ACTION_TARGET[action]);
}

/** Actions the UI offers for a state, in display order. */
export function legalActions(state: string): CriterionAction[] {
  const order: CriterionAction[] = ["confirm", "edit", "reject", "reopen"];
  return order.filter((action) => canApply(state, action));
}

export function targetState(action: CriterionAction): CriterionState {
  return ACTION_TARGET[action];
}

// ---------------------------------------------------------------------------
// Presentation metadata
// ---------------------------------------------------------------------------

export type Tone = "good" | "info" | "warn" | "bad" | "neutral";

export function stateMeta(state: string): {
  label: string;
  tone: Tone;
  explanation: string;
} {
  switch (state) {
    case "proposed":
      return {
        label: "Proposed",
        tone: "info",
        explanation: "Extracted automatically. A human has not looked at it yet.",
      };
    case "confirmed":
      return {
        label: "Confirmed",
        tone: "good",
        explanation: "A human confirmed this is something the change must prove.",
      };
    case "rejected":
      return {
        label: "Rejected",
        tone: "neutral",
        explanation: "A human decided this is not a requirement. It is ignored.",
      };
    case "edited":
      return {
        label: "Edited",
        tone: "info",
        explanation: "A human reworded this criterion. Confirm it to accept it.",
      };
    case "needs_reconfirmation":
      return {
        label: "Needs reconfirmation",
        tone: "warn",
        explanation:
          "The source wording changed after a human decided on this criterion. Review it again.",
      };
    case "orphaned":
      return {
        label: "Orphaned",
        tone: "bad",
        explanation:
          "The source this criterion came from is gone or no longer contains it. Reject it, or re-add the source.",
      };
    default:
      return { label: "Unknown state", tone: "neutral", explanation: "Unrecognized state." };
  }
}

export function testabilityMeta(value: string): {
  label: string;
  tone: Tone;
  tooltip: string;
  guidance: string | null;
} {
  switch (value) {
    case "behavioral_testable":
      return {
        label: "Behavioral, testable",
        tone: "good",
        tooltip: "Describes observable behavior with inputs, outputs or conditions.",
        guidance: null,
      };
    case "structural_checkable":
      return {
        label: "Structural, checkable",
        tone: "good",
        tooltip: "A refactor, rename, config, dependency or docs change that can be checked from the diff.",
        guidance: null,
      };
    case "non_functional_measurable":
      return {
        label: "Non-functional, measurable",
        tone: "good",
        tooltip: "Performance, security or accessibility with a threshold or a named tool.",
        guidance: null,
      };
    case "subjective_or_vague":
      return {
        label: "Subjective or vague",
        tone: "warn",
        tooltip: "Words like clean, better or intuitive without a measure cannot be verified by a test.",
        guidance:
          "Hard to verify. Add a measurable threshold (for example 'p95 latency under 200 ms') or an observable behavior.",
      };
    case "untestable_external":
      return {
        label: "Untestable (external)",
        tone: "bad",
        tooltip: "Needs human, product or legal judgment, or live external systems.",
        guidance:
          "Radius cannot test this on its own. Add a measurable threshold or a concrete, observable check, or confirm it as a manual review item.",
      };
    case "unrated":
    default:
      return {
        label: "Unrated",
        tone: "neutral",
        tooltip: "Testability has not been rated yet.",
        guidance: null,
      };
  }
}

export function sourceKindLabel(kind: string): string {
  switch (kind) {
    case "pr_body":
      return "PR description";
    case "pr_title":
      return "PR title";
    case "issue":
      return "Linked issue";
    case "commit_message":
      return "Commit message";
    case "spec_file":
      return ".radius/intent.yml";
    case "agent_prompt":
      return "Agent prompt";
    case "comment":
      return "Added by a human";
    default:
      return "Source";
  }
}

export function methodLabel(method: string): { label: string; verify: boolean } {
  if (method === "llm") return { label: "LLM-proposed", verify: true };
  if (method === "human") return { label: "Human", verify: false };
  if (method === "deterministic") return { label: "Deterministic", verify: false };
  return { label: "Unknown", verify: true };
}

export function describeSourceFlags(source: IntentSourceSummary): string[] {
  const flags: string[] = [];
  if (source.truncated) {
    flags.push("Truncated: the source was longer than the limit, only the first part was used.");
  }
  if (source.suspicious_content_removed) {
    flags.push(
      "Suspicious content removed: hidden characters, HTML comments or secrets were stripped before storage.",
    );
  }
  return flags;
}

export function formatPercent(weight: number): string {
  if (!Number.isFinite(weight)) return "-";
  return `${Math.round(weight * 100)}%`;
}

export function formatByteCount(text: string): number {
  // UTF-8 length, as the server limit is in bytes.
  let bytes = 0;
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    bytes += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
  }
  return bytes;
}

export function formatKiB(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

export function countCodePoints(text: string): number {
  return Array.from(text).length;
}

// ---------------------------------------------------------------------------
// Text handling
// ---------------------------------------------------------------------------

/** Truncate by code points (never splits a surrogate pair). */
export function truncateText(
  text: string,
  max: number = DISPLAY_TRUNCATE_CHARS,
): { text: string; truncated: boolean } {
  const points = Array.from(text);
  if (points.length <= max) return { text, truncated: false };
  return { text: points.slice(0, Math.max(0, max)).join(""), truncated: true };
}

export type EditValidation = { ok: true; text: string } | { ok: false; message: string };

/** Validate criterion wording for add/edit. */
export function validateCriterionText(raw: string, current?: string): EditValidation {
  const text = raw.trim();
  if (text === "") return { ok: false, message: "Criterion text cannot be empty." };
  const length = countCodePoints(text);
  if (length > MAX_CRITERION_CHARS) {
    return {
      ok: false,
      message: `Criterion text is ${length} characters; the limit is ${MAX_CRITERION_CHARS}.`,
    };
  }
  if (current !== undefined && text === current.trim()) {
    return { ok: false, message: "The text is unchanged." };
  }
  return { ok: true, text };
}

export type SourceTextValidation = { ok: true } | { ok: false; message: string };

export function validateSourceText(text: string): SourceTextValidation {
  if (text.trim() === "") return { ok: false, message: "Enter some text first." };
  const bytes = formatByteCount(text);
  if (bytes > MAX_SOURCE_BYTES) {
    return {
      ok: false,
      message: `Text is ${formatKiB(bytes)}; the limit is ${formatKiB(MAX_SOURCE_BYTES)}.`,
    };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Span highlighting
// ---------------------------------------------------------------------------

export type HighlightSpan = { id: string; start: number; end: number };
export type HighlightSegment = { text: string; ids: string[] };

/**
 * Split `text` into segments for highlighting. Offsets are Unicode code point
 * indices (the API is Python, so emoji count as one), half-open. Spans that
 * are not finite integers, are empty/reversed, or fall outside the text are
 * dropped and counted in `invalid`; they never throw or slice out of range.
 * Overlapping spans yield segments carrying several ids. The returned strings
 * are plain text; the caller must render them as text nodes.
 */
export function highlightSegments(
  text: string,
  spans: readonly HighlightSpan[],
): { segments: HighlightSegment[]; invalid: number } {
  const points = Array.from(text);
  const length = points.length;
  const valid: HighlightSpan[] = [];
  let invalid = 0;
  for (const span of spans) {
    if (
      !Number.isInteger(span.start) ||
      !Number.isInteger(span.end) ||
      span.start < 0 ||
      span.end > length ||
      span.start >= span.end
    ) {
      invalid += 1;
      continue;
    }
    valid.push(span);
  }
  if (valid.length === 0) {
    return { segments: length === 0 ? [] : [{ text, ids: [] }], invalid };
  }
  const cuts = new Set<number>([0, length]);
  for (const span of valid) {
    cuts.add(span.start);
    cuts.add(span.end);
  }
  const ordered = [...cuts].sort((a, b) => a - b);
  const segments: HighlightSegment[] = [];
  for (let i = 0; i < ordered.length - 1; i += 1) {
    const from = ordered[i];
    const to = ordered[i + 1];
    const ids = valid
      .filter((span) => span.start <= from && span.end >= to)
      .map((span) => span.id);
    segments.push({ text: points.slice(from, to).join(""), ids });
  }
  return { segments, invalid };
}

// ---------------------------------------------------------------------------
// Grouping, filtering and optimistic updates
// ---------------------------------------------------------------------------

export function countByState(criteria: readonly IntentCriterion[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const criterion of criteria) {
    counts[criterion.state] = (counts[criterion.state] ?? 0) + 1;
  }
  return counts;
}

export function filterByState(
  criteria: readonly IntentCriterion[],
  state: string | "all",
): IntentCriterion[] {
  if (state === "all") return [...criteria];
  return criteria.filter((criterion) => criterion.state === state);
}

/** Criteria that need a human's attention first. */
export function needsAttention(criteria: readonly IntentCriterion[]): number {
  return criteria.filter(
    (c) => c.state === "needs_reconfirmation" || c.state === "orphaned",
  ).length;
}

/** Predict the result of an action locally, for optimistic rendering. */
export function applyOptimistic(
  criteria: readonly IntentCriterion[],
  criterionId: string,
  action: CriterionAction,
  text?: string,
): IntentCriterion[] {
  return criteria.map((criterion) => {
    if (criterion.id !== criterionId || !canApply(criterion.state, action)) return criterion;
    return {
      ...criterion,
      state: targetState(action),
      text: action === "edit" && text !== undefined ? text : criterion.text,
    };
  });
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/** Shape of the error thrown by `radiusRequest` (class RadiusApiError in lib/api.ts). */
export type ApiErrorLike = Error & { name: "RadiusApiError"; status: number; code: string | null };

function isApiError(error: unknown): error is ApiErrorLike {
  return error instanceof Error && error.name === "RadiusApiError";
}

export type IntentErrorInfo =
  | { kind: "not_found"; message: string }
  | { kind: "stale"; message: string }
  | { kind: "illegal_transition"; message: string }
  | { kind: "spec_invalid"; message: string; lines: string[] }
  | { kind: "other"; message: string; code: string | null };

/** Extract the "line N: ..." messages of an INTENT_SPEC_INVALID message. */
export function parseSpecErrorLines(message: string): string[] {
  const found: string[] = [];
  const pattern = /line\s+(\d+):\s*(.*?)(?=(?:;|\n|,)?\s*line\s+\d+:|\n|$)/gi;
  for (const match of message.matchAll(pattern)) {
    const detail = match[2].trim().replace(/[;,]$/, "");
    if (detail) found.push(`line ${match[1]}: ${detail}`);
  }
  return found;
}

export function classifyIntentError(error: unknown): IntentErrorInfo {
  if (!isApiError(error)) {
    return {
      kind: "other",
      message: error instanceof Error ? error.message : String(error),
      code: null,
    };
  }
  switch (error.code) {
    case "INTENT_NOT_FOUND":
      return { kind: "not_found", message: error.message };
    case "INTENT_STALE":
      return {
        kind: "stale",
        message: "Someone changed this intent while you were looking at it. Reload to see the latest version.",
      };
    case "ILLEGAL_STATE_TRANSITION":
      return {
        kind: "illegal_transition",
        message: "That change is not allowed from the criterion's current state. Reload and try again.",
      };
    case "INTENT_SPEC_INVALID": {
      const lines = parseSpecErrorLines(error.message);
      return { kind: "spec_invalid", message: error.message, lines };
    }
    default:
      return { kind: "other", message: error.message, code: error.code };
  }
}

// ---------------------------------------------------------------------------
// Header value validation (client side mirrors lib/proxy.ts rules)
// ---------------------------------------------------------------------------

export const ACTOR_PATTERN = /^[A-Za-z0-9_.@:+-]{1,128}$/;

/** Build the audit label for a signed-in user, or null to omit the header. */
export function actorLabel(user: { id?: string | null } | null | undefined): string | null {
  const id = user?.id;
  if (!id) return null;
  const label = `user:${id}`;
  return ACTOR_PATTERN.test(label) ? label : null;
}

export const MAX_SOURCE_QUOTE_CHARS = 500;

/**
 * B-11: the evidence shown next to an LLM-proposed criterion, so a human confirms the
 * wording against the exact text it was drawn from. Plain text only (callers render it as a
 * React text node, never as HTML). `null` when there is nothing to show.
 */
export function sourceQuoteView(
  criterion: Pick<IntentCriterion, "origin" | "source_quote" | "source_quote_truncated">,
): { quote: string; truncated: boolean } | null {
  if (criterion.origin.method !== "llm") return null;
  const raw = criterion.source_quote;
  if (typeof raw !== "string" || raw.trim() === "") return null;
  const cut = truncateText(raw, MAX_SOURCE_QUOTE_CHARS);
  return { quote: cut.truncated ? cut.text : raw, truncated: cut.truncated || criterion.source_quote_truncated === true };
}
