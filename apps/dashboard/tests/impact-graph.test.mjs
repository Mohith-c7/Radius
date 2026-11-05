import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildColumns,
  buildImpactModel,
  impactChain,
  isTestPath,
  layoutImpact,
  linkedSet,
} from "../lib/impact-graph.ts";

// util.py <- models.py <- client.py <- tests/test_client.py ; other.py stands alone.
const file = (path) => ({ id: `file:${path}`, node_type: "file", label: path, path });
const nodes = [
  file("pkg/util.py"),
  file("pkg/models.py"),
  file("pkg/client.py"),
  file("pkg/other.py"),
  file("tests/test_client.py"),
  { id: "symbol:pkg/util.py:helper", node_type: "symbol", label: "helper", path: "pkg/util.py" },
];
const dep = (a, b) => ({ source_id: `file:${a}`, target_id: `file:${b}`, edge_type: "depends_on" });
const edges = [
  dep("pkg/models.py", "pkg/util.py"),
  dep("pkg/client.py", "pkg/models.py"),
  dep("tests/test_client.py", "pkg/client.py"),
  { source_id: "file:pkg/util.py", target_id: "symbol:pkg/util.py:helper", edge_type: "contains" },
];
const changed = [{ path: "pkg/util.py", additions: 3, deletions: 1, change_type: "modified" }];

describe("impact graph model", () => {
  it("recognises test files", () => {
    assert.equal(isTestPath("tests/test_client.py"), true);
    assert.equal(isTestPath("src/app.test.ts"), true);
    assert.equal(isTestPath("pkg/util_test.py"), true);
    assert.equal(isTestPath("pkg/contest.py"), false);
  });

  it("walks reverse dependencies from the changed files", () => {
    const m = buildImpactModel(nodes, edges, changed, ["tests/test_client.py"]);
    const get = (p) => m.files.get(`file:${p}`);
    assert.equal(get("pkg/util.py").kind, "changed");
    assert.equal(get("pkg/models.py").depth, 1);
    assert.equal(get("pkg/client.py").depth, 2);
    assert.equal(get("tests/test_client.py").kind, "test");
    assert.equal(get("tests/test_client.py").selectedTest, true);
    assert.equal(get("pkg/other.py").kind, "unaffected");
    assert.deepEqual(get("pkg/util.py").symbols, ["helper"]);
    assert.deepEqual(m.counts, { changed: 1, impacted: 2, tests: 1, selectedTests: 1, unaffected: 1 });
    assert.equal(m.maxDepth, 3);
  });

  it("explains why a file is affected", () => {
    const m = buildImpactModel(nodes, edges, changed, []);
    const chain = impactChain(m, "file:tests/test_client.py").map((id) => m.files.get(id).name);
    assert.deepEqual(chain, ["util.py", "models.py", "client.py", "test_client.py"]);
  });

  it("links a file to everything upstream and downstream of it", () => {
    const m = buildImpactModel(nodes, edges, changed, []);
    const visible = new Set(m.files.keys());
    const linked = linkedSet(m, "file:pkg/models.py", visible);
    assert.equal(linked.has("file:pkg/util.py"), true);
    assert.equal(linked.has("file:tests/test_client.py"), true);
    assert.equal(linked.has("file:pkg/other.py"), false);
  });

  it("hides unaffected files unless asked and lays columns left to right", () => {
    const m = buildImpactModel(nodes, edges, changed, []);
    const cols = buildColumns(m, false, "");
    assert.deepEqual(cols.map((c) => c.key), ["changed", "d1", "d2", "d3", "tests"].filter((k) => cols.some((c) => c.key === k)));
    assert.equal(cols.flatMap((c) => c.files).includes("file:pkg/other.py"), false);
    assert.equal(buildColumns(m, true, "").at(-1).key, "unaffected");

    const layout = layoutImpact(m, cols);
    const x = (p) => layout.files.get(`file:${p}`).x;
    assert.ok(x("pkg/util.py") < x("pkg/models.py"));
    assert.ok(x("pkg/models.py") < x("pkg/client.py"));
    assert.equal(layout.edges.length, 3);
    for (const e of layout.edges) assert.match(e.path, /^M [\d.]+ [\d.]+ C /);
  });

  it("keeps changed files the parser did not see", () => {
    const m = buildImpactModel(nodes, edges, [{ path: "README.md", additions: 1, deletions: 0 }], []);
    assert.equal(m.files.get("changed:README.md").kind, "changed");
  });
});
