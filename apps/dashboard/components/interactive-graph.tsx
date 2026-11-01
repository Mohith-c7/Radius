"use client";

import { useMemo, useRef, useState, MouseEvent as ReactMouseEvent } from "react";
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Search,
  X,
  FileCode,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { GraphEdge, GraphNode } from "../lib/api";
import {
  computeGraphLayout,
  NodeCategory,
} from "../lib/graph-layout";


type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  title?: string;
  subtitle?: string;
  height?: number;
};

export function InteractiveGraphViewer({
  nodes,
  edges,
  title = "CPG Slice & Dependency Graph",
  subtitle,
  height = 560,
}: Props) {
  const [filter, setFilter] = useState<"all" | NodeCategory>("all");
  const [search, setSearch] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Pan & Zoom
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });

  const layout = useMemo(() => {
    return computeGraphLayout(nodes, edges);
  }, [nodes, edges]);

  // Counts for filter pills
  const counts = useMemo(() => {
    const map = { all: nodes.length, modified: 0, caller: 0, test: 0, pruned: 0, module: 0 };
    for (const n of layout.nodes) {
      if (n.category in map) {
        map[n.category]++;
      }
    }
    return map;
  }, [nodes, layout.nodes]);

  // Filtered nodes
  const filteredNodeIds = useMemo(() => {
    const q = search.trim().toLowerCase();
    const ids = new Set<string>();
    for (const n of layout.nodes) {
      const matchesCategory = filter === "all" || n.category === filter;
      const matchesSearch =
        !q ||
        n.label.toLowerCase().includes(q) ||
        (n.path && n.path.toLowerCase().includes(q));
      if (matchesCategory && matchesSearch) {
        ids.add(n.id);
      }
    }
    return ids;
  }, [layout.nodes, filter, search]);

  const activeFocusId = selectedNodeId || hoveredNodeId;

  // Connected node IDs & edges for highlighting
  const { connectedNodeIds, highlightedEdgeKeys } = useMemo(() => {
    const nodeIds = new Set<string>();
    const edgeKeys = new Set<string>();
    if (!activeFocusId) return { connectedNodeIds: nodeIds, highlightedEdgeKeys: edgeKeys };

    nodeIds.add(activeFocusId);
    for (const e of edges) {
      if (e.source_id === activeFocusId) {
        nodeIds.add(e.target_id);
        edgeKeys.add(`${e.source_id}->${e.target_id}`);
      } else if (e.target_id === activeFocusId) {
        nodeIds.add(e.source_id);
        edgeKeys.add(`${e.source_id}->${e.target_id}`);
      }
    }
    return { connectedNodeIds: nodeIds, highlightedEdgeKeys: edgeKeys };
  }, [activeFocusId, edges]);

  const selectedNode = useMemo(() => {
    return layout.nodes.find((n) => n.id === selectedNodeId) || null;
  }, [layout.nodes, selectedNodeId]);

  // Handlers for dragging canvas
  const handleMouseDown = (e: ReactMouseEvent) => {
    if ((e.target as HTMLElement).closest(".graph-node-group")) return;
    setIsDragging(true);
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: ReactMouseEvent) => {
    if (!isDragging) return;
    setPan({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y,
    });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const zoomIn = () => setZoom((z) => Math.min(Number((z + 0.15).toFixed(2)), 2.5));
  const zoomOut = () => setZoom((z) => Math.max(Number((z - 0.15).toFixed(2)), 0.4));
  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedNodeId(null);
  };

  const getCategoryStyles = (category: NodeCategory) => {
    switch (category) {
      case "modified":
        return { stroke: "#DC8C6D", fill: "#FFF7F4", dot: "#DC8C6D", text: "#9E3C18", badge: "MODIFIED" };
      case "test":
        return { stroke: "#19815C", fill: "#E7F5EE", dot: "#19815C", text: "#167455", badge: "TEST" };
      case "pruned":
        return { stroke: "#70807A", fill: "#F4F6F5", dot: "#70807A", text: "#52605B", badge: "PRUNED" };
      case "caller":
        return { stroke: "#2D6FCA", fill: "#EAF2FF", dot: "#2D6FCA", text: "#1D529B", badge: "CALLER" };
      default:
        return { stroke: "#9CCFB7", fill: "#FFFFFF", dot: "#19815C", text: "#17211E", badge: "MODULE" };
    }
  };

  return (
    <div className="graph-container">
      {/* Header & Controls Toolbar */}
      <div className="graph-toolbar">
        <div>
          <h2 style={{ fontSize: "15px", margin: "0 0 2px" }}>{title}</h2>
          {subtitle && <p className="muted" style={{ fontSize: "12px", margin: 0 }}>{subtitle}</p>}
        </div>

        {/* Filter Pills */}
        <div className="graph-filters">
          <button
            type="button"
            className={`graph-filter-chip ${filter === "all" ? "active" : ""}`}
            onClick={() => setFilter("all")}
          >
            All ({counts.all})
          </button>
          {counts.modified > 0 && (
            <button
              type="button"
              className={`graph-filter-chip ${filter === "modified" ? "active" : ""}`}
              onClick={() => setFilter("modified")}
            >
              <span style={{ color: "#DC8C6D" }}>●</span> Modified ({counts.modified})
            </button>
          )}
          {counts.caller > 0 && (
            <button
              type="button"
              className={`graph-filter-chip ${filter === "caller" ? "active" : ""}`}
              onClick={() => setFilter("caller")}
            >
              <span style={{ color: "#2D6FCA" }}>●</span> Callers ({counts.caller})
            </button>
          )}
          {counts.test > 0 && (
            <button
              type="button"
              className={`graph-filter-chip ${filter === "test" ? "active" : ""}`}
              onClick={() => setFilter("test")}
            >
              <span style={{ color: "#19815C" }}>●</span> Tests ({counts.test})
            </button>
          )}
          {counts.pruned > 0 && (
            <button
              type="button"
              className={`graph-filter-chip ${filter === "pruned" ? "active" : ""}`}
              onClick={() => setFilter("pruned")}
            >
              <span style={{ color: "#70807A" }}>●</span> Pruned ({counts.pruned})
            </button>
          )}
        </div>

        {/* Search & Zoom Actions */}
        <div className="graph-controls">
          <div style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
            <Search size={13} style={{ position: "absolute", left: "8px", color: "var(--muted)" }} />
            <input
              type="text"
              placeholder="Find symbol..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                padding: "5px 8px 5px 26px",
                fontSize: "11px",
                borderRadius: "6px",
                border: "1px solid var(--line)",
                background: "#fff",
                width: "120px",
              }}
            />
          </div>
          <button type="button" className="graph-btn" onClick={zoomIn} title="Zoom in">
            <ZoomIn size={14} />
          </button>
          <button type="button" className="graph-btn" onClick={zoomOut} title="Zoom out">
            <ZoomOut size={14} />
          </button>
          <button type="button" className="graph-btn" onClick={resetView} title="Reset view">
            <RotateCcw size={14} />
            <span style={{ marginLeft: "4px", fontSize: "11px" }}>{Math.round(zoom * 100)}%</span>
          </button>
        </div>
      </div>

      {/* SVG Canvas Area */}
      <div
        className="graph-svg-wrapper"
        style={{ height: `${height}px` }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <svg
          width="100%"
          height="100%"
          style={{ overflow: "hidden" }}
        >
          <defs>
            <marker
              id="graph-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#9CCFB7" />
            </marker>
            <marker
              id="graph-arrow-active"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 9 5 L 0 9 z" fill="#19815C" />
            </marker>
          </defs>

          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Render Edges */}
            {layout.edges.map((edge) => {
              const edgeKey = `${edge.source_id}->${edge.target_id}`;
              const isEdgeHighlighted = highlightedEdgeKeys.has(edgeKey);
              const isDimmed =
                activeFocusId && !isEdgeHighlighted;
              const isVisible =
                filteredNodeIds.has(edge.source_id) && filteredNodeIds.has(edge.target_id);

              if (!isVisible) return null;

              return (
                <path
                  key={edgeKey}
                  d={edge.pathData}
                  className={`graph-edge-path ${isEdgeHighlighted ? "highlighted" : ""}`}
                  style={{
                    opacity: isDimmed ? 0.2 : 1,
                  }}
                  markerEnd={isEdgeHighlighted ? "url(#graph-arrow-active)" : "url(#graph-arrow)"}
                />
              );
            })}

            {/* Render Nodes */}
            {layout.nodes.map((node) => {
              const styles = getCategoryStyles(node.category);
              const isSelected = selectedNodeId === node.id;
              const isHovered = hoveredNodeId === node.id;
              const isConnected = connectedNodeIds.has(node.id);
              const isDimmed = activeFocusId && !isConnected;
              const isVisible = filteredNodeIds.has(node.id);

              if (!isVisible) return null;

              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x}, ${node.y})`}
                  className={`graph-node-group ${isSelected ? "selected" : ""} ${isDimmed ? "dimmed" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedNodeId(isSelected ? null : node.id);
                  }}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                >
                  <rect
                    className="node-bg"
                    width={node.width}
                    height={node.height}
                    rx="8"
                    ry="8"
                    fill={styles.fill}
                    stroke={isSelected || isHovered ? styles.text : styles.stroke}
                    strokeWidth={isSelected ? "2.5" : "1.2"}
                  />
                  {/* Category Indicator Dot */}
                  <circle cx="16" cy="20" r="5" fill={styles.dot} />
                  
                  {/* Node Title */}
                  <text
                    x="28"
                    y="24"
                    fill="var(--ink)"
                    fontSize="11"
                    fontWeight="700"
                    fontFamily="'DM Mono', monospace"
                  >
                    {node.label.length > 20 ? `${node.label.slice(0, 19)}…` : node.label}
                  </text>

                  {/* Subtext: Path or Category Badge */}
                  <text
                    x="28"
                    y="42"
                    fill="var(--muted)"
                    fontSize="9.5"
                    fontFamily="Manrope, sans-serif"
                  >
                    {node.path
                      ? (node.path.length > 24 ? `…${node.path.slice(-22)}` : node.path)
                      : styles.badge}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* Node Detail Slide-Over Drawer */}
        {selectedNode && (
          <aside className="graph-drawer">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
              <div>
                <span
                  className="status"
                  style={{
                    fontSize: "10px",
                    padding: "3px 8px",
                    fontWeight: 700,
                    marginBottom: "6px",
                    display: "inline-flex",
                    background: getCategoryStyles(selectedNode.category).fill,
                    color: getCategoryStyles(selectedNode.category).text,
                    border: `1px solid ${getCategoryStyles(selectedNode.category).stroke}`,
                  }}
                >
                  {getCategoryStyles(selectedNode.category).badge}
                </span>
                <h3 style={{ fontSize: "15px", margin: "6px 0 2px", wordBreak: "break-all" }}>
                  {selectedNode.label}
                </h3>
                <p className="muted" style={{ fontSize: "11px", margin: 0 }}>
                  ID: <code style={{ fontSize: "10px" }}>{selectedNode.id}</code>
                </p>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setSelectedNodeId(null)}
                style={{ width: "28px", height: "28px", padding: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
              >
                <X size={14} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "14px" }}>
              {selectedNode.path && (
                <div style={{ background: "#FAFCFA", border: "1px solid var(--line)", borderRadius: "8px", padding: "10px 12px" }}>
                  <span className="muted" style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase" }}>
                    File Location
                  </span>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    <FileCode size={13} color="var(--green)" />
                    <code style={{ fontSize: "11px", wordBreak: "break-all" }}>{selectedNode.path}</code>
                  </div>
                </div>
              )}

              {/* Callers (Inbound) */}
              <div>
                <span className="muted" style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase" }}>
                  Incoming References ({edges.filter((e) => e.target_id === selectedNode.id).length})
                </span>
                <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                  {edges
                    .filter((e) => e.target_id === selectedNode.id)
                    .map((e) => {
                      const src = layout.nodes.find((n) => n.id === e.source_id);
                      return (
                        <button
                          type="button"
                          key={`in-${e.source_id}`}
                          onClick={() => setSelectedNodeId(e.source_id)}
                          style={{
                            background: "#F8FAF8",
                            border: "1px solid var(--line)",
                            borderRadius: "6px",
                            padding: "6px 8px",
                            fontSize: "11px",
                            textAlign: "left",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                          }}
                        >
                          <span>{src?.label || e.source_id}</span>
                          <span className="muted" style={{ fontSize: "9px" }}>{e.edge_type}</span>
                        </button>
                      );
                    })}
                  {edges.filter((e) => e.target_id === selectedNode.id).length === 0 && (
                    <small className="muted" style={{ fontSize: "11px" }}>No inbound references in this slice.</small>
                  )}
                </div>
              </div>

              {/* Dependencies (Outbound) */}
              <div>
                <span className="muted" style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase" }}>
                  Outgoing Targets ({edges.filter((e) => e.source_id === selectedNode.id).length})
                </span>
                <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                  {edges
                    .filter((e) => e.source_id === selectedNode.id)
                    .map((e) => {
                      const tgt = layout.nodes.find((n) => n.id === e.target_id);
                      return (
                        <button
                          type="button"
                          key={`out-${e.target_id}`}
                          onClick={() => setSelectedNodeId(e.target_id)}
                          style={{
                            background: "#F8FAF8",
                            border: "1px solid var(--line)",
                            borderRadius: "6px",
                            padding: "6px 8px",
                            fontSize: "11px",
                            textAlign: "left",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                          }}
                        >
                          <span>{tgt?.label || e.target_id}</span>
                          <span className="muted" style={{ fontSize: "9px" }}>{e.edge_type}</span>
                        </button>
                      );
                    })}
                  {edges.filter((e) => e.source_id === selectedNode.id).length === 0 && (
                    <small className="muted" style={{ fontSize: "11px" }}>Terminal leaf node.</small>
                  )}
                </div>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export type AiPruningItem = {
  symbol: string;
  file: string;
  decision: "pruned" | "retained";
  reason: string;
};

export function AiPruningInsightsCard({
  items,
}: {
  items?: AiPruningItem[];
}) {
  // No fabricated sample data: render nothing unless real pruning results exist.
  if (!items || items.length === 0) return null;
  const displayItems = items;
  const prunedCount = displayItems.filter((i) => i.decision === "pruned").length;
  const percentSaved = displayItems.length > 0 ? Math.round((prunedCount / displayItems.length) * 100) : 0;

  return (
    <section className="card" style={{ padding: "20px", marginTop: "24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Sparkles size={16} color="var(--green)" />
            <h2 style={{ fontSize: "15px", margin: 0 }}>AI Impact Pruning Insights</h2>
          </div>
          <p className="muted" style={{ fontSize: "12px", marginTop: "4px" }}>
            Semantic evaluation by Gemini 2.0 Flash separating benign diffs from true behavioral changes.
          </p>
        </div>
        <span
          className="savings-pill"
          style={{ fontSize: "11px", padding: "4px 10px" }}
        >
          <ShieldCheck size={13} />
          {prunedCount} Callers Pruned ({percentSaved}% Noise Reduction)
        </span>
      </div>

      <div className="ai-pruning-grid">
        {displayItems.map((item, idx) => (
          <div
            key={`${item.symbol}-${idx}`}
            className={`ai-reasoning-card ${item.decision}`}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <code style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink)" }}>{item.symbol}</code>
              <span
                className="status"
                style={{
                  fontSize: "10px",
                  padding: "2px 7px",
                  fontWeight: 700,
                  background: item.decision === "pruned" ? "#E7F5EE" : "#EAF2FF",
                  color: item.decision === "pruned" ? "#167455" : "#1D529B",
                }}
              >
                {item.decision === "pruned" ? "PRUNED (BENIGN)" : "RETAINED"}
              </span>
            </div>
            <p className="muted" style={{ fontSize: "11px", marginBottom: "8px" }}>
              <FileCode size={11} style={{ display: "inline", marginRight: "4px" }} />
              {item.file}
            </p>
            <p style={{ fontSize: "11.5px", margin: 0, color: "#37474F", lineHeight: 1.5 }}>
              {item.reason}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
