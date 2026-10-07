import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { computeGraphLayout } from "../lib/graph-layout.ts";

describe("end-to-end target graph layout verification", () => {
  it("processes multi-language target repository CPG slice and computes interactive SVG layout", () => {
    const targetNodes = [
      { id: "src/auth.py:create_session", node_type: "modified", label: "create_session", path: "src/auth.py" },
      { id: "src/utils.ts:formatToken", node_type: "modified", label: "formatToken", path: "src/utils.ts" },
      { id: "src/api.py:login_handler", node_type: "caller", label: "login_handler", path: "src/api.py" },
      { id: "src/client.ts:authenticateUser", node_type: "caller", label: "authenticateUser", path: "src/client.ts" },
      { id: "tests/test_auth.py", node_type: "test", label: "test_create_session", path: "tests/test_auth.py" },
      { id: "tests/client.test.ts", node_type: "test", label: "client.test", path: "tests/client.test.ts" },
    ];

    const targetEdges = [
      { source_id: "src/auth.py:create_session", target_id: "src/api.py:login_handler", edge_type: "calls" },
      { source_id: "src/utils.ts:formatToken", target_id: "src/client.ts:authenticateUser", edge_type: "calls" },
      { source_id: "src/auth.py:create_session", target_id: "tests/test_auth.py", edge_type: "tested_by" },
      { source_id: "src/client.ts:authenticateUser", target_id: "tests/client.test.ts", edge_type: "tested_by" },
    ];

    const result = computeGraphLayout(targetNodes, targetEdges);

    assert.equal(result.nodes.length, 6);
    assert.equal(result.edges.length, 4);

    // Verify categories
    const pyMod = result.nodes.find((n) => n.id === "src/auth.py:create_session");
    const tsMod = result.nodes.find((n) => n.id === "src/utils.ts:formatToken");
    const pyCaller = result.nodes.find((n) => n.id === "src/api.py:login_handler");
    const tsCaller = result.nodes.find((n) => n.id === "src/client.ts:authenticateUser");
    const pyTest = result.nodes.find((n) => n.id === "tests/test_auth.py");
    const tsTest = result.nodes.find((n) => n.id === "tests/client.test.ts");

    assert.equal(pyMod?.category, "modified");
    assert.equal(tsMod?.category, "modified");
    assert.equal(pyCaller?.category, "caller");
    assert.equal(tsCaller?.category, "caller");
    assert.equal(pyTest?.category, "test");
    assert.equal(tsTest?.category, "test");

    // Modified in layer 0, callers in layer 1, tests in layer 2
    assert.ok(pyMod.x < pyCaller.x);
    assert.ok(pyCaller.x < pyTest.x);
    assert.ok(tsMod.x < tsCaller.x);

    // Verify all 4 edges have valid SVG bezier paths
    for (const edge of result.edges) {
      assert.ok(edge.pathData.startsWith("M "));
      assert.ok(edge.pathData.includes(" C "));
      assert.ok(!edge.pathData.includes("NaN"));
    }
  });
});
