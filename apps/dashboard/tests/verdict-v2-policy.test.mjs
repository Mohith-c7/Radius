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
const clone = () => structuredClone(example);
const parse = (raw) => {
  const r = m.parseVerdictV2(raw);
  assert.equal(r.ok, true, r.reason);
  return r.value;
};

const XSS = "<img src=x onerror=alert(1)> [x](javascript:alert(1)) @everyone";
const POLICY = {
  present: true,
  status: "ok",
  mode: "blocking",
  head_policy: "tighten_only",
  source: { origin: "base", ref: "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3" },
  provenance: [
    { key: "thresholds.tau_support", value: 0.6, origin: "base", line: 4 },
    { key: "tamper.rules.T002", value: { severity: "medium" }, origin: "base", line: 9 },
  ],
  ignored_head: [{ key: "thresholds.uim_max", value: 0.4, origin: "head", line: 3 }],
  tamper: {
    acknowledgements: [{ rule: "T005", action: "disable", from_severity: "high", reason: XSS, line: 12 }],
    refused: [{ rule: "T001", message: "T001 reported high; disable is ignored." }],
  },
  unmet: { required: [{ criterion_id: "c_1", state: "weak", min_state: "proven", paths: ["src/auth/**"], line: 6 }] },
  exclude_paths: ["docs/**"],
  errors: ["line 5: out of range"],
  warnings: ["line 7: Unknown key"],
};
const WAIVER = { id: "W-1", reason: XSS, owner: "alice", expires: "2026-12-01" };
const WAIVERS = {
  status: "ok",
  source: { ref: "abc" },
  applied: [{ id: "W-1", kind: "finding", target: "tf_1", owner: "alice", reason: XSS, expires: "2026-12-01" }],
  ignored: [
    { id: "W-2", code: "expired", message: "expired on 2026-10-01.", line: 9 },
    { id: "W-3", code: "lifetime_exceeds_max", message: "too long", line: 15 },
  ],
  evaluated_on: "2026-11-03",
  audit_digest: "sha256:abc",
};
const TAMPER = {
  finding_id: "tf_1", rule_id: "T002", severity: "high", path: "tests/a.py", reason: "skip added",
  waived: true, waiver: WAIVER,
};

test("a payload without policy or waivers parses to nulls and shows no section", () => {
  const v = parse(clone());
  assert.equal(v.policy, null);
  assert.equal(v.waivers, null);
  assert.equal(m.hasPolicySection(v), false);
  assert.equal(v.summary.tamper_waived, 0);
});

test("policy, applied settings with line refs and the mode are parsed", () => {
  const raw = clone();
  raw.policy = POLICY;
  const v = parse(raw);
  assert.equal(v.policy.mode, "blocking");
  assert.match(m.policyModeLabel(v.policy), /^Blocking/);
  assert.equal(m.settingLine(v.policy.settings[0]), "thresholds.tau_support = 0.6 (policy line 4, base)");
  assert.match(m.settingLine(v.policy.settings[1]), /tamper\.rules\.T002 = .*policy line 9/);
  assert.equal(v.policy.ignoredHead[0].origin, "head");
  assert.equal(v.policy.unmet[0].target, "c_1");
  assert.equal(v.policy.refused.length, 1);
  assert.match(v.policy.acknowledgements[0], /^T005: disable from high/);
  assert.equal(v.policy.sourceRef.length, 40);
  assert.equal(m.hasPolicySection(v), true);
});

test("an unreadable policy is labelled as not applied; advisory and no mode have wording", () => {
  const raw = clone();
  raw.policy = { present: true, status: "invalid", mode: null };
  assert.match(m.policyModeLabel(parse(raw).policy), /could not be applied \(invalid\)/);
  raw.policy = { present: true, status: "ok", mode: "advisory" };
  assert.match(m.policyModeLabel(parse(raw).policy), /^Advisory/);
  raw.policy = { present: true, status: "ok", mode: null };
  assert.match(m.policyModeLabel(parse(raw).policy), /No mode set/);
});

