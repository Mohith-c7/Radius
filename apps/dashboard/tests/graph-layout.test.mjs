import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { classifyNode, computeGraphLayout } from "../lib/graph-layout.ts";

describe("graph layout engine", () => {
  it("classifies nodes properly into categories", () => {
    assert.equal(classifyNode({ id: "1", node_type: "modified", label: "auth.py", path: "src/auth.py" }), "modified");
    assert.equal(classifyNode({ id: "2", node_type: "test", label: "test_auth", path: "tests/test_auth.py" }), "test");
    assert.equal(classifyNode({ id: "3", node_type: "function", label: "verify_token", path: "src/auth.py" }), "caller");
    assert.equal(classifyNode({ id: "4", node_type: "pruned", label: "internal_helper", path: "src/helper.py" }), "pruned");
    assert.equal(classifyNode({ id: "5", node_type: "module", label: "config", path: "src/config.py" }), "module");
  });

  it("computes layered layout with valid bounding dimensions and svg path data", () => {
    const nodes = [
      { id: "mod1", node_type: "modified", label: "validate_user", path: "src/user.py" },
      { id: "caller1", node_type: "function", label: "login_route", path: "src/routes.py" },
      { id: "test1", node_type: "test", label: "test_login", path: "tests/test_login.py" },
    ];
    const edges = [
      { source_id: "mod1", target_id: "caller1", edge_type: "calls" },
      { source_id: "caller1", target_id: "test1", edge_type: "tests" },
    ];

    const result = computeGraphLayout(nodes, edges);
    assert.equal(result.nodes.length, 3);
    assert.equal(result.edges.length, 2);

    // Layer 0 is modified, Layer 1 is caller, Layer 2 is test
    const modNode = result.nodes.find((n) => n.id === "mod1");
    const callerNode = result.nodes.find((n) => n.id === "caller1");
    const testNode = result.nodes.find((n) => n.id === "test1");

    assert.ok(modNode && callerNode && testNode);
    assert.ok(modNode.x < callerNode.x);
    assert.ok(callerNode.x < testNode.x);

    // Edges have valid SVG path data
    assert.ok(result.edges[0].pathData.startsWith("M "));
    assert.ok(result.edges[0].pathData.includes(" C "));
    assert.ok(result.width >= 600);
    assert.ok(result.height >= 400);
  });

  it("handles empty nodes gracefully", () => {
    const result = computeGraphLayout([], []);
    assert.equal(result.nodes.length, 0);
    assert.equal(result.edges.length, 0);
    assert.equal(result.width, 600);
    assert.equal(result.height, 400);
  });
});
