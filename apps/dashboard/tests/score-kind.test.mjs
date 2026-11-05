import assert from "node:assert/strict";
import test from "node:test";
import { scoreKindLabel, DEFAULT_SCORE_KIND } from "../lib/score-kind.ts";

test("heuristic_uncalibrated is labelled as an uncalibrated heuristic", () => {
  const label = scoreKindLabel("heuristic_uncalibrated");
  assert.equal(label.short, "Uncalibrated heuristic");
  assert.match(label.tooltip, /not a probability/);
});

test("missing or unknown score kinds fall back to the uncalibrated label", () => {
  assert.equal(DEFAULT_SCORE_KIND, "heuristic_uncalibrated");
  for (const kind of [undefined, null, "", "something_new"]) {
    assert.equal(scoreKindLabel(kind).short, "Uncalibrated heuristic");
  }
});

test("calibrated kind is not labelled as a heuristic", () => {
  assert.equal(scoreKindLabel("calibrated").short, "Calibrated score");
});