test("waived findings keep their waiver (owner, reason, expiry) and are listed", () => {
  const raw = clone();
  raw.tamper_findings = [TAMPER, { ...TAMPER, finding_id: "tf_2", waived: false, waiver: WAIVER }];
  raw.summary.tamper_waived = 1;
  raw.waivers = WAIVERS;
  const v = parse(raw);
  assert.equal(v.summary.tamper_waived, 1);
  const waived = m.waivedFindings(v);
  assert.equal(waived.length, 1);
  assert.equal(waived[0].waiver.owner, "alice");
  assert.equal(waived[0].waiver.expires, "2026-12-01");
  assert.equal(waived[0].waiver.reason, XSS, "untrusted text is kept verbatim, as text");
  assert.equal(v.tamper_findings[1].waiver, null, "a non-waived finding carries no waiver");
});

test("ignored waivers keep their codes", () => {
  const raw = clone();
  raw.waivers = WAIVERS;
  const v = parse(raw);
  assert.deepEqual(v.waivers.ignored.map((w) => w.code), ["expired", "lifetime_exceeds_max"]);
  assert.equal(m.waiverCodeLabel("lifetime_exceeds_max"), "lifetime exceeds max");
  assert.equal(v.waivers.evaluatedOn, "2026-11-03");
});

test("presentation wording wins over local wording, with local fallback", () => {
  const v = parse(clone());
  assert.equal(m.stateLabel(v, "proven"), "SUPPORTED");
  assert.equal(m.disclaimerText(v), example.presentation.disclaimer);
  assert.equal(m.legendText(v), example.presentation.legend);
  assert.equal(v.presentation.verdict_label, "Not verified - insufficient evidence");
  const raw = clone();
  delete raw.presentation;
  const old = parse(raw);
  assert.equal(old.presentation, null);
  assert.equal(m.stateLabel(old, "proven"), m.stateMeta("proven").label);
  assert.equal(m.disclaimerText(old), m.DISCLAIMER);
  assert.equal(m.legendText(old), m.LEGEND);
});

test("hostile policy and waiver payloads are tolerated and bounded", () => {
  const raw = clone();
  raw.policy = {
    mode: 5,
    provenance: ["x", null, { key: "k".repeat(5000), value: "v".repeat(5000), line: "7" }],
    tamper: "no",
    unmet: [],
    errors: Array.from({ length: 500 }, () => "e".repeat(5000)),
  };
  raw.waivers = { applied: "no", ignored: [1, { code: 7 }] };
  raw.tamper_findings = [{ ...TAMPER, waiver: "junk" }];
  const v = parse(raw);
  assert.equal(v.policy.mode, null);
  assert.equal(v.policy.settings.length, 1);
  assert.ok(v.policy.settings[0].key.length <= 81 && v.policy.settings[0].value.length <= 121);
  assert.equal(v.policy.settings[0].line, null);
  assert.equal(v.policy.errors.length, 50);
  assert.ok(v.policy.errors[0].length <= 301);
  assert.deepEqual(v.waivers.applied, []);
  assert.equal(v.waivers.ignored.length, 1);
  assert.equal(v.tamper_findings[0].waived, true);
  assert.equal(v.tamper_findings[0].waiver, null);
});

test("the panel renders the policy section as text only and behind the v2 panel", () => {
  const src = readFileSync(new URL("../components/verdict-v2-panel.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(src.replace(/\/\/.*$/gm, ""), /dangerouslySetInnerHTML|innerHTML/);
  assert.match(src, /function PolicySection/);
  assert.match(src, /WAIVED/);
  assert.match(src, /Ignored waivers/);
  assert.match(src, /hasPolicySection/);
  const host = readFileSync(new URL("../components/data-panels.tsx", import.meta.url), "utf8");
  assert.match(host, /VerdictV2Panel/);
});
