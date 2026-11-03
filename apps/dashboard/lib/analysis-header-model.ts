// Pure view model of the analysis detail page header (pill, headline,
// recommendation, legacy v1 block). It exists so the page tells ONE story:
// when a Verdict v2 result is available it owns the verdict, the headline and
// the recommendation; the v1 heuristic (0-100 ring, "Verified: every
// executable change ..." sentence) is demoted into a clearly labelled legacy
// block that is never styled as a pass unless v2 itself says supported.
//
// Product rule: missing evidence never reads as a pass. In v2 mode no tone is
// ever "good" (green): even "Supported by static evidence (alpha)" is "info",
// matching the Verdict v2 panel and the Check Run (advisory mode is never
// green). Status is always carried by words, never by colour alone.
//
// All strings are plain text; the page renders them as React text nodes.

import type { VerdictV2 } from "./verdict-v2-model.ts";

export type HeaderTone = "good" | "warn" | "bad" | "info" | "neutral";

/** The v2 input of the header: not yet loaded, absent/off/unavailable, or a result. */
export type V2Input = "loading" | VerdictV2 | null;

export type V1Input = {
  verificationStatus?: string | null;
  summary?: string | null;
  score: number;
  scoreKind?: string | null;
  recommendations: readonly string[];
  /** Percent of changed files with test evidence, when reported. */
  analysisCompleteness?: number | null;
} | null;

export const LEGACY_TITLE = "Legacy v1 result (file-level test selection, uncalibrated heuristic)";
export const V1_NO_REPORT_HEADLINE = "Analysis artifacts are being prepared";
export const V1_NO_RECOMMENDATION = "Radius has not generated recommendations for this analysis yet.";
export const LOADING_HEADLINE = "Loading the verdict...";
export const MAX_SHOWN_ACTIONS = 5;

export type LegacyBlock = {
  title: string;
  /** "v1 status: Verified" - words, neutral styling. */
  statusText: string;
  /** The v1 sentence, shown verbatim but labelled as legacy. */
  sentence: string | null;
  scoreText: string;
  score: number;
  scoreKind: string | null;
  evidenceText: string | null;
};

export type HeaderModel = {
  source: "v1" | "v2" | "loading";
  /** Stable key for tests / styling: the v2 verdict, or "v1". */
  verdictKey: string;
  pill: { label: string; tone: HeaderTone } | null;
  headline: string;
  /** "0 of 2 stated criteria supported ..." (v2 only). */
  summaryLine: string | null;
  /** Deciding reason of v2 (text), shown under the headline. */
  reasonLine: string | null;
  /** v1 only: show the big ring + "score (not a probability)" next to the headline. */
  showPrimaryRing: boolean;
  recommendation: {
    lead: string;
    actions: string[];
    hiddenActions: number;
    /** false when the lead is a neutral/muted statement, true for a "do not treat as verified" warning. */
    warning: boolean;
  };
  legacy: LegacyBlock | null;
};

// ---------------------------------------------------------------------------
// v1 presentation (unchanged wording and tones; used when v2 is absent)
// ---------------------------------------------------------------------------

export function v1Presentation(status?: string | null): { label: string; tone: HeaderTone } {
  switch ((status ?? "").toLowerCase()) {
    case "verified":
      return { label: "Verified", tone: "good" };
    case "failed":
      return { label: "Failed", tone: "bad" };
    default:
      return { label: "Not verified (insufficient evidence)", tone: "warn" };
  }
}

// ---------------------------------------------------------------------------
// v2 wording
// ---------------------------------------------------------------------------

type V2Kind = "verified" | "failed" | "needs_review" | "insufficient_evidence" | "pending" | "unknown";

function kindOf(v2: VerdictV2): V2Kind {
  if (v2.pending) return "pending";
  switch (v2.verdict) {
    case "verified":
    case "failed":
    case "needs_review":
    case "insufficient_evidence":
      return v2.verdict;
    default:
      return "unknown";
  }
}

function basisQualifier(v2: VerdictV2): string {
  return v2.summary.evidence_basis === "static_and_mutation"
    ? "alpha, static + sampled mutation evidence"
    : "alpha, static evidence only";
}

function pillFor(kind: V2Kind, v2: VerdictV2): { label: string; tone: HeaderTone } {
  const q = basisQualifier(v2);
  switch (kind) {
    case "verified":
      return { label: "Supported by static evidence (alpha)", tone: "info" };
    case "failed":
      return { label: `Failed (${q})`, tone: "bad" };
    case "needs_review":
      return { label: `Needs review (${q})`, tone: "warn" };
    case "insufficient_evidence":
      return { label: `Not verified - insufficient evidence (${q})`, tone: "warn" };
    case "pending":
      return { label: "Awaiting CI test results (alpha)", tone: "info" };
    default:
      return { label: `Not verified - no verdict (${q})`, tone: "warn" };
  }
}

