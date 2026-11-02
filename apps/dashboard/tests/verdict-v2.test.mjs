import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test, { afterEach } from "node:test";

process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111";

const m = await import("../lib/verdict-v2-model.ts");
const client = await import("../lib/verdict-v2.ts");

const example = JSON.parse(
  readFileSync(
    new URL("../../../docs/research/design/verdict_v2.example.08.json", import.meta.url),
    "utf8",
  ),
);
const parse = (raw = example) => {
  const result = m.parseVerdictV2(raw);
  assert.equal(result.ok, true, result.reason);
  return result.value;
};
const clone = () => structuredClone(example);

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const reply = (body, { status = 200, headers = {} } = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

// --- parsing -----------------------------------------------------------------

test("the design example (fixture 08) parses into the expected view model", () => {
  const v = parse();
  assert.equal(v.verdict, "insufficient_evidence");
  assert.equal(v.pending, false);
  assert.equal(v.criteria.length, 4);
  assert.deepEqual(
    v.criteria.map((c) => c.state),
    ["proven", "weak", "unevidenced", "unevidenced"],
  );
  assert.equal(v.summary.uim, 0.75);
  assert.equal(v.tauSupport, 0.5);
  assert.equal(v.uimMax, 0.2);
  assert.equal(v.justification.decided_by, "R2b");
  assert.equal(v.v1.score_kind, "heuristic_uncalibrated");
});

test("unknown fields and unknown states are tolerated", () => {
  const raw = clone();
  raw.brand_new_field = { x: 1 };
  raw.criteria[0].state = "partially_evidenced";
  raw.criteria[0].future = true;
  const v = parse(raw);
  assert.equal(v.criteria[0].state, "unknown");
  assert.equal(v.criteria[0].rawState, "partially_evidenced");
  assert.equal(m.stateMeta("partially_evidenced").label, "Unknown state");
});

test("malformed payloads are rejected without throwing", () => {
  for (const raw of [null, undefined, 3, "x", [], {}, { criteria: "no" }, { verdict_version: 3, criteria: [] }]) {
    const result = m.parseVerdictV2(raw);
    assert.equal(result.ok, false);
    assert.ok(result.reason.length > 0);
  }
});

test("wrong-typed fields fall back to neutral defaults", () => {
  const v = parse({
    verdict_version: 2,
    criteria: [{ criterion_id: 5, text: null, state: 7, S: "high", items: "none", flags: [1, "tampered"] }],
    summary: { uim: "x", proven: -4 },
    reasons: "no",
  });
  const c = v.criteria[0];
  assert.equal(c.text, "");
  assert.equal(c.S, 0);
  assert.deepEqual(c.flags, ["tampered"]);
  assert.deepEqual(c.items, []);
  assert.equal(v.summary.uim, 0);
  assert.equal(v.summary.proven, 0);
  assert.deepEqual(v.reasons, []);
});

test("numbers are clamped and lists and text are capped", () => {
  const raw = clone();
  raw.criteria[0].S = 7;
  raw.criteria[0].items[0].q = -3;
  raw.criteria[0].text = "x".repeat(m.MAX_TEXT_CHARS + 500);
  raw.criteria = Array.from({ length: m.MAX_CRITERIA + 20 }, () => structuredClone(raw.criteria[0]));
  const v = parse(raw);
  assert.equal(v.criteria.length, m.MAX_CRITERIA);
  assert.equal(v.criteriaTruncated, true);
  assert.equal(v.criteria[0].S, 1);
  assert.equal(v.criteria[0].items[0].q, 0);
  assert.equal(Array.from(v.criteria[0].text).length, m.MAX_TEXT_CHARS + 1);
  assert.ok(v.criteria[0].text.endsWith("…"));
});

test("truncateText never splits a surrogate pair", () => {
  const text = "a\u{1F600}".repeat(10);
  const cut = m.truncateText(text, 3);
  assert.equal(cut, "a\u{1F600}a…");
  assert.equal(m.truncateText("short", 10), "short");
});

test("hostile strings stay inert strings (rendering is React text only)", () => {
  const raw = clone();
  raw.criteria[0].text = '<img src=x onerror=alert(1)> [click](javascript:alert(1)) @everyone';
  raw.tamper_findings = [
    { finding_id: "tf_1", rule_id: "T001", severity: "high", path: "<script>", reason: "</div><b>x", new_snippet: "<svg onload=1>" },
  ];
  const v = parse(raw);
  assert.equal(v.criteria[0].text, raw.criteria[0].text);
  assert.equal(v.tamper_findings[0].new_snippet, "<svg onload=1>");
});

// --- presentation ---------------------------------------------------------------

test("every state has a label, an icon and a tone, and the labels are distinct", () => {
  const labels = new Set();
  for (const state of m.SUPPORT_STATES) {
    const meta = m.stateMeta(state);
    assert.ok(meta.label && meta.icon && meta.tone && meta.description, state);
    labels.add(meta.label);
  }
  assert.equal(labels.size, 5);
  assert.equal(m.stateMeta("unevidenced").label, "Unsupported");
  assert.equal(m.stateMeta("proven").label, "Supported");
  assert.equal(m.stateMeta("contradicted").tone, "bad");
});

test("verdict meta covers the four states, pending and unavailable", () => {
  assert.equal(m.verdictMeta("verified", false, "ok").label, "Supported by static evidence (alpha)");
  assert.notEqual(m.verdictMeta("verified", false, "ok").tone, "good");
  assert.equal(m.verdictMeta("failed", false, "ok").tone, "bad");
  assert.equal(m.verdictMeta("needs_review", false, "ok").label, "Needs review");
  assert.match(m.verdictMeta("insufficient_evidence", false, "ok").label, /insufficient evidence/);
  assert.equal(m.verdictMeta("verified", true, "ok").label, "Awaiting CI test results");
  assert.equal(m.verdictMeta(null, false, "error").label, "Verdict v2 unavailable");
  assert.equal(m.verdictMeta("odd", false, "ok").label, "No verdict");
});

test("header tags always carry the honesty labels", () => {
  const tags = m.headerTags(parse());
  const labels = tags.map((t) => t.label);
  assert.ok(labels.includes("v2 alpha"));
  assert.ok(labels.includes("Static assertion strength only (no mutation testing)"));
  assert.ok(labels.some((l) => /Uncalibrated/.test(l)));
  assert.ok(!labels.some((l) => /Shadow/.test(l)));
  const shadow = m.headerTags({ ...parse(), mode: "shadow", pending: true });
  assert.ok(shadow.some((t) => t.key === "shadow"));
  assert.ok(shadow.some((t) => t.key === "pending"));
});

test("headline explains unavailable and pending verdicts", () => {
  assert.match(m.headline(parse()), /unsupported intent mass 0.75/);
  assert.match(
    m.headline({ reasons: [], status: "error", error: { code: "TimeoutError", fallback: "v1" }, pending: false }),
    /v1 result is used/,
  );
  assert.match(m.headline({ reasons: [], status: "ok", error: null, pending: true }), /Waiting for CI/);
});

test("support bar marks the threshold", () => {
  const bar = m.supportBar({ S: 0.432 }, 0.5);
  assert.deepEqual(
    { percent: bar.percent, tau: bar.tauPercent, ok: bar.meetsThreshold },
    { percent: 43, tau: 50, ok: false },
  );
  assert.equal(bar.text, "0.43 of 0.50 needed");
  assert.equal(m.supportBar({ S: 0.604 }, 0.5).meetsThreshold, true);
  assert.equal(m.supportBar({ S: Number.NaN }, 2).percent, 0);
});

test("quality factors list the formula inputs in order with percentages", () => {
  const v = parse();
  const item = v.criteria[1].items[0];
  const factors = m.qualityFactors(item);
  assert.deepEqual(
    factors.map((f) => f.key),
    ["a_static", "i", "f", "flaky_f", "tamper", "l"],
  );
  assert.equal(factors[0].percent, 100);
  assert.match(factors[0].note, /capped at 0.60/);
  assert.equal(factors[1].percent, 80);
  assert.equal(factors.at(-1).percent, 90);
  const tampered = m.qualityFactors({ ...item, tamper_penalty: 1, f: 0 });
  assert.equal(tampered[4].percent, 0);
  assert.match(tampered[2].note, /ignored/);
});

test("evidence summary and item status wording", () => {
  const v = parse();
  assert.equal(m.evidenceSummary(v.criteria[3]).text, "No linked test");
  assert.equal(m.evidenceSummary(v.criteria[0]).text, "2 tests: 2 counted");
  const failing = { items: [{ status: "counted", outcome: "passed" }, { status: "gated:failed", outcome: "failed" }] };
  const s = m.evidenceSummary(failing);
  assert.equal(s.failing, 1);
  assert.equal(s.notCounted, 1);
  assert.equal(m.itemStatusLabel("counted"), "Counted");
  assert.equal(m.itemStatusLabel("gated:no_criterion_test_edge"), "Not counted (no criterion test edge)");
});

test("summary counts follow the five states and mass bars use the thresholds", () => {
  const v = parse();
  const counts = m.summaryCounts(v.summary);
  assert.deepEqual(counts.map((c) => c.count), [1, 1, 2, 0, 0]);
  const bars = m.massBar(v.summary, v.uimMax, v.minIntentCoverage);
  assert.equal(bars.uimPercent, 75);
  assert.equal(bars.uimMaxPercent, 20);
  assert.equal(bars.uimOverLimit, true);
  assert.equal(bars.coveragePercent, 100);
  assert.equal(m.massBar({ uim: 0.1, intent_coverage: 0.2 }, null, null).uimOverLimit, false);
});

test("the justification tree keeps rule order and marks the deciding rule", () => {
  const v = parse();
  const tree = m.justificationTree(v.justification);
  assert.equal(tree.decidedBy, "R2b");
  assert.deepEqual(tree.rules.map((r) => r.id).slice(0, 3), ["R1a", "R1b", "R1c"]);
  assert.equal(tree.rules.filter((r) => r.decisive).length, 1);
  assert.equal(tree.rules.find((r) => r.decisive).id, "R2b");
  assert.equal(tree.firedCount, tree.rules.filter((r) => r.fired).length);
  const r2b = tree.rules.find((r) => r.id === "R2b");
  assert.ok(r2b.inputs.some((i) => i.key === "uim" && i.text === "0.75"));
  assert.ok(r2b.refs.some((r) => r.key === "criterion_ids"));
});

test("rule inputs are rendered as bounded plain text", () => {
  const raw = clone();
  raw.justification.rules[0].inputs = { huge: "y".repeat(5000), nested: { a: [1, 2] }, flag: true };
  const rule = parse(raw).justification.rules[0];
  const huge = rule.inputs.find((i) => i.key === "huge");
  assert.ok(Array.from(huge.text).length <= 241);
  assert.equal(rule.inputs.find((i) => i.key === "nested").text, '{"a":[1,2]}');
  assert.equal(rule.inputs.find((i) => i.key === "flag").text, "true");
});

test("v1 comparison is always labelled with its score kind", () => {
  const v = parse();
  assert.match(m.v1Label(v.v1), /uncalibrated heuristic, not a probability/);
  assert.match(m.v1Label({ ...v.v1, score_kind: "calibrated" }), /\(calibrated\)/);
  assert.match(m.v1Label({ ...v.v1, confidence_score: null }), /no score/);
});

test("error and empty payloads: unavailable verdicts render honestly", () => {
  const v = parse({
    verdict_version: 2,
    status: "error",
    mode: "on",
    verdict: null,
    pending: false,
    criteria: [],
    summary: {},
    error: { code: "TimeoutError", fallback: "v1" },
  });
  assert.equal(v.status, "error");
  assert.equal(m.verdictMeta(v.verdict, v.pending, v.status).icon, "ban");
  assert.deepEqual(v.criteria, []);
  assert.equal(v.justification, null);
  assert.equal(v.summary.criteria_total, 0);
});

test("short sha only accepts hex", () => {
  assert.equal(m.shortSha("4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"), "4f2a9d1");
  assert.equal(m.shortSha("<script>"), "");
});

// --- error classification ------------------------------------------------------

test("classifyVerdictError separates disabled, not computed, not found and other", () => {
  const api = (status, meta = {}, message = "m") => Object.assign(new Error(message), { status, meta });
  assert.deepEqual(m.classifyVerdictError(api(404, { reason: "disabled" })), { kind: "disabled" });
  assert.deepEqual(m.classifyVerdictError(api(404, { reason: "not_computed" })), { kind: "not_computed" });
  assert.equal(m.classifyVerdictError(api(404)).kind, "not_found");
  assert.equal(m.classifyVerdictError(api(500, {}, "boom")).kind, "other");
  assert.equal(m.classifyVerdictError(new Error("network down")).kind, "other");
  assert.equal(m.classifyVerdictError("weird").kind, "other");
  assert.equal(m.classifyVerdictError(null).kind, "other");
});

// --- client ----------------------------------------------------------------------

test("getVerdictV2 reads the proxied route and returns the parsed verdict and ETag", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/analyses/a%201/verdict-v2");
    assert.equal(init.cache, "no-store");
    assert.equal(new Headers(init.headers).get("X-Radius-API-Key"), null);
    return reply({ success: true, data: example, meta: {} }, { headers: { ETag: '"abc"' } });
  };
  const result = await client.getVerdictV2("a 1");
  assert.equal(result.etag, '"abc"');
  assert.equal(result.verdict.criteria.length, 4);
});

