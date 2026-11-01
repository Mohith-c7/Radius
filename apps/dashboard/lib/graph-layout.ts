import type { GraphEdge, GraphNode } from "./api";

export type NodeCategory = "modified" | "caller" | "test" | "module" | "pruned";

export type PositionedNode = GraphNode & {
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
  category: NodeCategory;
};

export type PositionedEdge = GraphEdge & {
  pathData: string;
};

export type GraphLayoutResult = {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
};

export function classifyNode(node: GraphNode): NodeCategory {
  const typeLower = (node.node_type || "").toLowerCase();
  const labelLower = (node.label || "").toLowerCase();
  const pathLower = (node.path || "").toLowerCase();

  if (typeLower === "modified" || typeLower === "diff_entrypoint") {
    return "modified";
  }
  if (typeLower === "pruned" || typeLower === "benign") {
    return "pruned";
  }
  if (
    typeLower === "test" ||
    typeLower === "testcase" ||
    labelLower.startsWith("test_") ||
    pathLower.includes("test")
  ) {
    return "test";
  }
  if (typeLower === "caller" || typeLower === "function" || typeLower === "method") {
    return "caller";
  }
  return "module";
}

export function computeGraphLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options?: { nodeWidth?: number; nodeHeight?: number; colSpacing?: number; rowSpacing?: number }
): GraphLayoutResult {
  const nodeWidth = options?.nodeWidth ?? 200;
  const nodeHeight = options?.nodeHeight ?? 56;
  const colSpacing = options?.colSpacing ?? 260;
  const rowSpacing = options?.rowSpacing ?? 80;

  if (nodes.length === 0) {
    return { nodes: [], edges: [], width: 600, height: 400 };
  }

  const nodeMap = new Map<string, GraphNode>();
  for (const n of nodes) {
    nodeMap.set(n.id, n);
  }

  // Build adjacency
  const inDegree = new Map<string, number>();
  const outEdges = new Map<string, string[]>();

  for (const n of nodes) {
    inDegree.set(n.id, 0);
    outEdges.set(n.id, []);
  }

  for (const e of edges) {
    if (nodeMap.has(e.source_id) && nodeMap.has(e.target_id)) {
      outEdges.get(e.source_id)?.push(e.target_id);
      inDegree.set(e.target_id, (inDegree.get(e.target_id) ?? 0) + 1);
    }
  }

  // Layer assignment
  const layerMap = new Map<string, number>();
  for (const n of nodes) {
    const category = classifyNode(n);
    if (category === "modified") {
      layerMap.set(n.id, 0);
    } else if (category === "test") {
      layerMap.set(n.id, 2);
    } else {
      layerMap.set(n.id, 1);
    }
  }

  // Group by layer
  const layers = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const layer = layerMap.get(n.id) ?? 1;
    if (!layers.has(layer)) {
      layers.set(layer, []);
    }
    layers.get(layer)?.push(n);
  }

  const sortedLayerKeys = Array.from(layers.keys()).sort((a, b) => a - b);
  const positionedNodes: PositionedNode[] = [];
  const posMap = new Map<string, PositionedNode>();

  const paddingLeft = 40;
  const paddingTop = 40;
  let maxCol = 0;
  let maxRow = 0;

  sortedLayerKeys.forEach((layerKey, colIndex) => {
    const colNodes = layers.get(layerKey) || [];
    maxCol = Math.max(maxCol, colIndex);
    colNodes.forEach((node, rowIndex) => {
      maxRow = Math.max(maxRow, rowIndex);
      const x = paddingLeft + colIndex * colSpacing;
      const y = paddingTop + rowIndex * rowSpacing;
      const posNode: PositionedNode = {
        ...node,
        x,
        y,
        width: nodeWidth,
        height: nodeHeight,
        layer: layerKey,
        category: classifyNode(node),
      };
      positionedNodes.push(posNode);
      posMap.set(node.id, posNode);
    });
  });

  // Calculate edge Bezier paths
  const positionedEdges: PositionedEdge[] = [];
  for (const e of edges) {
    const src = posMap.get(e.source_id);
    const tgt = posMap.get(e.target_id);
    if (src && tgt) {
      const sx = src.x + src.width;
      const sy = src.y + src.height / 2;
      const tx = tgt.x;
      const ty = tgt.y + tgt.height / 2;
      const dx = Math.abs(tx - sx);
      const cx1 = sx + Math.max(dx * 0.4, 40);
      const cy1 = sy;
      const cx2 = tx - Math.max(dx * 0.4, 40);
      const cy2 = ty;
      const pathData = `M ${sx} ${sy} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${tx} ${ty}`;

      positionedEdges.push({
        ...e,
        pathData,
      });
    }
  }

  const totalWidth = paddingLeft * 2 + (maxCol + 1) * colSpacing;
  const totalHeight = paddingTop * 2 + (maxRow + 1) * rowSpacing;

  return {
    nodes: positionedNodes,
    edges: positionedEdges,
    width: Math.max(totalWidth, 600),
    height: Math.max(totalHeight, 400),
  };
}
