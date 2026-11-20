// Pure helpers for the dependency graph views. The API caps the graph payload
// (`limit`, `truncated`); a whole-repository graph is far larger than a proxy
// will relay, so the dashboard always asks for a bounded slice.

export type GraphScope = "full" | "impact";

export type GraphRequest = { scope?: GraphScope; depth?: number; limit?: number };

/** What the dashboard asks for: the changed files plus one hop, capped. */
export const DASHBOARD_GRAPH_REQUEST: Required<GraphRequest> = {
  scope: "impact",
  depth: 1,
  limit: 1500,
};

/** API path (under /api/v1) of the bounded graph of one analysis. */
export function graphPath(analysisId: string, request: GraphRequest = {}): string {
  const query = new URLSearchParams();
  if (request.scope) query.set("scope", request.scope);
  if (request.depth !== undefined) query.set("depth", String(request.depth));
  if (request.limit !== undefined) query.set("limit", String(request.limit));
  const text = query.toString();
  return `/analyses/${encodeURIComponent(analysisId)}/graph${text ? `?${text}` : ""}`;
}

type AnalysisLike = {
  id: string | null;
  status: string;
  completed_at: string | null;
  created_at: string;
};

/**
 * Newest analysis that finished (status completed) and has an id, or null.
 * Pending and running analyses have no graph yet, so they are never picked.
 */
export function pickNewestCompletedAnalysis<T extends AnalysisLike>(
  analyses: readonly T[],
): T | null {
  let best: T | null = null;
  let bestTime = Number.NEGATIVE_INFINITY;
  for (const analysis of analyses) {
    if (!analysis.id || analysis.status.toLowerCase() !== "completed") continue;
    const time = Date.parse(analysis.completed_at ?? analysis.created_at);
    const key = Number.isNaN(time) ? Number.NEGATIVE_INFINITY : time;
    if (best === null || key > bestTime) {
      best = analysis;
      bestTime = key;
    }
  }
  return best;
}

type GraphLike = {
  node_count: number;
  edge_count: number;
  nodes: readonly unknown[];
  edges: readonly unknown[];
  scope?: string;
  truncated?: boolean;
};

/** One-line description of what slice of the graph is shown. */
export function graphSummary(graph: GraphLike): string {
  const totals = `${graph.node_count} nodes, ${graph.edge_count} edges in the full graph`;
  const shown = `${graph.nodes.length} nodes, ${graph.edges.length} edges`;
  const slice = graph.scope === "impact" ? "changed files and their neighbours" : "graph";
  if (graph.truncated) return `Showing the first ${shown} of the ${slice} (truncated; ${totals}).`;
  if (graph.scope === "impact") return `Showing ${shown} (${slice}; ${totals}).`;
  return `${shown}.`;
}