test("a 404 carries meta.reason through to the classifier", async () => {
  globalThis.fetch = async () =>
    reply(
      { success: false, data: null, error: { code: "NOT_FOUND", message: "n/a" }, meta: { reason: "disabled" } },
      { status: 404 },
    );
  await assert.rejects(client.getVerdictV2("a1"), (error) => {
    assert.deepEqual(m.classifyVerdictError(error), { kind: "disabled" });
    return true;
  });
  globalThis.fetch = async () =>
    reply(
      { success: false, data: null, error: { code: "NOT_FOUND", message: "n/a" }, meta: { reason: "not_computed" } },
      { status: 404 },
    );
  await assert.rejects(client.getVerdictV2("a1"), (error) => {
    assert.deepEqual(m.classifyVerdictError(error), { kind: "not_computed" });
    return true;
  });
});

test("a payload that is not a v2 verdict is an error, not a crash", async () => {
  globalThis.fetch = async () => reply({ success: true, data: { hello: "world" }, meta: {} });
  await assert.rejects(client.getVerdictV2("a1"), /no criteria list/);
});

// --- rendering guard ---------------------------------------------------------------

test("the panel source renders untrusted text as React text only", () => {
  const source = readFileSync(new URL("../components/verdict-v2-panel.tsx", import.meta.url), "utf8");
  const code = source.replace(/\/\/.*$/gm, "");
  for (const forbidden of ["dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "href=", "src="]) {
    assert.ok(!code.includes(forbidden), `panel must not use ${forbidden}`);
  }
  assert.ok(!/from\s+["'][^"']*(markdown|marked|remark|sanitize)[^"']*["']/i.test(code));
  // Honesty labels are part of the header model, not optional copy.
  assert.ok(source.includes("headerTags(verdict)"));
});

// --- honesty and provenance (alpha) ---------------------------------------------

test("the wording never says proven or verified and carries a legend", () => {
  assert.match(m.DISCLAIMER, /not a proof of correctness/);
  assert.match(m.DISCLAIMER, /uncalibrated/);
  assert.equal(
    m.LEGEND,
    "supported = static assertion strength above threshold; not a proof of correctness",
  );
  for (const state of m.SUPPORT_STATES) {
    assert.doesNotMatch(m.stateMeta(state).label, /proven|verified/i, state);
  }
  assert.doesNotMatch(m.verdictMeta("verified", false, "ok").label, /^Verified/);
  assert.notEqual(m.verdictMeta("verified", false, "ok").tone, "good");
});

test("provenance and hints are parsed, defaulted and labelled", () => {
  const raw = clone();
  raw.criteria[0].provenance = "author_head_spec";
  raw.criteria[0].hints = [
    { kind: "tests", value: "tests/test_a.py", provenance: "author_head_spec" },
    "junk",
  ];
  const v = parse(raw);
  assert.equal(v.criteria[0].provenance, "author_head_spec");
  assert.deepEqual(v.criteria[0].hints, [
    { kind: "tests", value: "tests/test_a.py", provenance: "author_head_spec" },
  ]);
  const old = clone();
  delete old.criteria[0].provenance;
  delete old.criteria[0].hints;
  assert.equal(parse(old).criteria[0].provenance, "author_pr_body");
  assert.deepEqual(parse(old).criteria[0].hints, []);
  assert.equal(m.provenanceLabel("base_spec"), "Base branch spec");
  assert.equal(m.provenanceLabel("something_new"), "something new");
});

test("author-supplied hint reliance is counted from flags or the summary", () => {
  const raw = clone();
  assert.equal(m.authorHintCount(parse(raw)), 0);
  raw.criteria[0].flags = ["author_supplied_hint"];
  assert.equal(m.authorHintCount(parse(raw)), 1);
  raw.summary.author_hint_criteria = 3;
  assert.equal(m.authorHintCount(parse(raw)), 3);
  assert.equal(m.flagLabel("author_supplied_hint"), "Relies on author-supplied test hint");
});
