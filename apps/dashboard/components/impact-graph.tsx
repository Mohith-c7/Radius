"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type WheelEvent as ReactWheelEvent } from "react";
import { ArrowRight, Eye, EyeOff, FileCode, Maximize2, Search, X, ZoomIn, ZoomOut } from "lucide-react";
import type { ChangedFile, GraphEdge, GraphNode } from "../lib/api";
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  buildColumns,
  buildImpactModel,
  impactChain,
  layoutImpact,
  linkedSet,
  type ImpactFile,
  type ImpactKind,
} from "../lib/impact-graph";

const PANEL_WIDTH = 330;

const KIND_STYLE: Record<ImpactKind, { stroke: string; fill: string; accent: string; label: string }> = {
  changed: { stroke: "#DC8C6D", fill: "#FFF4EF", accent: "#C2603A", label: "Changed" },
  impacted: { stroke: "#2D6FCA", fill: "#EEF4FF", accent: "#1D529B", label: "Affected" },
  test: { stroke: "#19815C", fill: "#E9F6EF", accent: "#146B4C", label: "Test" },
  unaffected: { stroke: "#C9D3CE", fill: "#FAFBFA", accent: "#70807A", label: "Not affected" },
};

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  changedFiles: ChangedFile[];
  selectedTestPaths: string[];
  height?: number;
};

