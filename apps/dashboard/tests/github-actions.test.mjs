import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

process.env.NEXT_PUBLIC_RADIUS_API_BASE_URL = "https://radius.test/";
process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111";

const logic = await import("../lib/github-actions.ts");
const api = await import("../lib/api.ts");
const proxy = await import("../lib/proxy.ts");
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function reply(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("parseRepositoryInput accepts owner/name, URLs and .git, rejects typos", () => {
  for (const input of [
    " acme/widgets ",
    "https://github.com/acme/widgets",
    "github.com/acme/widgets.git/",
    "HTTP://GITHUB.COM/acme/widgets",
  ]) {
    const r = logic.parseRepositoryInput(input);
    assert.equal(r.ok, true, input);
    assert.equal(r.value, "acme/widgets");
  }
  for (const input of [
    "",
    "   ",
    "acme",
    "a/b/c",
    "acme/",
    "/widgets",
    "ac me/widgets",
    "acme/wid<script>",
    "a".repeat(200) + "/" + "b".repeat(200),
  ]) {
    const r = logic.parseRepositoryInput(input);
    assert.equal(r.ok, false, input);
    assert.ok(r.message.length > 10);
  }
});

test("request builders produce the exact allowlisted paths and methods", () => {
  const connect = logic.connectGitHubRequest("acme/widgets");
  assert.deepEqual(connect, {
    path: "/repositories/connect-github",
    method: "POST",
    body: '{"repository":"acme/widgets"}',
  });
  const analyze = logic.analyzePullRequestRequest("repo-1", 7);
  assert.deepEqual(analyze, { path: "/repositories/repo-1/pull-requests/7/analyze", method: "POST" });
  assert.throws(() => logic.analyzePullRequestRequest("repo-1", 0), RangeError);
  assert.throws(() => logic.analyzePullRequestRequest("repo-1", 1.5), RangeError);
  assert.equal(
    logic.syncPullRequestsRequest("r", false).path,
    "/repositories/r/sync-pull-requests?auto_analyze=false",
  );
  assert.equal(logic.rerunRequest("a1").path, "/analyses/a1/rerun");
  for (const spec of [connect, analyze, logic.syncPullRequestsRequest("repo-1"), logic.rerunRequest("a1")]) {
    const segments = spec.path.split("?")[0].split("/").filter(Boolean);
    assert.equal(proxy.checkRoute(segments, spec.method), "ok", spec.path);
    assert.notEqual(proxy.checkRoute(segments, "DELETE"), "ok", spec.path);
  }
});

test("proxy rejects near-miss routes of the new actions", () => {
  const c = proxy.checkRoute;
  assert.equal(c(["repositories", "connect-github", "x"], "POST"), "not_found");
  assert.equal(c(["repositories", "r1", "pull-requests", "7", "analyze", "x"], "POST"), "not_found");
  assert.equal(c(["repositories", "r1", "pull-requests", "7", "analyze"], "PUT"), "method");
  assert.equal(c(["repositories", "r1", "sync-pull-requests"], "GET"), "method");
  assert.equal(c(["analyses", "a1", "rerun"], "GET"), "method");
});

test("describeGitHubError maps every API code to guidance and keeps server detail", () => {
  for (const code of [
    "GITHUB_APP_NOT_CONFIGURED",
    "GITHUB_APP_NOT_INSTALLED",
    "GITHUB_APP_AUTH_FAILED",
    "GITHUB_REPOSITORY_NOT_ACCESSIBLE",
    "GITHUB_INSTALLATION_MISMATCH",
    "GITHUB_RATE_LIMITED",
    "GITHUB_API_ERROR",
    "REPOSITORY_DISCONNECTED",
  ]) {
    const v = logic.describeGitHubError({ status: 409, code, message: "server says X" });
    assert.ok(v.title.length > 30, code);
    assert.equal(v.detail, "server says X");
  }
  assert.match(
    logic.describeGitHubError({ status: 409, code: "GITHUB_APP_NOT_CONFIGURED", message: "m" }).title,
    /GITHUB_APP_ID/,
  );
  assert.match(logic.describeGitHubError(new TypeError("Failed to fetch")).title, /Could not reach/);
  assert.match(logic.describeGitHubError({ status: 429, code: null, message: "slow" }).title, /Too many/);
  assert.equal(
    logic.describeGitHubError({ status: 404, code: "NOT_FOUND", message: "Pull request #9 not found" }).title,
    "Pull request #9 not found",
  );
  assert.equal(logic.describeGitHubError({ status: 500, code: "X", message: "boom" }).title, "boom");
  assert.equal(
    logic.errorText({ status: 409, code: "REPOSITORY_DISCONNECTED", message: "gone" }).endsWith("(gone)"),
    true,
  );
});

test("summarizeSync reads meta defensively and lists skipped reasons", () => {
  const s = logic.summarizeSync(3, {
    github: "synced",
    analysisIds: ["a", "b"],
    skipped: [{ number: 9, reason: "GITHUB_API_ERROR: bad shape" }, null, { reason: 5 }, "x"],
  });
  assert.equal(s.kind, "synced");
  assert.equal(s.analysesQueued, 2);
  assert.deepEqual(s.skipped, [
    { number: 9, reason: "GITHUB_API_ERROR: bad shape" },
    { number: null, reason: "unknown reason" },
  ]);
  assert.match(s.text, /Synced 3 pull requests from GitHub, 2 new analyses queued, 2 skipped\./);
  assert.equal(logic.skippedLabel(s.skipped[0]), "#9: GITHUB_API_ERROR: bad shape");
  assert.match(
    logic.summarizeSync(1, { analysisIds: ["a"] }).text,
    /Synced 1 pull request from GitHub, 1 new analysis queued\./,
  );
  const nc = logic.summarizeSync(2, { github: "not_configured" });
  assert.equal(nc.kind, "not_configured");
  assert.match(nc.text, /not configured/);
  assert.equal(logic.summarizeSync(0, undefined).analysesQueued, 0);
});

test("connectMessage and canAnalyze", () => {
  assert.equal(logic.connectMessage("a/b", true), "Connected a/b.");
  assert.match(logic.connectMessage("a/b", false), /already connected/);
  assert.equal(logic.canAnalyze({ status: "open" }), true);
  assert.equal(logic.canAnalyze({ status: "merged" }), false);
});

test("connectGitHubRepository posts JSON through the proxy and reads meta", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/repositories/connect-github");
    assert.equal(init.method, "POST");
    assert.equal(init.body, '{"repository":"acme/widgets"}');
    assert.equal(new Headers(init.headers).get("X-Radius-API-Key"), null);
    return reply(
      { success: true, data: { id: "r1", full_name: "acme/widgets" }, meta: { created: false, installationId: 9001 } },
      200,
    );
  };
  const r = await api.connectGitHubRepository("acme/widgets");
  assert.equal(r.repository.id, "r1");
  assert.equal(r.created, false);
  assert.equal(r.installationId, 9001);
});

