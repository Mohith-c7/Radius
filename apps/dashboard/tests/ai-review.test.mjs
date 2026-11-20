import assert from "node:assert/strict";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");
const model = await import("../lib/ai-review-model.ts");

const OK = {
  analysis_id: "a1",
  status: "ok",
  reason_code: null,
  advisory: true,
  ai_generated: true,
  label: "AI-generated and advisory.",
  provider: "openai_compatible",
  model: "gemini-3.5-flash-lite",
  prompt_version: "ai-review-v1",
  generated_at: "2026-11-20T10:00:00Z",
  summary: "Adds retry handling to the uploader.",
  risks: [{ text: "Retries may duplicate uploads.", files: ["src/upload.py"] }],
  tests: [{ text: "tests/test_upload.py covers the retry path.", files: ["tests/test_upload.py"] }],
  missing_evidence: [],
  next_steps: [{ text: "Upload CI results.", files: [] }],
  notes: { dropped: [], injection_flags: ["instruction_override"], diff_truncated: true },
};

test("the ai-review route is allowlisted read-only and nothing else widened", () => {
  assert.equal(proxy.checkRoute(["analyses", "a1", "ai-review"], "GET"), "ok");
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    assert.equal(proxy.checkRoute(["analyses", "a1", "ai-review"], method), "method", method);
  }
  for (const segments of [
    ["analyses", "a1", "ai-review", "x"],
    ["analyses", "a1", "ai_review"],
    ["analyses", "a1", "ai-reviews"],
    ["analyses", "a1", "..", "ai-review"],
    ["ai-review"],
  ]) {
    assert.equal(proxy.checkRoute(segments, "GET"), "not_found", segments.join("/"));
  }
});

test("a valid review parses into sections with flags", () => {
  const parsed = model.parseAiReview(OK);
  assert.equal(parsed.ok, true);
  const v = parsed.value;
  assert.equal(v.status, "ok");
  assert.equal(v.summary, "Adds retry handling to the uploader.");
  assert.deepEqual(v.sections.risks, [{ text: "Retries may duplicate uploads.", files: ["src/upload.py"] }]);
  assert.equal(v.sections.missing_evidence.length, 0);
  assert.equal(v.injectionFlagged, true);
  assert.equal(v.diffTruncated, true);
});

test("a payload not marked advisory or AI-generated is rejected", () => {
  assert.equal(model.parseAiReview({ ...OK, advisory: false }).ok, false);
  assert.equal(model.parseAiReview({ ...OK, ai_generated: undefined }).ok, false);
  assert.equal(model.parseAiReview({ ...OK, status: "verified" }).ok, false);
  assert.equal(model.parseAiReview(null).ok, false);
  assert.equal(model.parseAiReview({ ...OK, summary: "" }).ok, false);
});

test("an unavailable review shows no sections and a plain reason", () => {
  const parsed = model.parseAiReview({ ...OK, status: "unavailable", reason_code: "provider_rate_limited" });
  assert.equal(parsed.ok, true);
  assert.equal(parsed.value.summary, null);
  assert.equal(parsed.value.sections.risks.length, 0);
  assert.match(model.unavailableText(parsed.value.reasonCode), /free-tier limit/);
  assert.match(model.unavailableText("output_summary_verdict_claim"), /safety checks/);
});

test("items are capped and malformed entries skipped", () => {
  const many = Array.from({ length: 9 }, (_, i) => ({ text: `risk ${i}`, files: ["a.py", 3, "b.py"] }));
  const parsed = model.parseAiReview({ ...OK, risks: [...many, "junk", { files: [] }] });
  assert.equal(parsed.value.sections.risks.length, 5);
  assert.deepEqual(parsed.value.sections.risks[0].files, ["a.py", "b.py"]);
});

test("404 means absent (render nothing); other errors are shown", () => {
  assert.deepEqual(model.classifyAiReviewError({ status: 404, meta: { reason: "not_generated" } }), { kind: "absent" });
  const other = model.classifyAiReviewError(new Error("boom"));
  assert.equal(other.kind, "other");
  assert.equal(other.message, "boom");
});
