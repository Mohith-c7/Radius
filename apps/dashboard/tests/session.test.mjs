import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const session = await import("../lib/session.ts");
const proxy = await import("../lib/proxy.ts");

const BASE = "http://api.test:8000";
// Cookie values are built at runtime; they are not credentials.
const goodCookie = ["fake", "session", String(Date.now())].join(".");

function jsonResponse(status, body) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeFetch(handler) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init, calls.length);
  };
  return { impl, calls };
}

const user = { id: "u1", email: "dev@example.test", role: "developer", email_verified: true };

function opts(fetchImpl, extra = {}) {
  return { apiBaseUrl: BASE, fetchImpl, cache: new session.SessionCache(), ...extra };
}

test("empty or missing cookie is rejected without calling the API", async () => {
  const f = makeFetch(() => jsonResponse(200, user));
  assert.deepEqual(await session.validateSession(undefined, opts(f.impl)), { ok: false, reason: "missing" });
  assert.deepEqual(await session.validateSession("", opts(f.impl)), { ok: false, reason: "missing" });
  assert.equal(f.calls.length, 0);
});

test("cookie values that could inject headers are rejected locally", async () => {
  const f = makeFetch(() => jsonResponse(200, user));
  for (const bad of ["a b", "a;b=c", "a\r\nX-Evil: 1", 'a"b', "a,b", "x".repeat(5000)]) {
    const r = await session.validateSession(bad, opts(f.impl));
    assert.equal(r.ok, false, JSON.stringify(bad));
  }
  assert.equal(f.calls.length, 0);
});

test("forged cookie: API answers 401 -> not signed in", async () => {
  const f = makeFetch(() => jsonResponse(401, { detail: "expired" }));
  const r = await session.validateSession(goodCookie, opts(f.impl));
  assert.deepEqual(r, { ok: false, reason: "invalid" });
  assert.equal(f.calls[0].url, `${BASE}/api/v1/auth/me`);
  assert.equal(f.calls[0].init.headers.Cookie, `radius_session=${goodCookie}`);
});

test("valid session returns the user", async () => {
  const f = makeFetch(() => jsonResponse(200, user));
  const r = await session.validateSession(goodCookie, opts(f.impl));
  assert.equal(r.ok, true);
  assert.equal(r.user.email, "dev@example.test");
  assert.equal(r.user.role, "developer");
});

test("API down, 5xx, malformed body and timeout all fail closed (not cached)", async () => {
  const cases = [
    () => {
      throw new TypeError("fetch failed");
    },
    () => jsonResponse(500, { detail: "boom" }),
    () => jsonResponse(502),
    () => jsonResponse(200, { nothing: true }),
    () => new Response("not json", { status: 200 }),
  ];
  for (const h of cases) {
    const f = makeFetch(h);
    const o = opts(f.impl);
    const r = await session.validateSession(goodCookie, o);
    assert.deepEqual(r, { ok: false, reason: "unavailable" });
    await session.validateSession(goodCookie, o);
    assert.equal(f.calls.length, 2, "failures must not be cached");
  }
  const slow = makeFetch((_u, init) => new Promise((_res, rej) => init.signal.addEventListener("abort", () => rej(new Error("timeout")))));
  const r = await session.validateSession(goodCookie, opts(slow.impl, { timeoutMs: 20 }));
  assert.deepEqual(r, { ok: false, reason: "unavailable" });
});

test("positive answers are cached, then expire", async () => {
  let t = 1_000_000;
  const f = makeFetch(() => jsonResponse(200, user));
  const o = opts(f.impl, { now: () => t, positiveTtlMs: 10_000 });
  await session.validateSession(goodCookie, o);
  await session.validateSession(goodCookie, o);
  assert.equal(f.calls.length, 1);
  t += 9_999;
  await session.validateSession(goodCookie, o);
  assert.equal(f.calls.length, 1);
  t += 2;
  await session.validateSession(goodCookie, o);
  assert.equal(f.calls.length, 2, "re-validated after the TTL");
});

test("a session revoked after caching is rejected once the cache expires", async () => {
  let t = 5_000;
  let live = true;
  const f = makeFetch(() => (live ? jsonResponse(200, user) : jsonResponse(401, {})));
  const o = opts(f.impl, { now: () => t, positiveTtlMs: 1_000, negativeTtlMs: 1_000 });
  assert.equal((await session.validateSession(goodCookie, o)).ok, true);
  live = false;
  assert.equal((await session.validateSession(goodCookie, o)).ok, true, "still inside the TTL");
  t += 1_001;
  assert.deepEqual(await session.validateSession(goodCookie, o), { ok: false, reason: "invalid" });
});

test("cache is keyed per cookie and bounded", async () => {
  const f = makeFetch((_u, init) =>
    init.headers.Cookie.endsWith("good") ? jsonResponse(200, user) : jsonResponse(401, {}),
  );
  const o = opts(f.impl);
  assert.equal((await session.validateSession("aaa-good", o)).ok, true);
  assert.equal((await session.validateSession("aaa-bad", o)).ok, false);
  assert.equal((await session.validateSession("aaa-good", o)).ok, true);
  assert.equal(f.calls.length, 2);
  const key = await o.cache.keyFor("aaa-good");
  assert.ok(!key.includes("aaa-good"), "raw cookie is not the cache key");
  for (let i = 0; i < 600; i += 1) await session.validateSession(`bulk-${i}-good`, o);
  assert.ok(o.cache.entries.size <= 500);
});

test("only admins may use DELETE", () => {
  const dev = { id: "1", email: "a@b.test", role: "developer", emailVerified: true };
  const admin = { ...dev, role: "admin" };
  assert.equal(session.roleAllows(dev, "DELETE"), false);
  assert.equal(session.roleAllows(dev, "delete"), false);
  assert.equal(session.roleAllows(admin, "DELETE"), true);
  assert.equal(session.roleAllows(dev, "GET"), true);
  assert.equal(session.roleAllows(dev, "POST"), true);
});

test("audit actor comes from the validated session, not the client header", () => {
  const cfg = { apiBaseUrl: BASE, organizationId: "o", apiKey: "k" };
  const incoming = new Headers({ "x-radius-actor": "spoofed-admin", "content-type": "application/json" });
  const route = { segments: ["analyses", "a1", "intent", "criteria"], method: "POST" };
  assert.equal(proxy.buildUpstreamHeaders(cfg, incoming, { ...route, actor: "real@example.test" }).get("x-radius-actor"), "real@example.test");
  assert.equal(proxy.buildUpstreamHeaders(cfg, incoming, { ...route, actor: "not valid!" }).get("x-radius-actor"), null);
});

test("route handler and middleware validate the session instead of trusting cookie presence", () => {
  const route = readFileSync(new URL("../app/api/radius/[...path]/route.ts", import.meta.url), "utf8");
  const mw = readFileSync(new URL("../middleware.ts", import.meta.url), "utf8");
  assert.match(route, /validateSession\(/);
  assert.match(route, /roleAllows\(/);
  assert.match(mw, /validateSession\(/);
  assert.doesNotMatch(mw, /hasSession\s*=\s*Boolean\(request\.cookies/);
});
