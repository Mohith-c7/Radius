import assert from "node:assert/strict";
import test from "node:test";

const { apiRewritesFrom } = await import("../lib/api-rewrites.mjs");

test("no upstream means no rewrite (default deployments are unchanged)", () => {
  assert.deepEqual(apiRewritesFrom({}), []);
  assert.deepEqual(apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "  " }), []);
});

test("an https upstream forwards /api/v1/* to the same path on the API", () => {
  assert.deepEqual(apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "https://radius-api.onrender.com" }), [
    { source: "/api/v1/:path*", destination: "https://radius-api.onrender.com/api/v1/:path*" },
  ]);
});

test("trailing slash is accepted, http only for localhost", () => {
  assert.equal(
    apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "https://api.example.com/" })[0].destination,
    "https://api.example.com/api/v1/:path*",
  );
  assert.equal(apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "http://localhost:8000" }).length, 1);
  assert.throws(() => apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "http://api.example.com" }), /https/);
});

test("anything but a bare origin is refused", () => {
  assert.throws(() => apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "not a url" }), /not a URL/);
  assert.throws(() => apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "https://api.example.com/api/v1" }), /origin/);
  assert.throws(() => apiRewritesFrom({ RADIUS_API_PUBLIC_UPSTREAM: "https://api.example.com?x=1" }), /origin/);
});
