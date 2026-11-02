import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111";

const intent = await import("../lib/intent.ts");
const model = await import("../lib/intent-model.ts");
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function reply(body, { status = 200, headers = {} } = {}) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
const ok = (data, extra = {}) => reply({ success: true, data, meta: extra.meta ?? {} }, extra);
const fail = (status, code, message) => reply({ success: false, data: null, error: { code, message } }, { status });

test("getIntent returns the snapshot and its ETag header", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/analyses/a1/intent");
    assert.equal(init.cache, "no-store");
    const h = new Headers(init.headers);
    assert.equal(h.get("X-Radius-API-Key"), null);
    return ok({ id: "s", version: 2, etag: '"body"', criteria: [], sources: [] }, { headers: { ETag: '"hdr"' } });
  };
  const { snapshot, etag } = await intent.getIntent("a1");
  assert.equal(snapshot.version, 2);
  assert.equal(etag, '"hdr"');
});

test("getIntent falls back to the etag in the body", async () => {
  globalThis.fetch = async () => ok({ version: 1, etag: '"body"', criteria: [], sources: [] });
  assert.equal((await intent.getIntent("a1")).etag, '"body"');
});

test("INTENT_NOT_FOUND maps to the empty state", async () => {
  globalThis.fetch = async () => fail(404, "INTENT_NOT_FOUND", "No intent yet.");
  await assert.rejects(intent.getIntent("a1"), (e) => {
    assert.equal(e.code, "INTENT_NOT_FOUND");
    assert.equal(e.status, 404);
    assert.equal(model.classifyIntentError(e).kind, "not_found");
    return true;
  });
});

test("patchCriterion sends If-Match and actor, JSON body, PATCH", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/analyses/a1/intent/criteria/crit_9");
    assert.equal(init.method, "PATCH");
    const h = new Headers(init.headers);
    assert.equal(h.get("If-Match"), '"abc"');
    assert.equal(h.get("X-Radius-Actor"), "user:u1");
    assert.equal(h.get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(init.body), { action: "edit", text: "New" });
    return ok({ criterion: { id: "crit_9", state: "edited" }, snapshot_id: "s", snapshot_version: 3, etag: '"def"', created: false });
  };
  const r = await intent.patchCriterion("a1", "crit_9", { action: "edit", text: "New" }, { ifMatch: '"abc"', actor: "user:u1" });
  assert.equal(r.etag, '"def"');
});

test("headers are omitted when no ETag or actor is known", async () => {
  globalThis.fetch = async (_i, init) => {
    const h = new Headers(init.headers);
    assert.equal(h.has("If-Match"), false);
    assert.equal(h.has("X-Radius-Actor"), false);
    return ok({ criterion: {}, snapshot_id: "s", snapshot_version: 1, etag: '"e"' });
  };
  await intent.patchCriterion("a1", "c", { action: "confirm" }, { ifMatch: null, actor: null });
});

test("INTENT_STALE (409) is a typed stale error", async () => {
  globalThis.fetch = async () => fail(409, "INTENT_STALE", "If-Match mismatch");
  await assert.rejects(intent.patchCriterion("a1", "c", { action: "confirm" }, { ifMatch: '"old"' }), (e) => {
    assert.equal(model.classifyIntentError(e).kind, "stale");
    return true;
  });
});

test("ILLEGAL_STATE_TRANSITION is typed", async () => {
  globalThis.fetch = async () => fail(409, "ILLEGAL_STATE_TRANSITION", "Illegal transition rejected -> confirmed.");
  await assert.rejects(intent.patchCriterion("a1", "c", { action: "confirm" }), (e) => {
    assert.equal(model.classifyIntentError(e).kind, "illegal_transition");
    return true;
  });
});

test("INTENT_SPEC_INVALID surfaces line-numbered messages", async () => {
  globalThis.fetch = async () => fail(422, "INTENT_SPEC_INVALID", "Invalid .radius/intent.yml: line 4: weight must be a number in (0, 1] [spec_invalid_weight]");
  await assert.rejects(intent.submitIntentSource("a1", { kind: "spec_file", text: "x" }), (e) => {
    const info = model.classifyIntentError(e);
    assert.equal(info.kind, "spec_invalid");
    assert.equal(info.lines[0].startsWith("line 4:"), true);
    return true;
  });
});

test("submitIntentSource posts camelCase fields", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/analyses/a1/intent/sources");
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), { kind: "agent_prompt", text: "Do X", sourceId: "p1" });
    return ok({ snapshot: {}, created: true, report: {}, sanitization: { removed: [], flagged: [] } }, { status: 201 });
  };
  const r = await intent.submitIntentSource("a1", { kind: "agent_prompt", text: "Do X", sourceId: "p1" });
  assert.equal(r.created, true);
});

test("rebuild, add criterion, sources, history, snapshots, diff use the right routes", async () => {
  const seen = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    seen.push(`${init.method ?? "GET"} ${url.pathname}${url.search}`);
    return ok([], { meta: { nextCursor: 4 } });
  };
  await intent.rebuildIntent("a1");
  await intent.addCriterion("a1", { text: "t" });
  await intent.getIntentSources("a1");
  await intent.getCriterionHistory("a1", "crit_1");
  const page = await intent.listSnapshots("a1", 7);
  await intent.getIntentDiff("a1", 1, 2);
  assert.deepEqual(seen, [
    "POST /api/radius/analyses/a1/intent/rebuild",
    "POST /api/radius/analyses/a1/intent/criteria",
    "GET /api/radius/analyses/a1/intent/sources",
    "GET /api/radius/analyses/a1/intent/criteria/crit_1/history",
    "GET /api/radius/analyses/a1/intent/snapshots?cursor=7",
    "GET /api/radius/analyses/a1/intent/diff?from=1&to=2",
  ]);
  assert.equal(page.nextCursor, 4);
});

test("path segments are URL-encoded", async () => {
  globalThis.fetch = async (input) => {
    assert.equal(new URL(String(input)).pathname, "/api/radius/analyses/a%2F1/intent");
    return ok({ version: 1, etag: '"e"', criteria: [], sources: [] });
  };
  await intent.getIntent("a/1");
});

test("non-JSON upstream failures still produce a typed error", async () => {
  globalThis.fetch = async () => new Response("<html>bad gateway</html>", { status: 502 });
  await assert.rejects(intent.getIntent("a1"), (e) => {
    assert.equal(e.name, "RadiusApiError");
    assert.equal(e.status, 502);
    assert.equal(e.code, null);
    return true;
  });
});
