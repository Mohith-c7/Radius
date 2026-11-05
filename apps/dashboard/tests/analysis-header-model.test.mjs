import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const m = await import("../lib/verdict-v2-model.ts");
const h = await import("../lib/analysis-header-model.ts");

const example = JSON.parse(
  readFileSync(
    new URL("../../../docs/research/design/verdict_v2.example.08.json", import.meta.url),
    "utf8",
  ),
);
function v2(verdict, { pending = false, mutate } = {}) {
  const raw = structuredClone(example);
  raw.verdict = verdict;
  raw.pending = pending;
  if (mutate) mutate(raw);
  const parsed = m.parseVerdictV2(raw);
  assert.equal(parsed.ok, true, parsed.reason);
  return parsed.value;
}

const V1_SENTENCE =
  "Verified: every executable change is covered by selected tests that ran and passed. Heuristic score 90.0/100 from CI test results (not a calibrated probability).";
const v1Verified = {
  verificationStatus: "verified",
  summary: V1_SENTENCE,
  score: 90,
  scoreKind: "heuristic_uncalibrated",
  recommendations: ["Proceed with standard review."],
  analysisCompleteness: 100,
};

const everything = (model) => JSON.stringify(model);

test("v2 absent: header is exactly the v1 header (wording and green Verified)", () => {
  const model = h.buildHeaderModel(v1Verified, null);
  assert.equal(model.source, "v1");
  assert.deepEqual(model.pill, { label: "Verified", tone: "good" });
  assert.equal(model.headline, V1_SENTENCE);
  assert.equal(model.showPrimaryRing, true);
  assert.equal(model.legacy, null);
  assert.equal(model.summaryLine, null);
  assert.equal(model.recommendation.lead, "Proceed with standard review.");
  assert.deepEqual(model.recommendation.actions, []);
  assert.equal(model.recommendation.warning, false);
});

test("v2 absent and no v1 report: today's placeholders", () => {
  const model = h.buildHeaderModel(null, null);
  assert.equal(model.pill, null);
  assert.equal(model.headline, "Analysis artifacts are being prepared");
  assert.equal(model.recommendation.lead, "Radius has not generated recommendations for this analysis yet.");
});

test("v1 not verified / failed keep their existing labels and tones", () => {
  assert.deepEqual(h.v1Presentation("failed"), { label: "Failed", tone: "bad" });
  assert.deepEqual(h.v1Presentation(undefined), {
    label: "Not verified (insufficient evidence)",
    tone: "warn",
  });
  assert.equal(h.toneColor("good"), "#64C89D");
  assert.equal(h.toneColor("bad"), "#F87171");
  assert.equal(h.toneColor("warn"), "#FBBF24");
});

test("v2 unavailable (status != ok) falls back to the v1 header", () => {
  const unavailable = v2("insufficient_evidence", { mutate: (r) => (r.status = "unavailable") });
  const model = h.buildHeaderModel(v1Verified, unavailable);
  assert.equal(model.source, "v1");
  assert.equal(model.pill.label, "Verified");
});

test("loading: never shows the v1 verdict, ring or recommendation", () => {
  const model = h.buildHeaderModel(v1Verified, "loading");
  assert.equal(model.source, "loading");
  assert.equal(model.pill.tone, "neutral");
  assert.equal(model.legacy, null);
  assert.equal(model.showPrimaryRing, false);
  assert.doesNotMatch(everything(model), /Verified:|Proceed with standard review|90/);
});

test("insufficient_evidence: honest alpha pill, summary line, v1 demoted (the reported bug)", () => {
  const verdict = v2("insufficient_evidence", {
    mutate: (r) => {
      r.summary.criteria_total = 2;
      r.summary.proven = 0;
      delete r.presentation;
    },
  });
  const model = h.buildHeaderModel(v1Verified, verdict);
  assert.equal(model.source, "v2");
  assert.equal(model.pill.label, "Not verified - insufficient evidence (alpha, static evidence only)");
  assert.equal(model.pill.tone, "warn");
  assert.equal(model.headline, model.pill.label);
  assert.match(model.summaryLine, /^0 of 2 stated criteria supported/);
  assert.equal(model.showPrimaryRing, false);
  // v1 only appears inside the labelled legacy block.
  assert.equal(model.legacy.title, "Legacy v1 result (file-level test selection, uncalibrated heuristic)");
  assert.equal(model.legacy.statusText, "v1 status: Verified");
  assert.equal(model.legacy.sentence, V1_SENTENCE);
  assert.equal(model.legacy.scoreText, "Heuristic score 90/100 (uncalibrated heuristic, not a probability)");
  const outside = everything({ ...model, legacy: null });
  assert.doesNotMatch(outside, /Verified:|Proceed with standard review|every executable change|90/);
  assert.match(model.recommendation.lead, /^Do not treat this PR as verified:/);
  assert.equal(model.recommendation.warning, true);
});

