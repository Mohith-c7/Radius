import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Next.js compiles each matcher entry like a path-to-regexp pattern; the single entry
// here is a plain regex group, so anchoring it reproduces what Next matches.
const source = readFileSync(new URL("../middleware.ts", import.meta.url), "utf8");
const pattern = source.match(/matcher:\s*\["([^"]+)"\]/)[1];
const matches = (path) => new RegExp(`^${pattern}$`).test(path);

test("the API proxy path never reaches the session middleware", () => {
  for (const path of ["/api/v1/auth/login", "/api/v1/health", "/api/v1"]) {
    assert.equal(matches(path), false, path);
  }
});

test("pages and the dashboard's own proxy still go through the middleware", () => {
  for (const path of ["/", "/login", "/analyses/123", "/api/radius/analyses", "/api/v10/x"]) {
    assert.equal(matches(path), true, path);
  }
  assert.equal(matches("/_next/static/chunk.js"), false);
});