test("connectGitHubRepository keeps the API error code", async () => {
  globalThis.fetch = async () =>
    reply({ success: false, data: null, error: { code: "GITHUB_REPOSITORY_NOT_ACCESSIBLE", message: "404" } }, 404);
  await assert.rejects(api.connectGitHubRepository("acme/nope"), (e) => {
    assert.equal(e.code, "GITHUB_REPOSITORY_NOT_ACCESSIBLE");
    assert.equal(e.status, 404);
    return true;
  });
});

test("analyzePullRequest and rerunAnalysis call the right routes", async () => {
  const seen = [];
  globalThis.fetch = async (input, init) => {
    seen.push([String(input), init.method, new Headers(init.headers).get("Idempotency-Key")]);
    return reply({ success: true, data: { id: "an1", status: "pending" } }, 202);
  };
  assert.equal((await api.analyzePullRequest("r1", 7)).id, "an1");
  assert.equal((await api.rerunAnalysis("an0")).id, "an1");
  assert.deepEqual(seen[0], [
    "http://dashboard.test/api/radius/repositories/r1/pull-requests/7/analyze",
    "POST",
    null,
  ]);
  assert.equal(seen[1][0], "http://dashboard.test/api/radius/analyses/an0/rerun");
  assert.ok(seen[1][2] && seen[1][2].length >= 8);
});

test("rerunAnalysis surfaces a disconnected repository code", async () => {
  globalThis.fetch = async () =>
    reply(
      { success: false, data: null, error: { code: "REPOSITORY_DISCONNECTED", message: "Repository is disconnected." } },
      409,
    );
  await assert.rejects(api.rerunAnalysis("a"), (e) => e.code === "REPOSITORY_DISCONNECTED");
});

test("syncPullRequestsDetailed returns the skipped reasons from meta", async () => {
  globalThis.fetch = async (input) => {
    assert.match(String(input), /sync-pull-requests\?auto_analyze=true$/);
    return reply({
      success: true,
      data: [{ id: "p1" }],
      meta: { github: "synced", analysisIds: [], skipped: [{ number: 4, reason: "x" }] },
    });
  };
  const r = await api.syncPullRequestsDetailed("r1");
  assert.equal(r.pullRequests.length, 1);
  assert.deepEqual(r.summary.skipped, [{ number: 4, reason: "x" }]);
  assert.equal((await api.syncPullRequests("r1")).length, 1);
});
