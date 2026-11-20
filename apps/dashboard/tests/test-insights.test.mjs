import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../lib/test-insights-model.ts");
const proxy = await import("../lib/proxy.ts");

function exec(id, test_name, status, timestamp, commit_sha = "aaa111", extra = {}) {
  return {
    id,
    test_name,
    test_path: `tests/test_${test_name}.py`,
    status,
    duration_ms: 10,
    timestamp,
    commit_sha,
    branch: "feature",
    ...extra,
  };
}

const rows = [
  exec("1", "login", "passed", "2026-11-18T10:00:00Z", "old"),
  exec("2", "login", "failed", "2026-11-19T10:00:00Z", "new"),
  exec("3", "signup", "passed", "2026-11-19T10:00:01Z", "new"),
  exec("4", "export", "skipped", "2026-11-19T10:00:02Z", "new"),
];

test("test insight routes are allowlisted read-only", () => {
  for (const route of ["statistics", "flaky", "recent"]) {
    assert.equal(proxy.checkRoute(["analyses", "a1", "tests", route], "GET"), "ok");
    assert.equal(proxy.checkRoute(["analyses", "a1", "tests", route], "POST"), "method");
    assert.equal(proxy.checkRoute(["analyses", "a1", "tests", route], "DELETE"), "method");
  }
  assert.equal(proxy.checkRoute(["analyses", "a1", "tests", "history"], "GET"), "not_found");
  assert.equal(proxy.checkRoute(["analyses", "a1", "tests", "recent", "x"], "GET"), "not_found");
});

// api-keys routes are allowlisted only together with the admin role gate and
// the API's admin-session check; tests/proxy-api-keys.test.mjs covers both.
test("api-keys routes are allowlisted only with exact methods", () => {
  assert.equal(proxy.checkRoute(["api-keys"], "GET"), "ok");
  assert.equal(proxy.checkRoute(["api-keys"], "PATCH"), "method");
  assert.equal(proxy.checkRoute(["api-keys", "audit"], "POST"), "method");
});

test("statusKind normalizes common JUnit outcomes", () => {
  assert.equal(m.statusKind("PASSED"), "passed");
  assert.equal(m.statusKind("error"), "failed");
  assert.equal(m.statusKind("skipped"), "skipped");
  assert.equal(m.statusKind(undefined), "other");
});

test("summarizeExecutions excludes skipped tests from the pass rate", () => {
  const summary = m.summarizeExecutions(rows);
  assert.deepEqual(
    { ...summary },
    { total: 4, passed: 2, failed: 1, skipped: 1, passRate: 66.7, lastRun: "2026-11-19T10:00:02Z" },
  );
  assert.equal(m.summarizeExecutions([]).passRate, null);
  assert.equal(m.summarizeExecutions([rows[3]]).passRate, null);
});

test("groupRuns makes one run per commit, newest first", () => {
  const runs = m.groupRuns(rows);
  assert.deepEqual(runs.map((r) => [r.commitSha, r.total, r.failed]), [["new", 3, 1], ["old", 1, 0]]);
});

test("summarizeTests and historyForTest give per-test views", () => {
  const tests = m.summarizeTests(rows);
  const login = tests.find((t) => t.testName === "login");
  assert.equal(login.runs, 2);
  assert.equal(login.failures, 1);
  assert.equal(login.lastStatus, "failed");
  assert.deepEqual(m.historyForTest(rows, login.key).map((r) => r.id), ["2", "1"]);
  // Flaky rows only carry the path.
  assert.deepEqual(m.historyForTest(rows, "tests/test_login.py").map((r) => r.id), ["2", "1"]);
});

test("anchorAnalysis and analysisForCommit pick the newest matching analysis", () => {
  const analyses = [
    { id: "a-old", commit_sha: "new", created_at: "2026-11-01T00:00:00Z" },
    { id: "a-new", commit_sha: "new", created_at: "2026-11-19T00:00:00Z" },
    { id: null, commit_sha: "x", created_at: "2026-11-20T00:00:00Z" },
    { id: "a-other", commit_sha: "old", created_at: "2026-11-10T00:00:00Z" },
  ];
  assert.equal(m.anchorAnalysis(analyses).id, "a-new");
  assert.equal(m.anchorAnalysis([]), null);
  assert.equal(m.analysisForCommit(analyses, "old").id, "a-other");
  assert.equal(m.analysisForCommit(analyses, "missing"), null);
  assert.equal(m.analysisForCommit(analyses, null), null);
});

test("formatters handle missing values", () => {
  assert.equal(m.formatPercent(null), "-");
  assert.equal(m.formatPercent(66.66), "66.7%");
  assert.equal(m.formatDuration(250), "250 ms");
  assert.equal(m.formatDuration(1530), "1.5 s");
  assert.equal(m.shortSha("abcdef0123"), "abcdef01");
  assert.equal(m.shortSha(null), "-");
});
