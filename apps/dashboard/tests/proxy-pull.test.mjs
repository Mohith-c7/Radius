import assert from "node:assert/strict";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");

test("pull-based GitHub routes are allowlisted with exactly their methods", () => {
  const check = (segs, m) => proxy.checkRoute(segs, m);
  assert.equal(check(["repositories", "connect-github"], "POST"), "ok");
  assert.equal(check(["repositories", "connect-github"], "GET"), "method");
  assert.equal(check(["repositories", "r1", "pull-requests", "7", "analyze"], "POST"), "ok");
  assert.equal(check(["repositories", "r1", "pull-requests", "7", "analyze"], "GET"), "method");
  assert.notEqual(check(["repositories", "r1", "pull-requests", "x", "analyze"], "POST"), "ok");
});
