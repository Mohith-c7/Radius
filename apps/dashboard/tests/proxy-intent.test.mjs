import assert from "node:assert/strict";
import test from "node:test";

const proxy = await import("../lib/proxy.ts");

const A = ["analyses", "a1", "intent"];

test("intent routes are allowlisted with exactly their methods", () => {
  const ok = (segs, m) => assert.equal(proxy.checkRoute(segs, m), "ok", `${m} ${segs.join("/")}`);
  ok(A, "GET");
  ok([...A, "snapshots"], "GET");
  ok([...A, "snapshots", "s-1"], "GET");
  ok([...A, "diff"], "GET");
  ok([...A, "sources"], "GET");
  ok([...A, "sources"], "POST");
  ok([...A, "rebuild"], "POST");
  ok([...A, "criteria"], "POST");
  ok([...A, "criteria", "crit_9b1c"], "PATCH");
  ok([...A, "criteria", "crit_9b1c", "history"], "GET");
});

test("intent routes reject other methods, other paths and traversal", () => {
  for (const [segs, m] of [
    [A, "POST"], [A, "PUT"], [A, "DELETE"], [A, "PATCH"],
    [[...A, "sources"], "DELETE"], [[...A, "sources"], "PATCH"],
    [[...A, "rebuild"], "GET"],
    [[...A, "criteria"], "GET"], [[...A, "criteria"], "DELETE"],
    [[...A, "criteria", "c1"], "GET"], [[...A, "criteria", "c1"], "DELETE"], [[...A, "criteria", "c1"], "POST"],
    [[...A, "criteria", "c1", "history"], "POST"],
    [[...A, "snapshots"], "POST"], [[...A, "snapshots", "s1"], "DELETE"],
    [[...A, "diff"], "POST"],
  ]) {
    assert.equal(proxy.checkRoute(segs, m), "method", `${m} ${segs.join("/")}`);
  }
  for (const segs of [
    [...A, "confirm"], [...A, "admin"], [...A, "criteria", "c1", "delete"],
    [...A, "criteria", ".."], [...A, "criteria", "a/b"], [...A, "criteria", "a%2Fb"],
    [...A, "snapshots", "s1", "x"], [...A, "sources", "extra"], [...A, ""],
    ["analyses", "a1", "intents"], ["intent"],
  ]) {
    assert.equal(proxy.checkRoute(segs, "GET"), "not_found", segs.join("/"));
  }
});

const cfg = { apiBaseUrl: "https://api.test", organizationId: "org-1", apiKey: "secret-key" };
const intentPatch = { segments: ["analyses", "a1", "intent", "criteria", "c1"], method: "PATCH" };

test("If-Match and X-Radius-Actor are forwarded only when valid, on intent writes", () => {
  const incoming = new Headers({ "If-Match": '"3f9a0c"', "X-Radius-Actor": "user:abc-123" });
  const out = proxy.buildUpstreamHeaders(cfg, incoming, intentPatch);
  assert.equal(out.get("If-Match"), '"3f9a0c"');
  assert.equal(out.get("X-Radius-Actor"), "user:abc-123");
  assert.equal(proxy.buildUpstreamHeaders(cfg, new Headers({ "If-Match": "*" }), intentPatch).get("If-Match"), "*");
  assert.equal(
    proxy.buildUpstreamHeaders(cfg, new Headers({ "If-Match": '"a1", "b2"' }), intentPatch).get("If-Match"),
    '"a1", "b2"',
  );
  const post = { segments: ["analyses", "a1", "intent", "sources"], method: "POST" };
  assert.equal(proxy.buildUpstreamHeaders(cfg, incoming, post).get("X-Radius-Actor"), "user:abc-123");
});

test("invalid If-Match and actor values are dropped", () => {
  for (const bad of ['W/"weak"', "abc", '"a b"', '""', '"x"\r\nX-Evil: 1', '"a",', "*, *", `"${"a".repeat(200)}"`]) {
    const headers = new Headers();
    try {
      headers.set("If-Match", bad);
    } catch {
      continue; // the Headers API itself refuses values with CR/LF
    }
    const out = proxy.buildUpstreamHeaders(cfg, headers, intentPatch);
    assert.equal(out.get("If-Match"), null, bad);
  }
  for (const bad of ["has space", "bad/slash", "x".repeat(129), "<script>", "a,b"]) {
    const out = proxy.buildUpstreamHeaders(cfg, new Headers({ "X-Radius-Actor": bad }), intentPatch);
    assert.equal(out.get("X-Radius-Actor"), null, JSON.stringify(bad));
  }
});

test("If-Match and actor are never forwarded outside intent writes", () => {
  const incoming = new Headers({ "If-Match": '"abc"', "X-Radius-Actor": "user:u1" });
  for (const route of [
    undefined,
    { segments: ["analyses", "a1", "intent"], method: "GET" },
    { segments: ["analyses", "a1", "rerun"], method: "POST" },
    { segments: ["repositories", "r1"], method: "PATCH" },
  ]) {
    const out = proxy.buildUpstreamHeaders(cfg, incoming, route);
    assert.equal(out.get("If-Match"), null);
    assert.equal(out.get("X-Radius-Actor"), null);
  }
});

test("no other client-supplied X-Radius-* header leaks, and the key stays server-side", () => {
  const incoming = new Headers({
    "X-Radius-API-Key": "client-key",
    "X-Radius-Organization-Id": "other-org",
    "X-Radius-Role": "admin",
    "X-Radius-Actor": "user:u1",
    "If-Match": '"abc"',
  });
  const out = proxy.buildUpstreamHeaders(cfg, incoming, intentPatch);
  assert.equal(out.get("X-Radius-API-Key"), "secret-key");
  assert.equal(out.get("X-Radius-Organization-Id"), "org-1");
  assert.equal(out.get("X-Radius-Role"), null);
  const names = [...out.keys()].filter((k) => k.startsWith("x-radius-")).sort();
  assert.deepEqual(names, ["x-radius-actor", "x-radius-api-key", "x-radius-organization-id"]);
});

test("response ETag pattern accepts strong ETags only", () => {
  assert.equal(proxy.IF_MATCH_PATTERN.test('"3f9a"'), true);
  assert.equal(proxy.IF_MATCH_PATTERN.test('W/"3f9a"'), false);
});

test("B-07: a validated session is forwarded instead of any client actor header", () => {
  const jwt = "aaaa1111.bbbb2222.cccc3333";
  const incoming = new Headers({ "X-Radius-Actor": "user:forged", "X-Radius-Session": "client-sent" });
  const out = proxy.buildUpstreamHeaders(cfg, incoming, { ...intentPatch, actor: "me@example.com", session: jwt });
  assert.equal(out.get("X-Radius-Session"), jwt);
  assert.equal(out.get("X-Radius-Actor"), null);
  // the browser can never choose the session header
  const noSession = proxy.buildUpstreamHeaders(cfg, incoming, intentPatch);
  assert.equal(noSession.get("X-Radius-Session"), null);
  // a malformed value is not forwarded (and falls back to the validated actor)
  const bad = proxy.buildUpstreamHeaders(cfg, incoming, { ...intentPatch, session: "not a token\r\nx: y" });
  assert.equal(bad.get("X-Radius-Session"), null);
  // never outside intent writes
  const get = proxy.buildUpstreamHeaders(cfg, incoming, { segments: ["analyses", "a1", "intent"], method: "GET", session: jwt });
  assert.equal(get.get("X-Radius-Session"), null);
});
