import assert from "node:assert/strict";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");

test("allowlist accepts known routes and methods", () => {
  assert.equal(proxy.checkRoute(["repositories"], "GET"), "ok");
  assert.equal(proxy.checkRoute(["repositories"], "POST"), "ok");
  assert.equal(proxy.checkRoute(["repositories", "abc-123"], "DELETE"), "ok");
  assert.equal(proxy.checkRoute(["repositories", "r1", "pull-requests", "42"], "GET"), "ok");
  assert.equal(proxy.checkRoute(["analyses", "a1", "tests", "results"], "POST"), "ok");
  assert.equal(proxy.checkRoute(["analyses", "a1", "graph"], "GET"), "ok");
});

test("allowlist rejects unknown paths, traversal, and bad methods", () => {
  for (const segs of [
    [],
    ["health"],
    ["auth", "login"],
    ["repositories", ".."],
    ["repositories", "a/b"],
    ["repositories", "a%2Fb"],
    ["repositories", "a\b"],
    ["repositories", ""],
    ["analyses", "a1", "admin"],
    ["analyses", "a1", "tests", "results", "extra"],
    ["http://evil.test"],
    ["repositories", "r1", "pull-requests", "x"],
  ]) {
    assert.equal(proxy.checkRoute(segs, "GET"), "not_found", JSON.stringify(segs));
  }
  assert.equal(proxy.checkRoute(["analyses", "a1"], "DELETE"), "method");
  assert.equal(proxy.checkRoute(["repositories"], "TRACE"), "method");
  assert.equal(proxy.checkRoute(["analyses", "a1", "rerun"], "GET"), "method");
});

test("upstream URL always uses the configured base", () => {
  const cfg = { apiBaseUrl: "https://api.test/", organizationId: "o", apiKey: "k" };
  assert.equal(
    proxy.buildUpstreamUrl(cfg, ["analyses", "a1"], "?status=x"),
    "https://api.test/api/v1/analyses/a1?status=x",
  );
});

test("upstream headers are rebuilt: key attached, browser headers dropped", () => {
  const cfg = { apiBaseUrl: "https://api.test", organizationId: "org-1", apiKey: "secret-key" };
  const incoming = new Headers({
    Cookie: "radius_session=abc",
    Authorization: "Bearer evil",
    Host: "evil.test",
    "X-Radius-API-Key": "client-supplied",
    "X-Radius-Organization-Id": "other-org",
    "X-Forwarded-For": "1.2.3.4",
    "Content-Type": "application/json; charset=utf-8",
    "Idempotency-Key": "12345678-aaaa-bbbb-cccc-1234567890ab",
  });
  const out = proxy.buildUpstreamHeaders(cfg, incoming);
  assert.equal(out.get("X-Radius-API-Key"), "secret-key");
  assert.equal(out.get("X-Radius-Organization-Id"), "org-1");
  assert.equal(out.get("Content-Type"), "application/json");
  assert.equal(out.get("Idempotency-Key"), "12345678-aaaa-bbbb-cccc-1234567890ab");
  for (const h of ["cookie", "authorization", "host", "x-forwarded-for"]) {
    assert.equal(out.get(h), null, h);
  }
});

test("insecure dev mode: no key configured means no key header", () => {
  const cfg = proxy.loadProxyConfig({ NEXT_PUBLIC_RADIUS_ORGANIZATION_ID: "org-1" });
  assert.equal(cfg.apiKey, "");
  const out = proxy.buildUpstreamHeaders(cfg, new Headers());
  assert.equal(out.has("X-Radius-API-Key"), false);
});

test("proxy config reads the key only from the server-only variable", () => {
  const cfg = proxy.loadProxyConfig({
    RADIUS_API_KEY: "srv",
    NEXT_PUBLIC_RADIUS_API_KEY: "must-be-ignored",
  });
  assert.equal(cfg.apiKey, "srv");
});

test("rejects bad idempotency keys and content types", () => {
  const cfg = { apiBaseUrl: "x", organizationId: "", apiKey: "" };
  const out = proxy.buildUpstreamHeaders(
    cfg,
    new Headers({ "Idempotency-Key": "bad key\u0001", "Content-Type": "text/html" }),
  );
  assert.equal(out.has("Idempotency-Key"), false);
  assert.equal(out.has("Content-Type"), false);
});
