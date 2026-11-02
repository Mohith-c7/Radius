// Pure view model of the Verdict v2 panel (VS-10): tolerant payload parsing,
// state/verdict presentation, evidence quality breakdown and the justification
// tree. Mirrors docs/research/design/verdict_v2.schema.json.
//
// SECURITY: criterion text, test ids, tamper reasons and snippets derive from
// PR content and are UNTRUSTED. Nothing here produces HTML or markdown; the
// panel renders every string as a React text node. Unknown fields and unknown
// enum values are tolerated (they render as neutral text), arrays and strings
// are capped so a hostile or huge payload cannot freeze the page.

export const MAX_CRITERIA = 200;
export const MAX_ITEMS_PER_CRITERION = 100;
export const MAX_TAMPER_FINDINGS = 100;
export const MAX_LIST = 200;
export const MAX_TEXT_CHARS = 2000;
export const MAX_SNIPPET_CHARS = 1200;
export const DEFAULT_TAU_SUPPORT = 0.5;

export const STATIC_ONLY_LABEL = "Static assertion strength only (no mutation testing)";
export const UNCALIBRATED_LABEL = "Uncalibrated: no probability, no score";
/** Presentation wording (alpha); the internal enum values (`proven`, `verified`) are unchanged. */
export const DISCLAIMER =
  "Alpha: static evidence only (assertion strength, no mutation testing); thresholds are uncalibrated. This is not a proof of correctness.";
export const LEGEND =
  "supported = static assertion strength above threshold; not a proof of correctness";
export const PROVENANCE_LABELS: Record<string, string> = {
  author_pr_body: "PR author (description)",
  author_head_spec: "PR author (spec file in this PR)",
  base_spec: "Base branch spec",
  human_confirmed: "Human confirmed",
  llm_proposed: "LLM proposed",
};

export type SupportState = "proven" | "weak" | "unevidenced" | "contradicted" | "excluded";
export const SUPPORT_STATES: readonly SupportState[] = [
  "proven",
  "weak",
  "unevidenced",
  "contradicted",
  "excluded",
];

export type Tone = "good" | "warn" | "bad" | "info" | "neutral";
export type IconName =
  | "check"
  | "alert"
  | "help"
  | "x"
  | "minus"
  | "shield"
  | "clock"
  | "ban";

export type Reason = { code: string; detail: string; rule_id: string | null };

export type EvidenceItem = {
  evidence_id: string;
  test_id: string;
  outcome: string;
  status: string;
  a_static: number;
  d_eff: number;
  i: number;
  f: number;
  flaky_f: number;
  tamper_penalty: number;
  q: number;
  l: number;
  term: number;
  contribution: number | null;
  l_cs: number | null;
  l_st: number | null;
  r_ct: number | null;
};

export type BestLink = { symbol_id: string; l_cs: number; l_st: number; r_ct: number };

export type Criterion = {
  criterion_id: string;
  text: string;
  state: SupportState | "unknown";
  rawState: string;
  S: number;
  S_raw: number;
  weight: number;
  testability: string;
  lifecycle: string;
  flags: string[];
  provenance: string;
  hints: Hint[];
  reasons: Reason[];
  best_link: BestLink | null;
  items: EvidenceItem[];
  itemsTruncated: boolean;
};

export type TamperFinding = {
  finding_id: string;
  rule_id: string;
  severity: string;
  path: string;
  reason: string;
  check: string;
  symbol: string | null;
  test_id: string | null;
  old_snippet: string | null;
  new_snippet: string | null;
};

export type NextAction = { code: string; text: string; criterion_id: string | null };

export type Summary = {
  criteria_total: number;
  proven: number;
  weak: number;
  unevidenced: number;
  contradicted: number;
  excluded: number;
  uim: number;
  intent_coverage: number;
  tamper: Record<string, number>;
  evidence_basis: string;
  author_hint_criteria: number;
};

export type Hint = { kind: string; value: string; provenance: string };

export type RuleResult = {
  id: string;
  label: string;
  fired: boolean;
  inputs: Array<{ key: string; text: string }>;
  refs: Array<{ key: string; ids: string[] }>;
};

