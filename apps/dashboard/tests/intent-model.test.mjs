import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../lib/intent-model.ts");

const crit = (over = {}) => ({
  id: "crit_1",
  text: "Users can log in",
  origin: { method: "deterministic", extractor_version: "v1", source_kind: "pr_body", source_id: "pr-body", source_hash: "h", retrieved_at: "2026-11-02T10:00:00Z" },
  span: { source_id: "pr-body", start: 0, end: 4 },
  weight: 1,
  testability: "unrated",
  testability_rationale: null,
  state: "proposed",
  hints: { paths: [], tests: [], label: null },
  ...over,
});

// --- state machine mirrors radius_intent.domain.criterion.ALLOWED_TRANSITIONS
test("legal actions per state mirror the server state machine", () => {
  assert.deepEqual(m.legalActions("proposed"), ["confirm", "edit", "reject"]);
  assert.deepEqual(m.legalActions("edited"), ["confirm", "edit", "reject"]);
  assert.deepEqual(m.legalActions("confirmed"), ["edit", "reject"]);
  assert.deepEqual(m.legalActions("needs_reconfirmation"), ["confirm", "edit", "reject"]);
  assert.deepEqual(m.legalActions("orphaned"), ["reject"]);
  assert.deepEqual(m.legalActions("rejected"), ["reopen"]);
  assert.deepEqual(m.legalActions("nonsense"), []);
});

test("illegal transitions are refused", () => {
  assert.equal(m.canApply("rejected", "confirm"), false);
  assert.equal(m.canApply("confirmed", "confirm"), false);
  assert.equal(m.canApply("orphaned", "confirm"), false);
  assert.equal(m.canApply("confirmed", "reopen"), false);
  assert.equal(m.canApply("__proto__", "confirm"), false);
  assert.equal(m.canApply("toString", "confirm"), false);
});

test("optimistic update follows the state machine and touches only one criterion", () => {
  const list = [crit(), crit({ id: "crit_2", state: "rejected" })];
  const confirmed = m.applyOptimistic(list, "crit_1", "confirm");
  assert.equal(confirmed[0].state, "confirmed");
  assert.equal(confirmed[1].state, "rejected");
  assert.equal(list[0].state, "proposed", "input is not mutated");
  const edited = m.applyOptimistic(list, "crit_1", "edit", "New wording");
  assert.equal(edited[0].state, "edited");
  assert.equal(edited[0].text, "New wording");
  // illegal action leaves the list unchanged
  assert.equal(m.applyOptimistic(list, "crit_2", "confirm")[1].state, "rejected");
  assert.equal(m.applyOptimistic(list, "crit_2", "reopen")[1].state, "proposed");
});

test("counting, filtering and attention", () => {
  const list = [crit(), crit({ id: "b", state: "orphaned" }), crit({ id: "c", state: "needs_reconfirmation" })];
  assert.deepEqual(m.countByState(list), { proposed: 1, orphaned: 1, needs_reconfirmation: 1 });
  assert.equal(m.filterByState(list, "all").length, 3);
  assert.equal(m.filterByState(list, "orphaned").length, 1);
  assert.equal(m.needsAttention(list), 2);
});

// --- presentation
test("testability metadata: vague and external carry guidance", () => {
  assert.match(m.testabilityMeta("subjective_or_vague").guidance, /measurable threshold/);
  assert.match(m.testabilityMeta("untestable_external").guidance, /measurable threshold/);
  assert.equal(m.testabilityMeta("behavioral_testable").guidance, null);
  assert.equal(m.testabilityMeta("unrated").label, "Unrated");
  assert.equal(m.testabilityMeta("something_new").label, "Unrated");
  for (const k of ["behavioral_testable", "structural_checkable", "non_functional_measurable", "subjective_or_vague", "untestable_external", "unrated"]) {
    assert.ok(m.testabilityMeta(k).tooltip.length > 0);
  }
});

test("state metadata calls out reconfirmation and orphaned", () => {
  assert.equal(m.stateMeta("needs_reconfirmation").tone, "warn");
  assert.equal(m.stateMeta("orphaned").tone, "bad");
  assert.equal(m.stateMeta("weird").label, "Unknown state");
});

test("method label marks LLM proposals for verification", () => {
  assert.deepEqual(m.methodLabel("llm"), { label: "LLM-proposed", verify: true });
  assert.equal(m.methodLabel("human").verify, false);
  assert.equal(m.methodLabel("deterministic").verify, false);
  assert.equal(m.methodLabel("???").verify, true);
});

test("source flags explain truncation and suspicious content", () => {
  const base = { kind: "pr_body", source_id: "x", raw_text_hash: "h", length: 1, truncated: false, suspicious_content_removed: false, fetched_at: null };
  assert.deepEqual(m.describeSourceFlags(base), []);
  assert.equal(m.describeSourceFlags({ ...base, truncated: true }).length, 1);
  assert.equal(m.describeSourceFlags({ ...base, truncated: true, suspicious_content_removed: true }).length, 2);
});

