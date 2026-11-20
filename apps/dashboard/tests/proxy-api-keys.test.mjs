import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");
const session = await import("../lib/session.ts");

const JWT = "aaaa1111.bbbb2222.cccc3333";
const cfg = { apiBaseUrl: "https://api.test", organizationId: "org-1", apiKey: "k" };
const dev = { id: "1", email: "dev@example.com", role: "developer", emailVerified: true };
const admin = { ...dev, role: "admin" };

const ROUTES = [
  [["api-keys"], "GET"],
  [["api-keys"], "POST"],
  [["api-keys", "audit"], "GET"],
  [["api-keys", "k1", "rotate"], "POST"],
  [["api-keys", "k1"], "DELETE"],
];

test("api-keys: exactly the allowlisted paths and methods", () => {
  for (const [segs, method] of ROUTES) {
    assert.equal(proxy.checkRoute(segs, method), "ok", `${method} ${segs.join("/")}`);
  }
  assert.equal(proxy.checkRoute(["api-keys"], "DELETE"), "method");
  assert.equal(proxy.checkRoute(["api-keys"], "PATCH"), "method");
  assert.equal(proxy.checkRoute(["api-keys", "audit"], "POST"), "method");
  assert.equal(proxy.checkRoute(["api-keys", "k1"], "GET"), "method");
  assert.equal(proxy.checkRoute(["api-keys", "k1"], "PATCH"), "method");
  assert.equal(proxy.checkRoute(["api-keys", "k1", "rotate"], "GET"), "method");
  for (const segs of [
    ["api-keys", "k1", "revoke"],
    ["api-keys", "k1", "rotate", "x"],
    ["api-keys", ".."],
    ["api-keys", "a%2Fb"],
  ]) {
    assert.equal(proxy.checkRoute(segs, "POST"), "not_found", JSON.stringify(segs));
  }
});

test("api-keys: only admins pass the role gate, for every method", () => {
  for (const [segs, method] of ROUTES) {
    assert.equal(session.roleAllows(dev, method, segs), false, `${method} ${segs.join("/")}`);
    assert.equal(session.roleAllows(admin, method, segs), true, `${method} ${segs.join("/")}`);
  }
  assert.equal(session.roleAllows({ ...dev, role: "" }, "GET", ["api-keys"]), false);
  // other routes keep the old rule
  assert.equal(session.roleAllows(dev, "GET", ["repositories"]), true);
  assert.equal(session.roleAllows(dev, "DELETE", ["repositories", "r1"]), false);
});

test("api-keys: the validated session is forwarded, never a client header or actor", () => {
  const incoming = new Headers({ "X-Radius-Session": "client.sent.token", "X-Radius-Actor": "forged" });
  for (const [segments, method] of ROUTES) {
    const out = proxy.buildUpstreamHeaders(cfg, incoming, { segments, method, actor: "dev@example.com", session: JWT });
    assert.equal(out.get("X-Radius-Session"), JWT);
    assert.equal(out.get("X-Radius-Actor"), null);
  }
  const none = proxy.buildUpstreamHeaders(cfg, incoming, { segments: ["api-keys"], method: "GET" });
  assert.equal(none.get("X-Radius-Session"), null);
  const bad = proxy.buildUpstreamHeaders(cfg, incoming, { segments: ["api-keys"], method: "GET", session: "bad\r\nx: y" });
  assert.equal(bad.get("X-Radius-Session"), null);
  // not forwarded on ordinary reads
  const repos = proxy.buildUpstreamHeaders(cfg, incoming, { segments: ["repositories"], method: "GET", session: JWT });
  assert.equal(repos.get("X-Radius-Session"), null);
});

test("route handler passes the path to the role gate", () => {
  const route = readFileSync(new URL("../app/api/radius/[...path]/route.ts", import.meta.url), "utf8");
  assert.match(route, /roleAllows\(session\.user, request\.method, path\)/);
});