export type Justification = {
  verdict: string;
  decided_by: string;
  rules: RuleResult[];
  thresholds: Array<{ key: string; text: string }>;
  versions: Array<{ key: string; text: string }>;
  config_digest: string;
  inputs_digest: string;
  profile: string;
};

export type V1Block = {
  verification_status: string;
  confidence_score: number | null;
  score_kind: string;
  risk_level: string | null;
};

export type VerdictV2 = {
  algo_version: string;
  profile: string;
  mode: string;
  status: string;
  analysis_id: string;
  head_sha: string;
  revision: number;
  computed_at: string | null;
  verdict: string | null;
  pending: boolean;
  reasons: Reason[];
  summary: Summary;
  criteria: Criterion[];
  criteriaTruncated: boolean;
  tamper_findings: TamperFinding[];
  unlinked_symbols: string[];
  next_actions: NextAction[];
  justification: Justification | null;
  v1: V1Block | null;
  error: { code: string; fallback: string | null } | null;
  tauSupport: number;
  uimMax: number | null;
  minIntentCoverage: number | null;
};

// ---------------------------------------------------------------------------
// tolerant readers
// ---------------------------------------------------------------------------

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const str = (value: unknown, fallback = ""): string => (typeof value === "string" ? value : fallback);
const optStr = (value: unknown): string | null => (typeof value === "string" ? value : null);
const num = (value: unknown, fallback = 0): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const optNum = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const strs = (value: unknown): string[] =>
  arr(value)
    .filter((v): v is string => typeof v === "string")
    .slice(0, MAX_LIST);

export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/** Truncate by code points (never splits a surrogate pair), adding an ellipsis. */
export function truncateText(text: string, max: number): string {
  const points = Array.from(text);
  return points.length <= max ? text : `${points.slice(0, max).join("")}…`;
}

function parseReason(raw: unknown): Reason | null {
  if (!isObject(raw)) return null;
  return {
    code: str(raw.code),
    detail: truncateText(str(raw.detail), MAX_TEXT_CHARS),
    rule_id: optStr(raw.rule_id),
  };
}

const reasons = (raw: unknown): Reason[] =>
  arr(raw)
    .map(parseReason)
    .filter((r): r is Reason => r !== null)
    .slice(0, MAX_LIST);

function parseItem(raw: unknown): EvidenceItem | null {
  if (!isObject(raw)) return null;
  return {
    evidence_id: str(raw.evidence_id),
    test_id: truncateText(str(raw.test_id), MAX_TEXT_CHARS),
    outcome: str(raw.outcome, "not_run"),
    status: str(raw.status),
    a_static: clamp01(num(raw.a_static)),
    d_eff: clamp01(num(raw.d_eff)),
    i: clamp01(num(raw.i)),
    f: clamp01(num(raw.f)),
    flaky_f: clamp01(num(raw.flaky_f, 1)),
    tamper_penalty: clamp01(num(raw.tamper_penalty)),
    q: clamp01(num(raw.q)),
    l: clamp01(num(raw.l)),
    term: clamp01(num(raw.term)),
    contribution: optNum(raw.contribution),
    l_cs: optNum(raw.l_cs),
    l_st: optNum(raw.l_st),
    r_ct: optNum(raw.r_ct),
  };
}

function parseBestLink(raw: unknown): BestLink | null {
  if (!isObject(raw) || typeof raw.symbol_id !== "string") return null;
  return {
    symbol_id: truncateText(raw.symbol_id, MAX_TEXT_CHARS),
    l_cs: clamp01(num(raw.l_cs)),
    l_st: clamp01(num(raw.l_st)),
    r_ct: clamp01(num(raw.r_ct)),
  };
}

export function normalizeState(raw: unknown): SupportState | "unknown" {
  return typeof raw === "string" && (SUPPORT_STATES as readonly string[]).includes(raw)
    ? (raw as SupportState)
    : "unknown";
}