function summaryLineFor(v2: VerdictV2): string {
  const s = v2.summary;
  const text = v2.presentation?.summary_text;
  if (text) return text;
  return `${s.proven} of ${s.criteria_total} stated criteria supported (alpha, uncalibrated).`;
}

const LEAD: Record<V2Kind, string> = {
  verified:
    "Static evidence supports the stated intent (alpha, uncalibrated; not a proof of correctness). Still review the change.",
  failed:
    "Do not treat this PR as verified: Radius found a problem with the evidence for the stated intent. Review the reason and the criteria below.",
  needs_review:
    "Do not treat this PR as verified: it needs a human review before anyone relies on this result.",
  insufficient_evidence:
    "Do not treat this PR as verified: there is not enough evidence that the stated intent is covered. Missing evidence is not a pass.",
  pending:
    "Do not treat this PR as verified yet: Radius is waiting for CI test results for this commit.",
  unknown:
    "Do not treat this PR as verified: Radius has no verdict for this commit. Missing evidence is not a pass.",
};

function v2Reason(v2: VerdictV2): string | null {
  if (v2.pending) return "Waiting for CI test results for this commit before judging the evidence.";
  return v2.reasons[0]?.detail || null;
}

function legacyBlock(v1: V1Input): LegacyBlock | null {
  if (!v1) return null;
  const status = v1Presentation(v1.verificationStatus).label;
  const kind = v1.scoreKind === "calibrated" ? "calibrated" : "uncalibrated heuristic, not a probability";
  const completeness =
    v1.analysisCompleteness === null || v1.analysisCompleteness === undefined
      ? null
      : `Changed files with test evidence: ${Math.round(v1.analysisCompleteness)}% (file-level, v1)`;
  return {
    title: LEGACY_TITLE,
    statusText: `v1 status: ${status}`,
    sentence: v1.summary || null,
    scoreText: `Heuristic score ${v1.score || "-"}${v1.score > 0 ? "/100" : ""} (${kind})`,
    score: v1.score,
    scoreKind: v1.scoreKind ?? null,
    evidenceText: completeness,
  };
}

// ---------------------------------------------------------------------------
// the mapping
// ---------------------------------------------------------------------------

export function buildHeaderModel(v1: V1Input, v2: V2Input): HeaderModel {
  if (v2 === "loading") {
    // Never flash a v1 "Verified" while v2 may still be about to contradict it.
    return {
      source: "loading",
      verdictKey: "loading",
      pill: { label: "Checking the verdict", tone: "neutral" },
      headline: LOADING_HEADLINE,
      summaryLine: null,
      reasonLine: null,
      showPrimaryRing: false,
      recommendation: { lead: LOADING_HEADLINE, actions: [], hiddenActions: 0, warning: false },
      legacy: null,
    };
  }

  // v2 absent, off, not computed, errored or unavailable (status != ok): exactly today's header.
  if (v2 === null || v2.status !== "ok") {
    const pill = v1 ? v1Presentation(v1.verificationStatus) : null;
    return {
      source: "v1",
      verdictKey: "v1",
      pill,
      headline: v1?.summary ?? V1_NO_REPORT_HEADLINE,
      summaryLine: null,
      reasonLine: null,
      showPrimaryRing: true,
      recommendation: {
        lead: v1?.recommendations.join(" ") || V1_NO_RECOMMENDATION,
        actions: [],
        hiddenActions: 0,
        warning: false,
      },
      legacy: null,
    };
  }

  const kind = kindOf(v2);
  const pill = pillFor(kind, v2);
  const all = v2.next_actions.map((a) => a.text).filter((t) => t.length > 0);
  return {
    source: "v2",
    verdictKey: kind === "pending" ? "pending" : (v2.verdict ?? "none"),
    pill,
    headline: pill.label,
    summaryLine: summaryLineFor(v2),
    reasonLine: v2Reason(v2),
    showPrimaryRing: false,
    recommendation: {
      lead: LEAD[kind],
      actions: all.slice(0, MAX_SHOWN_ACTIONS),
      hiddenActions: Math.max(0, all.length - MAX_SHOWN_ACTIONS),
      warning: kind !== "verified",
    },
    legacy: legacyBlock(v1),
  };
}

/** Text colour for a tone (the dashboard's existing palette). Words always accompany it. */
export function toneColor(tone: HeaderTone): string {
  switch (tone) {
    case "good":
      return "#64C89D";
    case "bad":
      return "#F87171";
    case "warn":
      return "#FBBF24";
    case "info":
      return "#2D6FCA";
    default:
      return "#70807A";
  }
}