test("recommendation shows v2 next_actions (capped) instead of the v1 advice", () => {
  const verdict = v2("insufficient_evidence", {
    mutate: (r) => {
      r.next_actions = Array.from({ length: 7 }, (_, i) => ({
        code: "add_test",
        text: `Add a test for criterion ${i}`,
        criterion_id: null,
      }));
    },
  });
  const model = h.buildHeaderModel(v1Verified, verdict);
  assert.equal(model.recommendation.actions.length, h.MAX_SHOWN_ACTIONS);
  assert.equal(model.recommendation.actions[0], "Add a test for criterion 0");
  assert.equal(model.recommendation.hiddenActions, 2);
});

test("needs_review", () => {
  const model = h.buildHeaderModel(v1Verified, v2("needs_review"));
  assert.equal(model.pill.label, "Needs review (alpha, static evidence only)");
  assert.equal(model.pill.tone, "warn");
  assert.match(model.recommendation.lead, /^Do not treat this PR as verified:/);
  assert.equal(model.recommendation.warning, true);
});

test("failed", () => {
  const model = h.buildHeaderModel(v1Verified, v2("failed"));
  assert.equal(model.pill.label, "Failed (alpha, static evidence only)");
  assert.equal(model.pill.tone, "bad");
  assert.match(model.recommendation.lead, /^Do not treat this PR as verified:/);
});

test("pending CI: awaiting wording, not a verdict", () => {
  const model = h.buildHeaderModel(v1Verified, v2("verified", { pending: true }));
  assert.equal(model.pill.label, "Awaiting CI test results (alpha)");
  assert.match(model.recommendation.lead, /^Do not treat this PR as verified yet/);
  assert.equal(model.recommendation.warning, true);
});

test("verified: neutral supported wording, never 'safe to merge', not green", () => {
  const model = h.buildHeaderModel(
    v1Verified,
    v2("verified", { mutate: (r) => (r.summary.proven = r.summary.criteria_total) }),
  );
  assert.equal(model.pill.label, "Supported by static evidence (alpha)");
  assert.equal(model.recommendation.warning, false);
  assert.match(model.recommendation.lead, /^Static evidence supports the stated intent/);
  assert.match(model.recommendation.lead, /Still review the change\.$/);
  assert.doesNotMatch(everything(model), /safe to merge|Proceed with standard review/i);
  assert.ok(model.legacy);
});

test("mutation basis changes the qualifier", () => {
  const verdict = v2("insufficient_evidence", {
    mutate: (r) => (r.summary.evidence_basis = "static_and_mutation"),
  });
  assert.match(h.buildHeaderModel(null, verdict).pill.label, /static \+ sampled mutation evidence/);
});

test("unknown verdict value is treated as not verified", () => {
  const model = h.buildHeaderModel(v1Verified, v2("something_new"));
  assert.match(model.pill.label, /^Not verified - no verdict/);
  assert.equal(model.pill.tone, "warn");
  assert.equal(model.recommendation.warning, true);
});

test("no green style in v2 mode for any verdict, and a status word always accompanies the tone", () => {
  for (const verdict of ["verified", "failed", "needs_review", "insufficient_evidence", "bogus"]) {
    for (const pending of [false, true]) {
      const model = h.buildHeaderModel(v1Verified, v2(verdict, { pending }));
      assert.notEqual(model.pill.tone, "good", `${verdict}/${pending}`);
      assert.notEqual(h.toneColor(model.pill.tone), "#64C89D");
      assert.match(model.pill.label, /Supported|Not verified|Failed|Needs review|Awaiting/);
      assert.match(model.legacy.statusText, /^v1 status: /);
    }
  }
});

test("v2 without a v1 report has no legacy block", () => {
  const model = h.buildHeaderModel(null, v2("needs_review"));
  assert.equal(model.legacy, null);
  assert.equal(model.source, "v2");
});

test("untrusted text stays a plain string (the model produces no markup)", () => {
  const verdict = v2("insufficient_evidence", {
    mutate: (r) => {
      r.next_actions = [{ code: "x", text: "<img src=x onerror=alert(1)>", criterion_id: null }];
    },
  });
  const model = h.buildHeaderModel(null, verdict);
  assert.equal(typeof model.recommendation.actions[0], "string");
});