function parseCriterion(raw: unknown): Criterion | null {
  if (!isObject(raw)) return null;
  const rawItems = arr(raw.items);
  return {
    criterion_id: str(raw.criterion_id),
    text: truncateText(str(raw.text), MAX_TEXT_CHARS),
    state: normalizeState(raw.state),
    rawState: str(raw.state),
    S: clamp01(num(raw.S)),
    S_raw: clamp01(num(raw.S_raw)),
    weight: num(raw.weight, 1),
    testability: str(raw.testability),
    lifecycle: str(raw.lifecycle),
    flags: strs(raw.flags),
    provenance: str(raw.provenance, "author_pr_body"),
    hints: arr(raw.hints)
      .slice(0, MAX_LIST)
      .filter(isObject)
      .map((h) => ({
        kind: str(h.kind),
        value: truncateText(str(h.value), 300),
        provenance: str(h.provenance, "author_pr_body"),
      })),
    reasons: reasons(raw.reasons),
    best_link: parseBestLink(raw.best_link),
    items: rawItems
      .slice(0, MAX_ITEMS_PER_CRITERION)
      .map(parseItem)
      .filter((i): i is EvidenceItem => i !== null),
    itemsTruncated: rawItems.length > MAX_ITEMS_PER_CRITERION,
  };
}

function parseTamper(raw: unknown): TamperFinding | null {
  if (!isObject(raw)) return null;
  const snippet = (value: unknown) => {
    const text = optStr(value);
    return text === null ? null : truncateText(text, MAX_SNIPPET_CHARS);
  };
  return {
    finding_id: str(raw.finding_id),
    rule_id: str(raw.rule_id),
    severity: str(raw.severity),
    path: truncateText(str(raw.path), MAX_TEXT_CHARS),
    reason: truncateText(str(raw.reason), MAX_TEXT_CHARS),
    check: str(raw.check),
    symbol: optStr(raw.symbol),
    test_id: optStr(raw.test_id),
    old_snippet: snippet(raw.old_snippet),
    new_snippet: snippet(raw.new_snippet),
  };
}

/** Compact, bounded text for an arbitrary JSON value (rule inputs, thresholds). */
export function compactValue(value: unknown, max = 240): string {
  if (typeof value === "string") return truncateText(value, max);
  if (typeof value === "number" || typeof value === "boolean" || value === null) return String(value);
  try {
    return truncateText(JSON.stringify(value) ?? "", max);
  } catch {
    return "";
  }
}

function pairs(raw: unknown): Array<{ key: string; text: string }> {
  if (!isObject(raw)) return [];
  return Object.keys(raw)
    .sort()
    .slice(0, MAX_LIST)
    .map((key) => ({ key: truncateText(key, 80), text: compactValue(raw[key]) }));
}

function parseRule(raw: unknown): RuleResult | null {
  if (!isObject(raw)) return null;
  const refs = isObject(raw.refs) ? raw.refs : {};
  return {
    id: str(raw.id),
    label: truncateText(str(raw.label), 200),
    fired: raw.fired === true,
    inputs: pairs(raw.inputs),
    refs: Object.keys(refs)
      .sort()
      .map((key) => ({ key, ids: strs(refs[key]) }))
      .filter((r) => r.ids.length > 0),
  };
}

function parseJustification(raw: unknown): Justification | null {
  if (!isObject(raw) || !Array.isArray(raw.rules)) return null;
  return {
    verdict: str(raw.verdict),
    decided_by: str(raw.decided_by),
    rules: raw.rules
      .slice(0, 50)
      .map(parseRule)
      .filter((r): r is RuleResult => r !== null),
    thresholds: pairs(raw.thresholds),
    versions: pairs(raw.versions),
    config_digest: str(raw.config_digest),
    inputs_digest: str(raw.inputs_digest),
    profile: str(raw.profile),
  };
}

