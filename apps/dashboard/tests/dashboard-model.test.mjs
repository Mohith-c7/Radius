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

test("analysisLabel falls back to the short analysis id for a PR that is not synced", () => {
  const label = m.analysisLabel(analysis("abcdef0123456", "pending", "", "random-uuid"), prs);
  assert.equal(label.title, "Analysis abcdef01");
  assert.equal(label.secondary, "Pull request not synced");
  assert.equal(label.pullRequest, null);
});

test("analysisLabel names a PR-less analysis by its branch/commit", () => {
  const manual = { id: "abcdef0123456", pull_request_id: null, commit_sha: "90bd4aa7439419186a85" };
  const label = m.analysisLabel(manual, prs);
  assert.equal(label.title, "Branch/commit 90bd4aa");
  assert.equal(label.secondary, "Analysis abcdef01");
  assert.equal(label.pullRequest, null);
  assert.equal(m.analysisLabel({ id: null, pull_request_id: null }, prs).title, "Branch/commit");
});

test("analysisHeading says branch/commit verification when there is no PR", () => {
  assert.deepEqual(m.analysisHeading({ pull_request_id: null, commit_sha: "90bd4aa7439419" }, "acme/radius"), {
    title: "Branch/commit verification",
    description: "acme/radius / Branch/commit 90bd4aa",
  });
  assert.deepEqual(m.analysisHeading({ pull_request_id: "pr-uuid-1", commit_sha: "a" }, "acme/radius", pr), {
    title: "Pull request verification",
    description: "acme/radius / PR #154 build(deps): Bump the npm group across 1 directory with 3 u…",
  });
  assert.equal(
    m.analysisHeading({ pull_request_id: "12345678-aaaa", commit_sha: "a" }, "acme/radius").description,
    "acme/radius / PR 12345678",
  );
});

test("pullRequestOptionLabel and initialBranch drive the Run Verification form", () => {
  assert.equal(m.pullRequestOptionLabel(pr, 30), "#154 build(deps): Bump the npm gro…");
  assert.equal(m.pullRequestOptionLabel({ github_pr_number: 7, title: "Fix login" }), "#7 Fix login");
  const branches = [
    { id: "b1", repository_id: "r", name: "feature", latest_commit_sha: "111" },
    { id: "b2", repository_id: "r", name: "main", latest_commit_sha: "222" },
  ];
  assert.equal(m.initialBranch({ default_branch: "main", branches })?.latest_commit_sha, "222");
  assert.equal(m.initialBranch({ default_branch: "develop", branches })?.name, "feature");
  assert.equal(m.initialBranch({ default_branch: "main", branches: [] }), null);
  assert.equal(m.initialBranch({ default_branch: "main" }), null);
});

test("filterAnalyses filters the analyses list by status and repository", () => {
  const list = [
    { id: "1", status: "completed", repository_id: "r1" },
    { id: "2", status: "FAILED", repository_id: "r1" },
    { id: "3", status: "pending", repository_id: "r2" },
  ];
  const ids = (items) => items.map((a) => a.id);
  assert.deepEqual(m.ANALYSIS_STATUS_FILTERS, ["all", "pending", "running", "completed", "failed"]);
  assert.deepEqual(ids(m.filterAnalyses(list, { status: "all", repositoryId: "all" })), ["1", "2", "3"]);
  assert.deepEqual(ids(m.filterAnalyses(list, {})), ["1", "2", "3"]);
  assert.deepEqual(ids(m.filterAnalyses(list, { status: "failed" })), ["2"]);
  assert.deepEqual(ids(m.filterAnalyses(list, { repositoryId: "r1" })), ["1", "2"]);
  assert.deepEqual(ids(m.filterAnalyses(list, { status: "pending", repositoryId: "r1" })), []);
  assert.deepEqual(ids(m.filterAnalyses(list, { status: "running" })), []);
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