export function ImpactGraph({ nodes, edges, changedFiles, selectedTestPaths, height = 640 }: Props) {
  const model = useMemo(
    () => buildImpactModel(nodes, edges, changedFiles, selectedTestPaths),
    [nodes, edges, changedFiles, selectedTestPaths],
  );
  const [showUnaffected, setShowUnaffected] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);

  const columns = useMemo(() => buildColumns(model, showUnaffected, query), [model, showUnaffected, query]);
  const layout = useMemo(() => layoutImpact(model, columns), [model, columns]);
  const visible = useMemo(() => new Set(layout.files.keys()), [layout]);

  const focusId = hoverId ?? selectedId;
  const linked = useMemo(
    () => (focusId && visible.has(focusId) ? linkedSet(model, focusId, visible) : null),
    [focusId, model, visible],
  );
  const chain = useMemo(() => (selectedId ? impactChain(model, selectedId) : []), [model, selectedId]);
  const chainEdges = useMemo(() => {
    const keys = new Set<string>();
    for (let i = 1; i < chain.length; i++) keys.add(`${chain[i - 1]}->${chain[i]}`);
    return keys;
  }, [chain]);

  // ---- pan & zoom -------------------------------------------------------
  const viewportRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [viewportWidth, setViewportWidth] = useState(0);
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewportWidth(el.clientWidth));
    ro.observe(el);
    setViewportWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const fitScale = viewportWidth ? Math.max(0.35, Math.min(1, (viewportWidth - 24) / layout.width)) : 1;
  const canvasHeight = Math.round(Math.min(height, Math.max(380, layout.height * fitScale + 28)));
  const drag = useRef<{ x: number; y: number } | null>(null);

  const fit = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const k = Math.max(0.35, Math.min(1, (el.clientWidth - 24) / layout.width, (canvasHeight - 24) / layout.height));
    setView({ k, x: (el.clientWidth - layout.width * k) / 2, y: 12 });
  }, [layout.width, layout.height, canvasHeight]);

  useEffect(() => {
    if (!selectedId) fit();
    // Refit only when the graph or the canvas changes, not on every selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fit]);

  const zoomBy = (factor: number, cx?: number, cy?: number) => {
    const el = viewportRef.current;
    const px = cx ?? (el ? el.clientWidth / 2 : 0);
    const py = cy ?? (el ? el.clientHeight / 2 : 0);
    setView((v) => {
      const k = Math.min(2.2, Math.max(0.3, v.k * factor));
      return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
    });
  };
  const onWheel = (e: ReactWheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && Math.abs(e.deltaY) < 40) {
      setView((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
      return;
    }
    const rect = viewportRef.current!.getBoundingClientRect();
    zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - rect.left, e.clientY - rect.top);
  };
  const onDown = (e: ReactMouseEvent) => {
    if ((e.target as Element).closest("[data-file]")) return;
    drag.current = { x: e.clientX - view.x, y: e.clientY - view.y };
  };
  const onMove = (e: ReactMouseEvent) => {
    if (!drag.current) return;
    setView((v) => ({ ...v, x: e.clientX - drag.current!.x, y: e.clientY - drag.current!.y }));
  };
  const onUp = () => {
    drag.current = null;
  };

  const select = (id: string | null) => {
    setSelectedId(id);
    if (!id) return;
    if (!visible.has(id) && model.files.get(id)?.kind === "unaffected") setShowUnaffected(true);
    // Fit the file and its impact chain into the area left of the details panel.
    const el = viewportRef.current;
    const placed = impactChain(model, id).map((c) => layout.files.get(c)).filter(Boolean) as Array<{ x: number; y: number }>;
    if (!el || placed.length === 0) return;
    const minX = Math.min(...placed.map((f) => f.x)) - 30;
    const maxX = Math.max(...placed.map((f) => f.x)) + NODE_WIDTH + 30;
    const minY = Math.min(...placed.map((f) => f.y)) - 30;
    const maxY = Math.max(...placed.map((f) => f.y)) + NODE_HEIGHT + 30;
    const availW = Math.max(240, el.clientWidth - (selectedId ? 0 : PANEL_WIDTH));
    const availH = el.clientHeight;
    setView((v) => {
      const k = Math.max(0.3, Math.min(v.k < 0.9 ? 0.9 : v.k, availW / (maxX - minX), availH / (maxY - minY)));
      return { k, x: (availW - (maxX - minX) * k) / 2 - minX * k, y: (availH - (maxY - minY) * k) / 2 - minY * k };
    });
  };

  const selected = selectedId ? model.files.get(selectedId) ?? null : null;
  const dimmed = (id: string) => linked !== null && !linked.has(id);

  if (!model.hasFileGraph && changedFiles.length === 0) {
    return null;
  }

  return (
    <section className="card impact-graph">
      <header className="impact-head">
        <div>
          <h2>Impact map</h2>
          <p className="muted">
            How this pull request spreads through the code: from the changed files, along imports, to the
            tests that cover them. Hover a file to see everything linked to it; click it to see why it is affected.
          </p>
        </div>
        <dl className="impact-stats">
          <div><dt>Changed</dt><dd style={{ color: KIND_STYLE.changed.accent }}>{model.counts.changed}</dd></div>
          <div><dt>Affected files</dt><dd style={{ color: KIND_STYLE.impacted.accent }}>{model.counts.impacted}</dd></div>
          <div><dt>Tests selected</dt><dd style={{ color: KIND_STYLE.test.accent }}>{model.counts.selectedTests}</dd></div>
          <div><dt>Furthest reach</dt><dd>{model.maxDepth} {model.maxDepth === 1 ? "hop" : "hops"}</dd></div>
        </dl>
      </header>

      <div className="impact-toolbar">
        <label className="impact-search">
          <Search size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter files..." />
        </label>
        <button className="impact-btn" type="button" onClick={() => setShowUnaffected((s) => !s)}>
          {showUnaffected ? <EyeOff size={14} /> : <Eye size={14} />}
          {showUnaffected ? "Hide" : "Show"} unaffected files ({model.counts.unaffected})
        </button>
        <span className="impact-legend">
          {(["changed", "impacted", "test"] as ImpactKind[]).map((k) => (
            <span key={k}><i style={{ background: KIND_STYLE[k].stroke }} />{KIND_STYLE[k].label}</span>
          ))}
          <span><i className="impact-legend-line" />imports (impact flows →)</span>
        </span>
        <span className="impact-zoom">
          <button className="impact-btn icon" type="button" onClick={() => zoomBy(1 / 1.2)} aria-label="Zoom out"><ZoomOut size={14} /></button>
          <span>{Math.round(view.k * 100)}%</span>
          <button className="impact-btn icon" type="button" onClick={() => zoomBy(1.2)} aria-label="Zoom in"><ZoomIn size={14} /></button>
          <button className="impact-btn icon" type="button" onClick={fit} aria-label="Fit to screen"><Maximize2 size={14} /></button>
        </span>
      </div>

      <div className="impact-body">
        <div
          ref={viewportRef}
          className="impact-viewport"
          style={{ height: canvasHeight }}
          onWheel={onWheel}
          onMouseDown={onDown}
          onMouseMove={onMove}
          onMouseUp={onUp}
          onMouseLeave={onUp}
          onClick={(e) => {
            if (!(e.target as Element).closest("[data-file]")) setSelectedId(null);
          }}
        >
          <svg width="100%" height="100%">
            <defs>
              <marker id="impact-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#9FB3AA" />
              </marker>
              <marker id="impact-arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#C2603A" />
              </marker>
            </defs>
            <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
              {layout.columns.map((c) => (
                <g key={c.key}>
                  <rect x={c.x - 10} y={8} width={c.width + 20} height={layout.height - 16} rx={12} className="impact-col-bg" />
                  <text x={c.x} y={30} className="impact-col-title">{c.title}</text>
                  <text x={c.x} y={46} className="impact-col-hint">{c.files.length} {c.files.length === 1 ? "file" : "files"} · {c.hint}</text>
                </g>
              ))}

              {layout.edges.map((e) => {
                const hot = chainEdges.has(e.key);
                const lit = linked ? linked.has(e.from) && linked.has(e.to) : false;
                const faded = linked !== null && !lit;
                return (
                  <path
                    key={e.key}
                    d={e.path}
                    fill="none"
                    stroke={hot ? "#C2603A" : lit ? "#5E8F7A" : "#B7C7BF"}
                    strokeWidth={hot ? 2.6 : lit ? 1.8 : 1.1}
                    strokeOpacity={faded ? 0.12 : hot || lit ? 0.95 : 0.55}
                    markerEnd={e.reversed ? undefined : hot ? "url(#impact-arrow-hot)" : "url(#impact-arrow)"}
                    markerStart={e.reversed ? (hot ? "url(#impact-arrow-hot)" : "url(#impact-arrow)") : undefined}
                  />
                );
              })}

              {[...layout.files.values()].map((f) => {
                const s = KIND_STYLE[f.kind];
                const isSel = f.id === selectedId;
                const inChain = chain.includes(f.id);
                return (
                  <g
                    key={f.id}
                    data-file={f.id}
                    transform={`translate(${f.x} ${f.y})`}
                    style={{ cursor: "pointer", opacity: dimmed(f.id) ? 0.22 : 1, transition: "opacity 120ms" }}
                    onMouseEnter={() => setHoverId(f.id)}
                    onMouseLeave={() => setHoverId(null)}
                    onClick={(e) => {
                      e.stopPropagation();
                      select(isSel ? null : f.id);
                    }}
                  >
                    <title>{f.path}</title>
                    <rect
                      width={NODE_WIDTH}
                      height={NODE_HEIGHT}
                      rx={9}
                      fill={s.fill}
                      stroke={isSel || inChain ? s.accent : s.stroke}
                      strokeWidth={isSel ? 2.6 : inChain ? 2 : 1.2}
                    />
                    <rect width={5} height={NODE_HEIGHT} rx={2.5} fill={s.stroke} />
                    <text x={14} y={21} className="impact-node-name">
                      {truncate(f.name, f.kind === "changed" ? 17 : f.selectedTest ? 24 : f.symbols.length ? 21 : 27)}
                    </text>
                    <text x={14} y={37} className="impact-node-dir">{truncate(f.dir || "/", 32)}</text>
                    {f.kind === "changed" && (f.additions !== undefined || f.deletions !== undefined) ? (
                      <text x={NODE_WIDTH - 10} y={21} textAnchor="end" className="impact-node-badge">
                        <tspan fill="#19815C">+{f.additions ?? 0}</tspan> <tspan fill="#C2603A">−{f.deletions ?? 0}</tspan>
                      </text>
                    ) : f.selectedTest ? (
                      <g transform={`translate(${NODE_WIDTH - 16} 17)`}>
                        <title>Selected to run</title>
                        <circle r={7} fill="#19815C" />
                        <path d="M -3.2 0.2 L -1 2.4 L 3.2 -2" stroke="#fff" strokeWidth={1.7} fill="none" strokeLinecap="round" strokeLinejoin="round" />
                      </g>
                    ) : f.symbols.length ? (
                      <text x={NODE_WIDTH - 10} y={21} textAnchor="end" className="impact-node-badge" fill="#70807A">{f.symbols.length} sym</text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          </svg>
          {model.hasImportLinks && model.counts.impacted === 0 && (
            <p className="impact-note">
              <strong>Contained change.</strong> No other file in the repository imports the changed files, so the
              change stays local.
            </p>
          )}
          {!model.hasImportLinks && (
            <p className="impact-note">
              <strong>Only the changed files are shown.</strong> Radius found no file-to-file imports in this
              repository{model.counts.selectedTests === 0 ? " and matched no tests" : ""}. Imports are resolved to
              files for Python and TypeScript/JavaScript; for other languages (Go, Java, Rust) the ripple beyond the
              changed files is not traced yet.
            </p>
          )}
        </div>

        {selected && (
          <FileDetails
            file={selected}
            chain={chain.map((id) => model.files.get(id)!).filter(Boolean)}
            lookup={(id) => model.files.get(id)}
            onSelect={select}
            onClose={() => setSelectedId(null)}
            height={canvasHeight}
          />
        )}
      </div>
    </section>
  );
}

function FileDetails({
  file,
  chain,
  lookup,
  onSelect,
  onClose,
  height,
}: {
  height: number;
  file: ImpactFile;
  chain: ImpactFile[];
  lookup: (id: string) => ImpactFile | undefined;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const [allSymbols, setAllSymbols] = useState(false);
  useEffect(() => setAllSymbols(false), [file.id]);
  const s = KIND_STYLE[file.kind];
  const status =
    file.kind === "changed"
      ? `Changed in this PR${file.additions !== undefined ? ` (+${file.additions} −${file.deletions ?? 0})` : ""}`
      : file.depth !== null
        ? `${file.isTest ? "Test, " : ""}affected ${file.depth} ${file.depth === 1 ? "hop" : "hops"} from the change`
        : file.selectedTest
          ? "Selected test (matched by test mapping)"
          : "Not reached from the changed files";
  const symbols = allSymbols ? file.symbols : file.symbols.slice(0, 12);

  return (
    <aside className="impact-details" style={{ height }}>
      <div className="impact-details-head">
        <span className="impact-kind" style={{ color: s.accent, borderColor: s.stroke, background: s.fill }}>{s.label}</span>
        <button className="impact-btn icon" type="button" onClick={onClose} aria-label="Close details"><X size={14} /></button>
      </div>
      <h3>{file.name}</h3>
      <p className="impact-path"><FileCode size={12} /> {file.path}</p>
      <p className="impact-status">{status}{file.selectedTest && file.kind !== "changed" ? " · selected to run" : ""}</p>

      {chain.length > 1 && (
        <div className="impact-section">
          <h4>Why it is affected</h4>
          <ol className="impact-chain">
            {chain.map((f, i) => (
              <li key={f.id}>
                <button type="button" onClick={() => onSelect(f.id)} className={f.id === file.id ? "current" : ""}>
                  {f.name}
                  <small>{f.dir}</small>
                </button>
                {i < chain.length - 1 && <span className="impact-chain-arrow">imported by <ArrowRight size={11} /></span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      <LinkList title="Uses" empty="Imports no other project file." ids={file.dependsOn} lookup={lookup} onSelect={onSelect} />
      <LinkList title="Used by" empty="No project file imports this one." ids={file.usedBy} lookup={lookup} onSelect={onSelect} />

      <div className="impact-section">
        <h4>Symbols ({file.symbols.length})</h4>
        {file.symbols.length === 0 ? (
          <p className="muted small">No functions or classes parsed.</p>
        ) : (
          <div className="impact-symbols">
            {symbols.map((sym, i) => <code key={`${sym}-${i}`}>{sym}</code>)}
            {file.symbols.length > 12 && (
              <button type="button" className="impact-more" onClick={() => setAllSymbols((v) => !v)}>
                {allSymbols ? "Show fewer" : `+${file.symbols.length - 12} more`}
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function LinkList({
  title,
  empty,
  ids,
  lookup,
  onSelect,
}: {
  title: string;
  empty: string;
  ids: string[];
  lookup: (id: string) => ImpactFile | undefined;
  onSelect: (id: string) => void;
}) {
  const files = ids.map(lookup).filter((f): f is ImpactFile => Boolean(f));
  const order: Record<ImpactKind, number> = { changed: 0, impacted: 1, test: 2, unaffected: 3 };
  files.sort((a, b) => order[a.kind] - order[b.kind] || a.path.localeCompare(b.path));
  return (
    <div className="impact-section">
      <h4>{title} ({files.length})</h4>
      {files.length === 0 ? (
        <p className="muted small">{empty}</p>
      ) : (
        <ul className="impact-links">
          {files.slice(0, 14).map((f) => (
            <li key={f.id}>
              <button type="button" onClick={() => onSelect(f.id)}>
                <i style={{ background: KIND_STYLE[f.kind].stroke }} />
                <span>{f.name}</span>
                <small>{f.dir}</small>
              </button>
            </li>
          ))}
          {files.length > 14 && <li className="muted small">+{files.length - 14} more</li>}
        </ul>
      )}
    </div>
  );
}

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