function parseSummary(raw: unknown, criteria: Criterion[]): Summary {
  const s = isObject(raw) ? raw : {};
  const count = (state: SupportState) => criteria.filter((c) => c.state === state).length;
  const tamper: Record<string, number> = {};
  if (isObject(s.tamper)) {
    for (const key of Object.keys(s.tamper).slice(0, 10)) {
      const v = s.tamper[key];
      if (typeof v === "number" && Number.isFinite(v)) tamper[key] = v;
    }
  }
  return {
    criteria_total: Math.max(0, Math.trunc(num(s.criteria_total, criteria.length))),
    proven: Math.max(0, Math.trunc(num(s.proven, count("proven")))),
    weak: Math.max(0, Math.trunc(num(s.weak, count("weak")))),
    unevidenced: Math.max(0, Math.trunc(num(s.unevidenced, count("unevidenced")))),
    contradicted: Math.max(0, Math.trunc(num(s.contradicted, count("contradicted")))),
    excluded: Math.max(0, Math.trunc(num(s.excluded, count("excluded")))),
    uim: clamp01(num(s.uim)),
    intent_coverage: clamp01(num(s.intent_coverage)),
    tamper,
    evidence_basis: str(s.evidence_basis, "static_only"),
    author_hint_criteria: Math.max(0, Math.trunc(num(s.author_hint_criteria, 0))),

  };
}

function thresholdNumber(justification: unknown, key: string): number | null {
  if (!isObject(justification) || !isObject(justification.thresholds)) return null;
  return optNum(justification.thresholds[key]);
}

export type ParseResult = { ok: true; value: VerdictV2 } | { ok: false; reason: string };

/** Parse the `data` of GET /analyses/{id}/verdict-v2. Never throws. */
export function parseVerdictV2(raw: unknown): ParseResult {
  if (!isObject(raw)) return { ok: false, reason: "The verdict response was not an object." };
  if (raw.verdict_version !== undefined && raw.verdict_version !== 2) {
    return { ok: false, reason: `Unsupported verdict version ${compactValue(raw.verdict_version, 20)}.` };
  }
  if (!Array.isArray(raw.criteria)) {
    return { ok: false, reason: "The verdict response has no criteria list." };
  }
  const criteria = raw.criteria
    .slice(0, MAX_CRITERIA)
    .map(parseCriterion)
    .filter((c): c is Criterion => c !== null);
  const error = isObject(raw.error)
    ? { code: str(raw.error.code), fallback: optStr(raw.error.fallback) }
    : null;
  return {
    ok: true,
    value: {
      algo_version: str(raw.algo_version),
      profile: str(raw.profile),
      mode: str(raw.mode),
      status: str(raw.status, "ok"),
      analysis_id: str(raw.analysis_id),
      head_sha: str(raw.head_sha),
      revision: Math.max(1, Math.trunc(num(raw.revision, 1))),
      computed_at: optStr(raw.computed_at),
      verdict: optStr(raw.verdict),
      pending: raw.pending === true,
      reasons: reasons(raw.reasons),
      summary: parseSummary(raw.summary, criteria),
      criteria,
      criteriaTruncated: raw.criteria.length > MAX_CRITERIA,
      tamper_findings: arr(raw.tamper_findings)
        .slice(0, MAX_TAMPER_FINDINGS)
        .map(parseTamper)
        .filter((t): t is TamperFinding => t !== null),
      unlinked_symbols: strs(raw.unlinked_symbols).map((s) => truncateText(s, 300)),
      next_actions: arr(raw.next_actions)
        .slice(0, MAX_LIST)
        .filter(isObject)
        .map((a) => ({
          code: str(a.code),
          text: truncateText(str(a.text), MAX_TEXT_CHARS),
          criterion_id: optStr(a.criterion_id),
        })),
      justification: parseJustification(raw.justification),
      v1: isObject(raw.v1)
        ? {
            verification_status: str(raw.v1.verification_status, "unknown"),
            confidence_score: optNum(raw.v1.confidence_score),
            score_kind: str(raw.v1.score_kind),
            risk_level: optStr(raw.v1.risk_level),
          }
        : null,
      error,
      tauSupport: thresholdNumber(raw.justification, "tau_support") ?? DEFAULT_TAU_SUPPORT,
      uimMax: thresholdNumber(raw.justification, "uim_max"),
      minIntentCoverage: thresholdNumber(raw.justification, "min_intent_coverage"),
    },
  };
}

