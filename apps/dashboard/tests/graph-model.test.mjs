import assert from "node:assert/strict";
import test from "node:test";

const g = await import("../lib/graph-model.ts");

test("graphPath asks for the bounded impact slice by default request", () => {
  assert.equal(
    g.graphPath("a-1", g.DASHBOARD_GRAPH_REQUEST),
    "/analyses/a-1/graph?scope=impact&depth=1&limit=1500",
  );
  assert.equal(g.graphPath("a/1"), "/analyses/a%2F1/graph");
  assert.equal(g.graphPath("x", { scope: "full", limit: 10 }), "/analyses/x/graph?scope=full&limit=10");
  assert.ok(g.DASHBOARD_GRAPH_REQUEST.limit <= 5000, "API caps limit at 5000");
});

const analysis = (id, status, completed_at, created_at = "2026-01-01T00:00:00Z") => ({
  id,
  status,
  completed_at,
  created_at,
});

test("pickNewestCompletedAnalysis skips pending, running and id-less analyses", () => {
  const picked = g.pickNewestCompletedAnalysis([
    analysis("pending", "pending", null, "2026-03-01T00:00:00Z"),
    analysis("running", "running", null, "2026-03-02T00:00:00Z"),
    analysis(null, "completed", "2026-03-03T00:00:00Z"),
    analysis("old", "completed", "2026-02-01T00:00:00Z"),
    analysis("new", "COMPLETED", "2026-02-10T00:00:00Z"),
    analysis("failed", "failed", "2026-02-20T00:00:00Z"),
  ]);
  assert.equal(picked?.id, "new");
});

test("pickNewestCompletedAnalysis returns null when nothing has completed", () => {
  assert.equal(g.pickNewestCompletedAnalysis([]), null);
  assert.equal(g.pickNewestCompletedAnalysis([analysis("p", "pending", null)]), null);
});

test("pickNewestCompletedAnalysis falls back to created_at", () => {
  const picked = g.pickNewestCompletedAnalysis([
    analysis("a", "completed", null, "2026-01-01T00:00:00Z"),
    analysis("b", "completed", null, "2026-01-05T00:00:00Z"),
  ]);
  assert.equal(picked?.id, "b");
});

const graph = (overrides) => ({
  node_count: 27368,
  edge_count: 35575,
  nodes: [1, 2],
  edges: [1],
  ...overrides,
});

test("graphSummary says when the slice is truncated and keeps the totals", () => {
  const text = g.graphSummary(graph({ scope: "full", truncated: true }));
  assert.match(text, /truncated/);
  assert.match(text, /2 nodes, 1 edges/);
  assert.match(text, /27368 nodes, 35575 edges in the full graph/);
});

test("graphSummary describes an untruncated impact slice and a plain full graph", () => {
  assert.match(g.graphSummary(graph({ scope: "impact", truncated: false })), /changed files/);
  assert.doesNotMatch(g.graphSummary(graph({ scope: "impact" })), /truncated/);
  assert.equal(
    g.graphSummary({ node_count: 2, edge_count: 1, nodes: [1, 2], edges: [1] }),
    "2 nodes, 1 edges.",
  );
});
