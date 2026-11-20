import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const m = await import("../lib/verdict-v2-model.ts");

const example = JSON.parse(
  readFileSync(
    new URL("../../../docs/research/design/verdict_v2.example.08.json", import.meta.url),
    "utf8",
  ),
);
const parse = (raw) => {
  const result = m.parseVerdictV2(raw);
  assert.equal(result.ok, true, result.reason);
  return result.value;
};
const withSuggestions = (suggested) => ({ ...structuredClone(example), suggested_tests: suggested });
const snippet = "from pkg.mod import f\n\ndef test_f():\n    assert f(2) == 4\n";

// --- suggested tests (DEC-034) -------------------------------------------------

test("suggested tests are parsed with forced not-executed, not-evidence flags", () => {
  const cid = example.criteria[1].criterion_id;
  const v = parse(
    withSuggestions([
      { criterion_id: cid, test_code: snippet, a_static: 0.9, imports: { "pkg.mod": ["f"] }, model: "m1", provenance: "something_else", executed: true, evidence: true },
    ]),
  );
  assert.equal(v.suggested_tests.length, 1);
  const s = v.suggested_tests[0];
  assert.equal(s.criterion_id, cid);
  assert.equal(s.test_code, snippet);
  assert.equal(s.model, "m1");
  assert.equal(s.provenance, "llm_proposed");
  assert.equal(s.executed, false);
  assert.equal(s.evidence, false);
  assert.equal(s.codeTruncated, false);
  assert.equal(m.suggestedTestTarget(v, s), example.criteria[1].text);
  assert.equal(m.suggestedTestTarget(v, { criterion_id: "c_gone" }), "c_gone");
});

test("a payload without suggested tests yields an empty list", () => {
  assert.deepEqual(parse(structuredClone(example)).suggested_tests, []);
  for (const bad of [null, "x", 3, { a: 1 }]) {
    assert.deepEqual(parse(withSuggestions(bad)).suggested_tests, []);
  }
});

test("malformed suggestions are dropped without throwing", () => {
  const v = parse(
    withSuggestions([
      null,
      "code",
      { criterion_id: "c1" },
      { criterion_id: "c1", test_code: "   " },
      { criterion_id: 7, test_code: snippet },
      { criterion_id: "c1", test_code: 42 },
      { criterion_id: "c2", test_code: snippet, model: { x: 1 } },
    ]),
  );
  assert.equal(v.suggested_tests.length, 0, "only the first five entries are read and all are malformed");
  const ok = parse(withSuggestions([{ criterion_id: "c2", test_code: snippet, model: { x: 1 } }]));
  assert.equal(ok.suggested_tests.length, 1);
  assert.equal(ok.suggested_tests[0].model, "");
});

test("the list and each snippet are capped", () => {
  const many = Array.from({ length: 9 }, (_, i) => ({ criterion_id: `c${i}`, test_code: snippet }));
  const v = parse(withSuggestions(many));
  assert.equal(v.suggested_tests.length, m.MAX_SUGGESTED_TESTS);
  assert.equal(v.suggestedTestsTruncated, true);
  const huge = "\u{1F600}".repeat(m.MAX_SUGGESTED_CODE_CHARS + 10);
  const cut = parse(withSuggestions([{ criterion_id: "c1", test_code: huge }])).suggested_tests[0];
  assert.equal(Array.from(cut.test_code).length, m.MAX_SUGGESTED_CODE_CHARS);
  assert.equal(cut.codeTruncated, true);
});

test("hostile snippets stay inert strings", () => {
  const code = "</pre><script>alert(1)</script>\n```\n<img src=x onerror=alert(1)>";
  const v = parse(withSuggestions([{ criterion_id: "c1", test_code: code }]));
  assert.equal(v.suggested_tests[0].test_code, code);
});

test("the panel renders suggestions in a collapsed, labelled section as text", () => {
  const source = readFileSync(new URL("../components/verdict-v2-panel.tsx", import.meta.url), "utf8");
  assert.equal(m.SUGGESTED_TESTS_TITLE, "Suggested tests (not run, not evidence)");
  assert.match(m.SUGGESTED_TESTS_NOTE, /never executed: not evidence/);
  assert.ok(source.includes("<SuggestedTests verdict={verdict} />"));
  assert.ok(source.includes('<pre className="vv2-pre">{item.test_code}</pre>'));
  assert.ok(source.includes("Not executed") && source.includes("Not evidence"));
  // Collapsed by default: the details element of the section has no `open` attribute.
  assert.match(source, /<details className="vv2-details" data-testid="suggested-tests">/);
});

// --- headline label for pending and unavailable results ------------------------------

test("a pending (R2p) result never shows the stored insufficient-evidence label", () => {
  const raw = structuredClone(example);
  raw.pending = true;
  raw.verdict = "insufficient_evidence";
  raw.presentation = {
    verdict_label: "Not verified - insufficient evidence",
    summary_text: "Not verified - insufficient evidence: 1 of 4 stated criteria supported by static evidence.",
  };
  const v = parse(raw);
  assert.equal(m.verdictLabel(v), "Awaiting CI test results");
  assert.equal(m.presentationSummary(v), "");
  const done = parse({ ...raw, pending: false });
  assert.equal(m.verdictLabel(done), "Not verified - insufficient evidence");
  assert.match(m.presentationSummary(done), /1 of 4/);
  const unavailable = parse({ ...raw, pending: false, status: "error", verdict: null, presentation: { verdict_label: "Verdict unavailable", summary_text: "Verdict unavailable: 0 of 0" } });
  assert.equal(m.verdictLabel(unavailable), "Verdict v2 unavailable");
  assert.equal(m.presentationSummary(unavailable), "");
  const noPresentation = parse({ ...raw, pending: false, presentation: undefined });
  assert.match(m.verdictLabel(noPresentation), /insufficient evidence/);
});