// ---------------------------------------------------------------------------
// presentation
// ---------------------------------------------------------------------------

export type StateMeta = { label: string; tone: Tone; icon: IconName; description: string };

const STATE_META: Record<SupportState | "unknown", StateMeta> = {
  proven: {
    label: "Supported",
    tone: "good",
    icon: "check",
    description:
      "Static assertion strength above the threshold. Not a proof of correctness: no mutation testing, uncalibrated thresholds.",
  },
  weak: {
    label: "Weak",
    tone: "warn",
    icon: "alert",
    description: "Some evidence, but below the support threshold or without a strong assertion.",
  },
  unevidenced: {
    label: "Unsupported",
    tone: "warn",
    icon: "help",
    description: "No usable evidence for this criterion.",
  },
  contradicted: {
    label: "Contradicted",
    tone: "bad",
    icon: "x",
    description: "A linked test fails.",
  },
  excluded: {
    label: "Excluded",
    tone: "neutral",
    icon: "minus",
    description: "Not counted (not testable or rejected).",
  },
  unknown: {
    label: "Unknown state",
    tone: "neutral",
    icon: "help",
    description: "This state is not known to this dashboard version.",
  },
};

export function stateMeta(state: string): StateMeta {
  return STATE_META[normalizeState(state)];
}

const FLAG_LABELS: Record<string, string> = {
  tampered: "Tampered tests",
  flaky_evidence: "Flaky evidence",
  stale_evidence: "Stale evidence ignored",
  low_link_confidence: "Low link confidence",
  unconfirmed: "Criterion not confirmed",
  pending_results: "Awaiting CI results",
  static_only: "Static evidence only",
  no_strong_assertion: "No strong assertion",
  needs_typed_evidence: "Needs non-functional evidence",
  no_linked_test: "No test linked",
  author_supplied_hint: "Relies on author-supplied test hint",
};

export function provenanceLabel(provenance: string): string {
  return PROVENANCE_LABELS[provenance] ?? truncateText(provenance.replace(/_/g, " "), 40);
}

/** Criteria whose counted tests rely on an unconfirmed author-supplied hint. */
export function authorHintCount(v: Pick<VerdictV2, "criteria" | "summary">): number {
  const flagged = v.criteria.filter((c) => c.flags.includes("author_supplied_hint")).length;
  return Math.max(flagged, v.summary.author_hint_criteria);
}

export function flagLabel(flag: string): string {
  return FLAG_LABELS[flag] ?? truncateText(flag.replace(/_/g, " "), 60);
}

const SEVERITY_TONE: Record<string, Tone> = {
  critical: "bad",
  high: "bad",
  medium: "warn",
  low: "info",
  info: "neutral",
};
export const severityTone = (severity: string): Tone => SEVERITY_TONE[severity] ?? "neutral";

export type VerdictMeta = { label: string; tone: Tone; icon: IconName };

export function verdictMeta(
  verdict: string | null,
  pending: boolean,
  status: string,
): VerdictMeta {
  if (status !== "ok") return { label: "Verdict v2 unavailable", tone: "neutral", icon: "ban" };
  if (pending) return { label: "Awaiting CI test results", tone: "info", icon: "clock" };
  switch (verdict) {
    case "verified":
      return { label: "Supported by static evidence (alpha)", tone: "info", icon: "check" };
    case "failed":
      return { label: "Failed", tone: "bad", icon: "x" };
    case "needs_review":
      return { label: "Needs review", tone: "warn", icon: "shield" };
    case "insufficient_evidence":
      return { label: "Not verified: insufficient evidence", tone: "warn", icon: "alert" };
    default:
      return { label: "No verdict", tone: "neutral", icon: "help" };
  }
}

export type OutcomeMeta = { label: string; tone: Tone; icon: IconName };

