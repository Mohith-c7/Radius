import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../lib/api-keys-model.ts");

const NOW = Date.parse("2026-11-20T12:00:00Z");
const key = (over = {}) => ({
  id: "k1",
  name: "ci",
  prefix: "rdk_abcd",
  scopes: ["ci-upload"],
  created_by: "admin",
  created_at: "2026-11-01T00:00:00Z",
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  rotated_from_id: null,
  ...over,
});

test("keyState: revoked beats expiry; past expiry is expired, future is expiring", () => {
  assert.equal(m.keyState(key(), NOW), "active");
  assert.equal(m.keyState(key({ expires_at: "2026-11-21T00:00:00Z" }), NOW), "expiring");
  assert.equal(m.keyState(key({ expires_at: "2026-11-19T00:00:00Z" }), NOW), "expired");
  assert.equal(m.keyState(key({ revoked_at: "2026-11-02T00:00:00Z", expires_at: "2027-01-01T00:00:00Z" }), NOW), "revoked");
  assert.equal(m.canManage(key({ expires_at: "2026-11-21T00:00:00Z" }), NOW), true);
  assert.equal(m.canManage(key({ revoked_at: "2026-11-02T00:00:00Z" }), NOW), false);
});

test("sortKeys lists usable keys first, newest first", () => {
  const keys = [
    key({ id: "old", created_at: "2026-10-01T00:00:00Z" }),
    key({ id: "revoked", created_at: "2026-11-10T00:00:00Z", revoked_at: "2026-11-11T00:00:00Z" }),
    key({ id: "new", created_at: "2026-11-05T00:00:00Z" }),
  ];
  assert.deepEqual(m.sortKeys(keys, NOW).map((k) => k.id), ["new", "old", "revoked"]);
});

test("create form defaults to ci-upload and validates name and scopes", () => {
  assert.deepEqual(m.DEFAULT_KEY_SCOPES, ["ci-upload"]);
  assert.match(m.validateKeyForm("  ", ["ci-upload"]), /name/);
  assert.match(m.validateKeyForm("x".repeat(121), ["ci-upload"]), /120/);
  assert.match(m.validateKeyForm("ci", []), /scope/);
  assert.match(m.validateKeyForm("ci", ["root"]), /scope/);
  assert.equal(m.validateKeyForm("ci", ["ci-upload"]), null);
  assert.deepEqual(m.createKeyPayload("  ci  ", ["admin", "ci-upload", "bogus", "admin"]), {
    name: "ci",
    scopes: ["ci-upload", "admin"],
  });
});

test("audit helpers: newest first, details summarised without nested dumps", () => {
  const events = [
    { id: "a", api_key_id: "k1", action: "created", actor: "x", detail: {}, created_at: "2026-11-01T00:00:00Z" },
    { id: "b", api_key_id: "k1", action: "revoked", actor: "x", detail: {}, created_at: "2026-11-02T00:00:00Z" },
  ];
  assert.deepEqual(m.sortAudit(events).map((e) => e.id), ["b", "a"]);
  assert.equal(
    m.auditDetailText({ scopes: ["ci-upload"], name: "ci", nested: { a: 1 }, empty: null }),
    "scopes: ci-upload; name: ci; nested: ...",
  );
  assert.equal(m.auditDetailText(null), "");
});
