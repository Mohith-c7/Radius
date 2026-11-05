import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111";

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

function withMutation() {
  const raw = structuredClone(example);
  raw.evidence_basis = "static_and_mutation";
  raw.summary.evidence_basis = "static_and_mutation";
  raw.mutation = {
    status: "measured", reason: "", generated: 14, sampled: 10, decided: 10, killed: 8,
    skipped_for_budget: 0, ladder: ["sampled:10of14"],
  };
  const [c1, c2] = raw.criteria;
  c1.evidence_basis = "mutation_measured";
  c1.flags = ["mutation_measured"];
  c1.mutation = {
    basis: "mutation_measured", n_mutants: 10, killed: 8, d_union: 0.8, d_union_lcb: 0.49,
    tests_measured: 2, tests_total: 2, excluded: {}, d_reach: null,
    d_reach_reason: "no_reachability_data", reason: "",
    survivors: [
      { mutant_id: "m8", path: "src/<b>x</b>.py", line: 28, operator: "AOR" },
      { mutant_id: "m9", path: "src/validators.py", line: 29, operator: "ROR" },
    ],
  };
  c1.items[0].basis = "mutation";
  c1.items[0].d_eff = 0.49;
  c1.items[0].d_mut_lcb = 0.49;
  c1.items[0].mutation_n = 10;
  c1.items[0].mutation_killed = 8;
  c2.evidence_basis = "static_only";
  c2.mutation = {
    basis: "static_only", n_mutants: 0, killed: 0, d_union: null, d_union_lcb: null,
    tests_measured: 0, tests_total: 1, survivors: [], excluded: {}, d_reach: null,
    d_reach_reason: "no_reachability_data", reason: "",
  };
  return raw;
}

test("flag off: no mutation fields, static label, static disclaimer", () => {
  const v = parse(structuredClone(example));
  assert.equal(v.mutation, null);
  for (const c of v.criteria) {
    assert.equal(c.mutation, null);
    assert.equal(c.evidence_basis, "");
    assert.equal(m.criterionBasisText(c), "");
    assert.deepEqual(m.mutationGaps(c), []);
  }
  assert.equal(m.mutationRunNote(v), "");
  const tags = m.headerTags(v);
  assert.equal(tags.find((t) => t.key === "static").label, m.STATIC_ONLY_LABEL);
  assert.match(m.disclaimerText({ presentation: null, summary: v.summary }), /static evidence only/);
});

test("measured criterion: basis text, gaps list, factor note and header", () => {
  const v = parse(withMutation());
  const [c1, c2] = v.criteria;
  assert.equal(m.criterionBasisText(c1), "Evidence basis: mutation-measured (10 mutants)");
  assert.equal(m.criterionBasisText(c2), "Evidence basis: static assertion strength only");
  assert.deepEqual(m.mutationGaps(c1), [
    "src/<b>x</b>.py:28, operator AOR", // plain text; React renders it as a text node
    "src/validators.py:29, operator ROR",
  ]);
  assert.match(m.qualityFactors(c1.items[0])[0].note, /measured detection 0\.49 \(lower bound, 8 of 10 mutants killed\)/);
  assert.match(m.qualityFactors(c2.items[0])[0].note, /no mutation data/);
  assert.equal(m.headerTags(v).find((t) => t.key === "static").label, m.MUTATION_BASIS_LABEL);
  assert.match(m.disclaimerText({ presentation: null, summary: v.summary }), /sampled mutation testing/);
  assert.match(m.mutationRunNote(v), /10 decided mutants, sampled 10 of 14, 8 caught/);
  assert.match(m.mutationRunNote(v), /not a proof/);
  assert.equal(m.flagLabel("mutation_measured"), "Mutation-measured");
});

test("partial basis and unmeasured run are labelled honestly", () => {
  const raw = withMutation();
  raw.criteria[0].evidence_basis = "mutation_partial";
  raw.criteria[0].mutation.basis = "mutation_partial";
  assert.match(m.criterionBasisText(parse(raw).criteria[0]), /mutation-measured for some tests \(10 mutants\), static for the rest/);
  const off = structuredClone(example);
  off.mutation = { status: "unmeasured", reason: "sandbox_disabled", generated: 0, sampled: 0, decided: 0, killed: 0 };
  const note = m.mutationRunNote(parse(off));
  assert.match(note, /enabled but did not measure this change \(sandbox disabled\); static assertion strength applies/);
});

test("hostile mutation payloads are bounded and never throw", () => {
  const raw = withMutation();
  raw.criteria[0].mutation.survivors = Array.from({ length: 500 }, (_, i) => ({
    mutant_id: `m${i}`, path: "p".repeat(5000), line: "x", operator: "O".repeat(100),
  }));
  raw.criteria[1].mutation = "not an object";
  raw.mutation = ["bad"];
  const v = parse(raw);
  assert.equal(v.criteria[0].mutation.survivors.length, 50);
  assert.equal(v.criteria[0].mutation.survivorsTruncated, true);
  assert.ok(v.criteria[0].mutation.survivors[0].path.length < 5000);
  assert.equal(v.criteria[1].mutation, null);
  assert.equal(v.mutation, null);
});

test("link gaps (stage 2): honest wording, bounded, absent when there is none", () => {
  const raw = withMutation();
  raw.criteria[0].mutation.link_gaps = [
    { mutant_id: "m3", path: "src/validators.py", line: 20, operator: "ROR", tests: ["tests/<b>t</b>.py::t"] },
  ];
  raw.criteria[0].mutation.link_gap_tests = ["tests/<b>t</b>.py::t"];
  const v = parse(raw);
  const text = m.linkGapText(v.criteria[0]);
  assert.equal(
    text,
    "Link gaps: 1 mutant killed only by tests not linked to this criterion: tests/<b>t</b>.py::t.",
  );
  assert.match(m.LINK_GAP_ACTION, /tests:/);
  assert.equal(m.linkGapText(v.criteria[1]), "");
  // hostile input is bounded and never throws
  raw.criteria[0].mutation.link_gaps = Array.from({ length: 500 }, () => ({ tests: "x" }));
  raw.criteria[0].mutation.link_gap_tests = Array.from({ length: 500 }, () => "t".repeat(5000));
  const w = parse(raw);
  assert.ok(w.criteria[0].mutation.link_gaps.length <= 50);
  assert.ok(w.criteria[0].mutation.link_gap_tests.length <= 10);
  assert.ok(w.criteria[0].mutation.link_gap_tests[0].length < 5000);
  // flag off / stage 1 only: nothing
  assert.equal(m.linkGapText(parse(structuredClone(example)).criteria[0]), "");
});