export function outcomeMeta(outcome: string): OutcomeMeta {
  switch (outcome) {
    case "passed":
      return { label: "Passed", tone: "good", icon: "check" };
    case "failed":
    case "error":
      return { label: outcome === "error" ? "Error" : "Failed", tone: "bad", icon: "x" };
    case "skipped":
      return { label: "Skipped", tone: "neutral", icon: "minus" };
    case "flaky":
      return { label: "Flaky", tone: "warn", icon: "alert" };
    case "not_run":
      return { label: "Not run", tone: "neutral", icon: "clock" };
    default:
      return { label: truncateText(outcome || "unknown", 30), tone: "neutral", icon: "help" };
  }
}

/** "0.43" style text; the API already rounds, this only fixes the display. */
export function formatScore(value: number): string {
  return clamp01(value).toFixed(2);
}

export function formatPercent(value: number): string {
  return `${Math.round(clamp01(value) * 100)}%`;
}

export type SupportBar = {
  percent: number;
  tauPercent: number;
  text: string;
  meetsThreshold: boolean;
};

export function supportBar(criterion: Pick<Criterion, "S">, tau: number): SupportBar {
  const s = clamp01(criterion.S);
  const t = clamp01(tau);
  return {
    percent: Math.round(s * 100),
    tauPercent: Math.round(t * 100),
    text: `${formatScore(s)} of ${formatScore(t)} needed`,
    meetsThreshold: s >= t,
  };
}

export type Factor = { key: string; label: string; value: number; percent: number; note: string };

/** The quality factors of one evidence item, in the order of the formula. */
export function qualityFactors(item: EvidenceItem): Factor[] {
  const factor = (key: string, label: string, value: number, note: string): Factor => ({
    key,
    label,
    value: clamp01(value),
    percent: Math.round(clamp01(value) * 100),
    note,
  });
  return [
    factor(
      "a_static",
      "Assertion strength",
      item.a_static,
      `capped at ${formatScore(item.d_eff)} (no mutation data)`,
    ),
    factor("i", "Independence", item.i, "who wrote the test relative to the code"),
    factor("f", "Freshness", item.f, item.f > 0 ? "bound to the current head" : "not the current head: ignored"),
    factor("flaky_f", "Flakiness", item.flaky_f, item.flaky_f < 1 ? "discounted" : "no flakiness seen"),
    factor(
      "tamper",
      "Untampered",
      1 - item.tamper_penalty,
      item.tamper_penalty > 0 ? "tamper findings reduce this test" : "no tamper findings",
    ),
    factor("l", "Link strength", item.l, "criterion to symbol to test"),
  ];
}

export function itemStatusLabel(status: string): string {
  if (status === "counted") return "Counted";
  if (status.startsWith("gated:")) return `Not counted (${status.slice(6).replace(/_/g, " ")})`;
  return status ? truncateText(status.replace(/_/g, " "), 60) : "Unknown";
}

export type EvidenceSummary = {
  total: number;
  counted: number;
  failing: number;
  notCounted: number;
  text: string;
};

export function evidenceSummary(criterion: Pick<Criterion, "items">): EvidenceSummary {
  const total = criterion.items.length;
  const counted = criterion.items.filter((i) => i.status === "counted").length;
  const failing = criterion.items.filter((i) => i.outcome === "failed" || i.outcome === "error").length;
  const notCounted = total - counted;
  const noun = total === 1 ? "test" : "tests";
  const text =
    total === 0
      ? "No linked test"
      : `${total} ${noun}: ${counted} counted${failing ? `, ${failing} failing` : ""}`;
  return { total, counted, failing, notCounted, text };
}

export type Counts = Array<{ state: SupportState; count: number; meta: StateMeta }>;

export function summaryCounts(summary: Summary): Counts {
  return SUPPORT_STATES.map((state) => ({
    state,
    count: summary[state],
    meta: STATE_META[state],
  }));
}

export type MassBar = {
  uimPercent: number;
  uimMaxPercent: number | null;
  coveragePercent: number;
  minCoveragePercent: number | null;
  uimOverLimit: boolean;
};

