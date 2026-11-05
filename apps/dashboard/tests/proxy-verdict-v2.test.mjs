import assert from "node:assert/strict";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");

test("exactly one verdict v2 route is allowlisted, read-only", () => {
  assert.equal(proxy.checkRoute(["analyses", "a1", "verdict-v2"], "GET"), "ok");
  assert.equal(proxy.checkRoute(["analyses", "5b0b9c6e-0000-4000-8000-000000000008", "verdict-v2"], "GET"), "ok");
});

test("verdict v2 rejects every write method", () => {
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    assert.equal(proxy.checkRoute(["analyses", "a1", "verdict-v2"], method), "method", method);
  }
});

test("the undocumented alias, sub-paths and look-alikes stay rejected", () => {
  for (const segments of [
    ["analyses", "a1", "verdict"],
    ["analyses", "a1", "verdict-v2", "criteria"],
    ["analyses", "a1", "verdict-v2", "x"],
    ["analyses", "a1", "verdict-v2x"],
    ["analyses", "a1", "verdict_v2"],
    ["analyses", "a1", "Verdict-v2"],
    ["analyses", "a1", "verdict-v2", ""],
    ["analyses", "a1", "verdict-v2", ".."],
    ["analyses", "a1", "..", "verdict-v2"],
    ["analyses", "a1/b", "verdict-v2"],
    ["analyses", "a%2F1", "verdict-v2"],
    ["verdict-v2"],
  ]) {
    assert.equal(proxy.checkRoute(segments, "GET"), "not_found", segments.join("/"));
  }
});

test("adding the route did not widen any other path", () => {
  assert.equal(proxy.checkRoute(["analyses", "a1", "confidence"], "GET"), "ok");
  assert.equal(proxy.checkRoute(["analyses", "a1", "confidence"], "POST"), "method");
  assert.equal(proxy.checkRoute(["analyses", "a1", "evidence"], "GET"), "not_found");
  assert.equal(proxy.checkRoute(["organizations"], "GET"), "not_found");
});

test("the verdict read forwards no client intent-write headers and keeps the key server-side", () => {
  const cfg = { apiBaseUrl: "https://api.test", organizationId: "org-1", apiKey: "k-secret" };
  const incoming = new Headers({
    "If-Match": '"x"',
    "X-Radius-Actor": "someone",
    Cookie: "session=1",
    Authorization: "Bearer abc",
  });
  const out = proxy.buildUpstreamHeaders(cfg, incoming, {
    segments: ["analyses", "a1", "verdict-v2"],
    method: "GET",
  });
  assert.equal(out.get("If-Match"), null);
  assert.equal(out.get("X-Radius-Actor"), null);
  assert.equal(out.get("Cookie"), null);
  assert.equal(out.get("Authorization"), null);
  assert.equal(out.get("X-Radius-API-Key"), "k-secret");
  assert.equal(
    proxy.buildUpstreamUrl(cfg, ["analyses", "a1", "verdict-v2"], ""),
    "https://api.test/api/v1/analyses/a1/verdict-v2",
  );
});