test("formatting helpers", () => {
  assert.equal(m.formatPercent(1), "100%");
  assert.equal(m.formatPercent(0.55), "55%");
  assert.equal(m.formatPercent(NaN), "-");
  assert.equal(m.formatByteCount("abc"), 3);
  assert.equal(m.formatByteCount("é"), 2);
  assert.equal(m.formatByteCount("€"), 3);
  assert.equal(m.formatByteCount("\u{1F600}"), 4);
  assert.equal(m.formatKiB(2048), "2.0 KiB");
  assert.equal(m.countCodePoints("a\u{1F600}b"), 3);
  assert.equal(m.sourceKindLabel("spec_file"), ".radius/intent.yml");
  assert.equal(m.sourceKindLabel("zzz"), "Source");
});

// --- validation
test("criterion text validation: empty, cap, unchanged", () => {
  assert.equal(m.validateCriterionText("   ").ok, false);
  assert.deepEqual(m.validateCriterionText("  ok  "), { ok: true, text: "ok" });
  assert.equal(m.validateCriterionText("a".repeat(2000)).ok, true);
  assert.equal(m.validateCriterionText("a".repeat(2001)).ok, false);
  // 2000 emoji are 2000 characters (code points), not 4000
  assert.equal(m.validateCriterionText("\u{1F600}".repeat(2000)).ok, true);
  assert.equal(m.validateCriterionText("same", "same").ok, false);
});

test("source text validation uses the 64 KiB byte cap", () => {
  assert.equal(m.validateSourceText("").ok, false);
  assert.equal(m.validateSourceText("a".repeat(65536)).ok, true);
  assert.equal(m.validateSourceText("a".repeat(65537)).ok, false);
  assert.equal(m.validateSourceText("€".repeat(21846)).ok, false); // 65538 bytes
});

test("truncateText never splits a surrogate pair", () => {
  assert.deepEqual(m.truncateText("short", 10), { text: "short", truncated: false });
  const t = m.truncateText("\u{1F600}".repeat(10), 3);
  assert.equal(t.truncated, true);
  assert.equal(t.text, "\u{1F600}".repeat(3));
  assert.equal(m.truncateText("abc", 0).text, "");
});

// --- span highlighting
const flat = (r) => r.segments.map((s) => `${s.ids.join("+")}:${s.text}`);

test("highlight: simple span", () => {
  const r = m.highlightSegments("hello world", [{ id: "a", start: 6, end: 11 }]);
  assert.deepEqual(flat(r), [":hello ", "a:world"]);
  assert.equal(r.invalid, 0);
});

test("highlight: out-of-range, reversed, empty and non-integer spans are dropped, never throw", () => {
  const text = "abc";
  for (const span of [
    { id: "a", start: -1, end: 2 },
    { id: "a", start: 0, end: 4 },
    { id: "a", start: 2, end: 2 },
    { id: "a", start: 3, end: 1 },
    { id: "a", start: 0.5, end: 2 },
    { id: "a", start: NaN, end: 2 },
    { id: "a", start: 0, end: Infinity },
    { id: "a", start: "0", end: 2 },
  ]) {
    const r = m.highlightSegments(text, [span]);
    assert.equal(r.invalid, 1, JSON.stringify(span));
    assert.deepEqual(flat(r), [":abc"]);
  }
  assert.deepEqual(m.highlightSegments("", [{ id: "a", start: 0, end: 1 }]), { segments: [], invalid: 1 });
});

test("highlight: overlapping spans carry both ids", () => {
  const r = m.highlightSegments("abcdef", [
    { id: "a", start: 0, end: 4 },
    { id: "b", start: 2, end: 6 },
  ]);
  assert.deepEqual(flat(r), ["a:ab", "a+b:cd", "b:ef"]);
});

test("highlight: nested and adjacent spans", () => {
  const r = m.highlightSegments("abcdef", [
    { id: "a", start: 0, end: 6 },
    { id: "b", start: 1, end: 3 },
    { id: "c", start: 3, end: 5 },
  ]);
  assert.deepEqual(flat(r), ["a:a", "a+b:bc", "a+c:de", "a:f"]);
  assert.equal(r.segments.map((s) => s.text).join(""), "abcdef");
});

test("highlight: offsets are code points (emoji count once)", () => {
  const text = "\u{1F600}ok \u{1F680} go";
  const r = m.highlightSegments(text, [{ id: "a", start: 3, end: 5 }]); // " <rocket>"
  assert.deepEqual(flat(r), [":\u{1F600}ok", "a: \u{1F680}", ": go"]);
  assert.equal(r.segments.map((s) => s.text).join(""), text);
});

