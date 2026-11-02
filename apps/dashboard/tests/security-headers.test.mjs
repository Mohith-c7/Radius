import assert from "node:assert/strict";
import test from "node:test";

const sh = await import("../lib/security-headers.mjs");

function directive(csp, name) {
  return csp.split("; ").find((d) => d === name || d.startsWith(`${name} `));
}

test("CSP uses a nonce with strict-dynamic and no script unsafe-inline/eval in production", () => {
  const csp = sh.buildCsp({ nonce: "abc123", apiOrigin: "https://api.example.com" });
  const script = directive(csp, "script-src");
  assert.match(script, /'nonce-abc123'/);
  assert.match(script, /'strict-dynamic'/);
  assert.doesNotMatch(script, /unsafe-inline|unsafe-eval/);
  assert.equal(directive(csp, "frame-ancestors"), "frame-ancestors 'none'");
  assert.equal(directive(csp, "object-src"), "object-src 'none'");
  assert.equal(directive(csp, "base-uri"), "base-uri 'self'");
  assert.equal(directive(csp, "form-action"), "form-action 'self'");
  assert.equal(directive(csp, "default-src"), "default-src 'self'");
  assert.equal(directive(csp, "connect-src"), "connect-src 'self' https://api.example.com");
  assert.equal(directive(csp, "upgrade-insecure-requests"), undefined);
});

test("CSP never contains wildcards or a bare scheme source for scripts", () => {
  const csp = sh.buildCsp({ nonce: "n", apiOrigin: "http://localhost:8000" });
  assert.doesNotMatch(directive(csp, "script-src"), /\*|https?:/);
  assert.doesNotMatch(directive(csp, "connect-src"), /\*/);
});

test("dev CSP adds eval and websockets only in development", () => {
  const dev = sh.buildCsp({ nonce: "n", isDev: true });
  assert.match(directive(dev, "script-src"), /'unsafe-eval'/);
  assert.match(directive(dev, "connect-src"), /ws:/);
  const prod = sh.buildCsp({ nonce: "n", isDev: false });
  assert.doesNotMatch(prod, /unsafe-eval|ws:/);
});

test("upgrade-insecure-requests only when requested", () => {
  assert.match(sh.buildCsp({ nonce: "n", upgradeInsecure: true }), /upgrade-insecure-requests/);
});

test("apiOriginFrom normalises URLs and tolerates garbage", () => {
  assert.equal(sh.apiOriginFrom("https://api.example.com/api/v1"), "https://api.example.com");
  assert.equal(sh.apiOriginFrom(undefined), "http://localhost:8000");
  assert.equal(sh.apiOriginFrom("not a url"), "");
});

test("static headers include the hardening set and HSTS only when enabled", () => {
  const map = Object.fromEntries(sh.staticSecurityHeaders().map((h) => [h.key, h.value]));
  assert.equal(map["X-Content-Type-Options"], "nosniff");
  assert.equal(map["X-Frame-Options"], "DENY");
  assert.equal(map["Referrer-Policy"], "strict-origin-when-cross-origin");
  assert.match(map["Permissions-Policy"], /camera=\(\)/);
  assert.equal(map["Cross-Origin-Opener-Policy"], "same-origin");
  assert.equal(map["Strict-Transport-Security"], undefined);
  const hsts = Object.fromEntries(
    sh.staticSecurityHeaders({ hstsEnabled: true }).map((h) => [h.key, h.value]),
  );
  assert.match(hsts["Strict-Transport-Security"], /max-age=\d+; includeSubDomains/);
});

test("hstsEnabledFrom parses truthy values only", () => {
  assert.equal(sh.hstsEnabledFrom({ RADIUS_HSTS_ENABLED: "true" }), true);
  assert.equal(sh.hstsEnabledFrom({ RADIUS_HSTS_ENABLED: "1" }), true);
  assert.equal(sh.hstsEnabledFrom({ RADIUS_HSTS_ENABLED: "false" }), false);
  assert.equal(sh.hstsEnabledFrom({}), false);
});
