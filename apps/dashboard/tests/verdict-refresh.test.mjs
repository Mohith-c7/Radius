import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test, { afterEach } from "node:test";

process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111";

const refresh = await import("../lib/verdict-refresh.ts");
const client = await import("../lib/verdict-v2.ts");

const example = JSON.parse(
  readFileSync(new URL("../../../docs/research/design/verdict_v2.example.08.json", import.meta.url), "utf8"),
);

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const snapshot = (revision, pending = false, failed = false) => ({
  verdict: { revision },
  refresh: { pending, failed },
});

function harness(snapshots, { cancelAfter = Infinity } = {}) {
  const calls = { loads: 0, sleeps: [] };
  return {
    calls,
    options: {
      load: async () => {
        const next = snapshots[Math.min(calls.loads, snapshots.length - 1)];
        calls.loads += 1;
        if (next instanceof Error) throw next;
        return next;
      },
      sleep: async (ms) => {
        calls.sleeps.push(ms);
      },
      cancelled: () => calls.loads >= cancelAfter,
    },
  };
}

test("followRefresh stops as soon as a newer revision appears", async () => {
  const h = harness([snapshot(3, true), snapshot(3, true), snapshot(4, false)]);
  const result = await refresh.followRefresh({ baseline: 3, ...h.options });
  assert.equal(result.verdict.revision, 4);
  assert.equal(h.calls.loads, 3);
  assert.deepEqual(h.calls.sleeps, refresh.REFRESH_DELAYS_MS.slice(0, 3));
});

test("followRefresh stops when no refresh is queued any more (nothing changed)", async () => {
  const h = harness([snapshot(3, false)]);
  const result = await refresh.followRefresh({ baseline: 3, ...h.options });
  assert.equal(result.verdict.revision, 3);
  assert.equal(h.calls.loads, 1);
});

test("followRefresh is bounded: it gives up after the last delay and keeps the last snapshot", async () => {
  const h = harness([snapshot(3, true, true)]);
  const result = await refresh.followRefresh({ baseline: 3, ...h.options });
  assert.equal(h.calls.loads, refresh.REFRESH_DELAYS_MS.length);
  assert.equal(result.refresh.failed, true);
  const total = h.calls.sleeps.reduce((a, b) => a + b, 0);
  assert.ok(total >= 20_000 && total <= 60_000, `total wait ${total} ms`);
  assert.ok(h.calls.sleeps.every((ms) => ms >= 1000), "no tight loop");
});

test("followRefresh survives a transient load error and honours cancellation", async () => {
  const flaky = harness([new Error("boom"), snapshot(4, false)]);
  const result = await refresh.followRefresh({ baseline: 3, ...flaky.options });
  assert.equal(result.verdict.revision, 4);

  const cancelled = harness([snapshot(3, true)], { cancelAfter: 1 });
  const out = await refresh.followRefresh({ baseline: 3, ...cancelled.options });
  assert.equal(cancelled.calls.loads, 1);
  assert.equal(out.verdict.revision, 3);

  const none = harness([new Error("down")]);
  assert.equal(await refresh.followRefresh({ baseline: 3, ...none.options }), null);
});

test("the intent-changed event reaches only the matching analysis and can be unsubscribed", () => {
  const listeners = new Map();
  globalThis.window = {
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name) => listeners.delete(name),
    dispatchEvent: (event) => {
      listeners.get(event.type)?.(event);
      return true;
    },
  };
  globalThis.CustomEvent = class {
    constructor(type, init) {
      this.type = type;
      this.detail = init?.detail;
    }
  };
  try {
    let hits = 0;
    const off = refresh.onIntentChanged("a1", () => (hits += 1));
    refresh.notifyIntentChanged("a2");
    assert.equal(hits, 0);
    refresh.notifyIntentChanged("a1");
    assert.equal(hits, 1);
    off();
    refresh.notifyIntentChanged("a1");
    assert.equal(hits, 1);
  } finally {
    delete globalThis.window;
    delete globalThis.CustomEvent;
  }
});

test("getVerdictV2 exposes the stale marker from the envelope meta", async () => {
  const reply = (meta) => async () =>
    new Response(JSON.stringify({ success: true, data: example, meta }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  globalThis.fetch = reply({ refresh_pending: true, refresh_reason: "intent_changed", refresh_failed: true });
  assert.deepEqual((await client.getVerdictV2("a1")).refresh, { pending: true, failed: true });
  globalThis.fetch = reply({});
  assert.deepEqual((await client.getVerdictV2("a1")).refresh, { pending: false, failed: false });
});

test("the intent panel announces a successful criterion change to the verdict panel", () => {
  const intent = readFileSync(new URL("../components/intent-panel.tsx", import.meta.url), "utf8");
  assert.ok(intent.includes("notifyIntentChanged(analysisId)"));
  const verdict = readFileSync(new URL("../components/verdict-v2-panel.tsx", import.meta.url), "utf8");
  assert.ok(verdict.includes("onIntentChanged(analysisId"));
  assert.ok(verdict.includes("followRefresh("));
});
