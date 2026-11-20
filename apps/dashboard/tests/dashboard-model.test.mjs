import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../lib/dashboard-model.ts");

const pr = {
  id: "pr-uuid-1",
  repository_id: "repo-1",
  github_pr_number: 154,
  title: "build(deps): Bump the npm group across 1 directory with 3 updates",
  source_branch: "dependabot/npm",
  target_branch: "develop",
  author: "dependabot",
  status: "open",
};
const prs = m.indexPullRequests([pr]);

function analysis(id, status, created_at, pull_request_id = "pr-uuid-1") {
  return { id, status, created_at, pull_request_id, commit_sha: `sha${id}`, repository_id: "repo-1" };
}

test("analysisLabel shows PR number and truncated title with the short id secondary", () => {
  const label = m.analysisLabel(analysis("d2e500e9-aaaa", "completed", ""), prs, 30);
  assert.equal(label.title, "#154 build(deps): Bump the npm gro…");
  assert.ok(label.title.length <= "#154 ".length + 30);
  assert.equal(label.secondary, "Analysis d2e500e9");
  assert.equal(label.pullRequest, pr);
});

test("analysisLabel falls back to the short analysis id for unknown or manual PRs", () => {
  const label = m.analysisLabel(analysis("abcdef0123456", "pending", "", "random-uuid"), prs);
  assert.equal(label.title, "Analysis abcdef01");
  assert.equal(label.pullRequest, null);
  assert.equal(m.analysisLabel({ id: null, pull_request_id: "" }, prs).title, "Analysis -");
});

test("truncate keeps short text and adds an ellipsis to long text", () => {
  assert.equal(m.truncate("  short  ", 10), "short");
  assert.equal(m.truncate("abcdefghij", 5), "abcd…");
});

test("pullRequestUrl builds a GitHub link and rejects malformed input", () => {
  assert.equal(m.pullRequestUrl("Mohith-c7/Radius", 154), "https://github.com/Mohith-c7/Radius/pull/154");
  assert.equal(m.pullRequestUrl(undefined, 1), null);
  assert.equal(m.pullRequestUrl("evil.test/x/../y", 1), null);
  assert.equal(m.pullRequestUrl("a/b", 0), null);
});

test("completedAnalyses and defaultComparePair pick the two newest completed runs", () => {
  const list = [
    analysis("p1", "pending", "2026-11-20T10:00:00Z"),
    analysis("c-old", "completed", "2026-11-01T10:00:00Z"),
    analysis("c-new", "COMPLETED", "2026-11-19T10:00:00Z"),
    analysis("f1", "failed", "2026-11-18T10:00:00Z"),
    analysis("c-mid", "completed", "2026-11-10T10:00:00Z"),
  ];
  assert.deepEqual(m.completedAnalyses(list).map((a) => a.id), ["c-new", "c-mid", "c-old"]);
  assert.deepEqual(m.defaultComparePair(list), ["c-new", "c-mid"]);
  assert.deepEqual(m.defaultComparePair([list[0], list[1]]), ["c-old", null]);
});

test("averageConfidence ignores missing scores and returns null when there are none", () => {
  assert.equal(m.averageConfidence([]), null);
  assert.equal(m.averageConfidence([{ confidence_score: 80 }, { confidence_score: 71 }]), 76);
  assert.equal(m.averageConfidence([{ confidence_score: Number.NaN }]), null);
});

test("search matchers cover PR number, title, repository, id prefix and commit", () => {
  const a = analysis("d2e500e9-aaaa", "completed", "");
  const ctx = { repositoryName: "Mohith-c7/Radius", pullRequest: pr };
  for (const query of ["", "#154", "154", "bump THE", "radius", "d2e5", "shad2e", "completed"]) {
    assert.ok(m.analysisMatches(a, query, ctx), query);
  }
  assert.equal(m.analysisMatches(a, "docker", ctx), false);
  assert.equal(m.analysisMatches(a, "bump", { repositoryName: "x" }), false);
  assert.ok(m.pullRequestMatches(pr, "dependabot", "Mohith-c7/Radius"));
  assert.ok(m.pullRequestMatches(pr, "radius", "Mohith-c7/Radius"));
  assert.equal(m.pullRequestMatches(pr, "docker", "Mohith-c7/Radius"), false);
  assert.ok(m.repositoryMatches({ full_name: "Mohith-c7/Radius" }, "RAD"));
});

test("describeReadiness reports the real /ready result", () => {
  assert.equal(m.describeReadiness("loading").tone, "neutral");
  assert.equal(m.describeReadiness({ status: 200 }).tone, "positive");
  assert.match(m.describeReadiness({ status: 503 }).text, /not ready \(HTTP 503\)/);
  assert.equal(m.describeReadiness({ status: 401 }).tone, "neutral");
  assert.equal(m.describeReadiness("error").tone, "warning");
});