export function massBar(
  summary: Pick<Summary, "uim" | "intent_coverage">,
  uimMax: number | null,
  minCoverage: number | null,
): MassBar {
  return {
    uimPercent: Math.round(clamp01(summary.uim) * 100),
    uimMaxPercent: uimMax === null ? null : Math.round(clamp01(uimMax) * 100),
    coveragePercent: Math.round(clamp01(summary.intent_coverage) * 100),
    minCoveragePercent: minCoverage === null ? null : Math.round(clamp01(minCoverage) * 100),
    uimOverLimit: uimMax !== null && summary.uim > uimMax,
  };
}

export type Tag = { key: string; label: string; tone: Tone };

/** Header tags: always the alpha and honesty labels, plus shadow / pending. */
export function headerTags(v: Pick<VerdictV2, "mode" | "pending" | "status" | "summary">): Tag[] {
  const tags: Tag[] = [
    { key: "alpha", label: "v2 alpha", tone: "info" },
    { key: "static", label: STATIC_ONLY_LABEL, tone: "neutral" },
    { key: "uncalibrated", label: UNCALIBRATED_LABEL, tone: "neutral" },
  ];
  if (v.mode === "shadow") tags.push({ key: "shadow", label: "Shadow: not shown on the PR", tone: "info" });
  if (v.pending) tags.push({ key: "pending", label: "Pending CI", tone: "info" });
  return tags;
}

export function headline(v: Pick<VerdictV2, "reasons" | "status" | "error" | "pending">): string {
  if (v.status !== "ok") {
    return v.error?.fallback === "v1"
      ? `v2 is unavailable (${v.error.code || v.status}); the v1 result is used instead.`
      : `v2 is unavailable (${v.error?.code || v.status}).`;
  }
  if (v.pending) return "Waiting for CI test results for this commit before judging the evidence.";
  return v.reasons[0]?.detail || "No deciding reason was recorded.";
}

export function shortSha(sha: string): string {
  return /^[0-9a-f]{7,40}$/.test(sha) ? sha.slice(0, 7) : "";
}

export function v1Label(v1: V1Block): string {
  const score = v1.confidence_score === null ? "no score" : `${Math.round(v1.confidence_score)}/100`;
  const kind =
    v1.score_kind === "calibrated" ? "calibrated" : "uncalibrated heuristic, not a probability";
  return `${v1.verification_status.replace(/_/g, " ")}, ${score} (${kind})`;
}

// ---------------------------------------------------------------------------
// justification tree
// ---------------------------------------------------------------------------

export type TreeRule = RuleResult & { decisive: boolean };
export type JustificationTree = {
  verdict: string;
  decidedBy: string;
  rules: TreeRule[];
  firedCount: number;
};

/** The rules in order, the deciding one marked; the first fired rule decides. */
export function justificationTree(j: Justification): JustificationTree {
  const rules = j.rules.map((r) => ({ ...r, decisive: r.id === j.decided_by }));
  return {
    verdict: j.verdict,
    decidedBy: j.decided_by,
    rules,
    firedCount: rules.filter((r) => r.fired).length,
  };
}

// ---------------------------------------------------------------------------
// errors
// ---------------------------------------------------------------------------

export type VerdictErrorInfo =
  | { kind: "disabled" }
  | { kind: "not_computed" }
  | { kind: "not_found"; message: string }
  | { kind: "other"; message: string };

/** Classify an error thrown by lib/api.ts radiusRequest (RadiusApiError-shaped). */
export function classifyVerdictError(error: unknown): VerdictErrorInfo {
  if (isObject(error) || error instanceof Error) {
    const e = error as { status?: unknown; code?: unknown; meta?: unknown; message?: unknown };
    if (e.status === 404) {
      const reason = isObject(e.meta) ? e.meta.reason : undefined;
      if (reason === "disabled") return { kind: "disabled" };
      if (reason === "not_computed") return { kind: "not_computed" };
      return { kind: "not_found", message: "This analysis was not found." };
    }
    const message = typeof e.message === "string" ? e.message : "The verdict could not be loaded.";
    return { kind: "other", message: truncateText(message, 300) };
  }
  return { kind: "other", message: "The verdict could not be loaded." };
}