test("highlight: combining marks, RTL and ZWJ text round-trips", () => {
  for (const text of ["éa", "שלום abc", "مرحبا", "\u{1F468}‍\u{1F469}x"]) {
    const n = m.countCodePoints(text);
    const r = m.highlightSegments(text, [{ id: "a", start: 1, end: n }]);
    assert.equal(r.invalid, 0);
    assert.equal(r.segments.map((s) => s.text).join(""), text);
  }
});

test("highlight: XSS payload stays inert text and is never altered", () => {
  const payload = '<img src=x onerror=alert(1)><script>alert(2)</script>[x](javascript:alert(3))';
  const r = m.highlightSegments(payload, [{ id: "a", start: 0, end: 10 }]);
  assert.equal(r.segments.map((s) => s.text).join(""), payload);
  // segments are plain strings; nothing in the model builds markup
  for (const s of r.segments) assert.equal(typeof s.text, "string");
});

// --- errors
function apiError(code, message, status = 409) {
  const e = new Error(message);
  e.name = "RadiusApiError";
  e.status = status;
  e.code = code;
  return e;
}

test("error classification", () => {
  assert.equal(m.classifyIntentError(apiError("INTENT_NOT_FOUND", "none", 404)).kind, "not_found");
  assert.equal(m.classifyIntentError(apiError("INTENT_STALE", "etag")).kind, "stale");
  assert.equal(m.classifyIntentError(apiError("ILLEGAL_STATE_TRANSITION", "x")).kind, "illegal_transition");
  const other = m.classifyIntentError(apiError("INTENT_NO_SOURCES", "Add a source first."));
  assert.deepEqual(other, { kind: "other", message: "Add a source first.", code: "INTENT_NO_SOURCES" });
  assert.equal(m.classifyIntentError(new Error("boom")).kind, "other");
  assert.equal(m.classifyIntentError("str").kind, "other");
});

test("spec errors keep their line numbers", () => {
  const msg = "Invalid .radius/intent.yml: line 4: weight must be a number in (0, 1] [spec_invalid_weight]; line 9: unknown key 'foo' [spec_unknown_key]";
  const info = m.classifyIntentError(apiError("INTENT_SPEC_INVALID", msg, 422));
  assert.equal(info.kind, "spec_invalid");
  assert.deepEqual(info.lines, [
    "line 4: weight must be a number in (0, 1] [spec_invalid_weight]",
    "line 9: unknown key 'foo' [spec_unknown_key]",
  ]);
  const multi = m.parseSpecErrorLines("Invalid:\nline 2: bad\nline 3: worse");
  assert.deepEqual(multi, ["line 2: bad", "line 3: worse"]);
  assert.deepEqual(m.parseSpecErrorLines("no lines here"), []);
});

test("actor label comes from the session user and is header-safe", () => {
  assert.equal(m.actorLabel(null), null);
  assert.equal(m.actorLabel({}), null);
  assert.equal(m.actorLabel({ id: "abc-123" }), "user:abc-123");
  assert.equal(m.actorLabel({ id: "bad id\r\nX-Evil: 1" }), null);
  assert.equal(m.actorLabel({ id: "x".repeat(200) }), null);
});

// --- B-11: the verbatim source quote next to an LLM-proposed criterion
const llmOrigin = { method: "llm", extractor_version: "v1", source_kind: "pr_body", source_id: "pr-body", source_hash: "h", retrieved_at: "2026-11-02T10:00:00Z" };

test("source quote is shown only for LLM-proposed criteria and only as plain text", () => {
  const html = '<img src=x onerror="alert(1)"> must log in';
  const view = m.sourceQuoteView(crit({ origin: llmOrigin, source_quote: html }));
  assert.deepEqual(view, { quote: html, truncated: false }); // returned verbatim; React renders it as text
  assert.equal(m.sourceQuoteView(crit({ source_quote: html })), null); // deterministic origin
  assert.equal(m.sourceQuoteView(crit({ origin: llmOrigin, source_quote: null })), null);
  assert.equal(m.sourceQuoteView(crit({ origin: llmOrigin, source_quote: "   " })), null);
  assert.equal(m.sourceQuoteView(crit({ origin: llmOrigin })), null); // older API without the field
});

test("a long quote is cut client side and the server truncation flag is kept", () => {
  const long = "x".repeat(m.MAX_SOURCE_QUOTE_CHARS + 50);
  const cut = m.sourceQuoteView(crit({ origin: llmOrigin, source_quote: long }));
  assert.equal(Array.from(cut.quote).length, m.MAX_SOURCE_QUOTE_CHARS);
  assert.equal(cut.truncated, true);
  const server = m.sourceQuoteView(crit({ origin: llmOrigin, source_quote: "short quote here", source_quote_truncated: true }));
  assert.equal(server.truncated, true);
});
