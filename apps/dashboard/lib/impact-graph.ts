import type { GraphEdge, GraphNode } from "./api";

/**
 * File-level impact graph for one analysis.
 *
 * The raw CPG holds every file, symbol, import and export of the repository
 * (thousands of nodes). For a reviewer the useful question is narrower: which
 * files does this pull request reach, through which links, and which tests
 * cover them. This module collapses the CPG to files, walks `depends_on`
 * edges backwards from the changed files (B changed -> A depends on B -> A is
 * impacted), and lays the result out in columns by hop distance.
 */

export type ImpactKind = "changed" | "impacted" | "test" | "unaffected";

export type ImpactFile = {
  id: string;
  path: string;
  name: string;
  dir: string;
  kind: ImpactKind;
  isTest: boolean;
  /** Hops from the nearest changed file; 0 = changed, null = not reached. */
  depth: number | null;
  /** Previous file on the shortest impact path (towards the changed file). */
  via: string | null;
  symbols: string[];
  dependsOn: string[];
  usedBy: string[];
  selectedTest: boolean;
  additions?: number;
  deletions?: number;
  changeType?: string;
};

export type ImpactColumn = { key: string; title: string; hint: string; files: string[] };

export type PlacedFile = ImpactFile & { x: number; y: number; column: number };

export type PlacedEdge = {
  key: string;
  /** The file whose change propagates (dependency). */
  from: string;
  /** The file that is affected (dependent). */
  to: string;
  path: string;
  /** True when the path is drawn from `to` to `from`; arrowhead goes on the start. */
  reversed: boolean;
};

export type ImpactLayout = {
  files: Map<string, PlacedFile>;
  edges: PlacedEdge[];
  columns: Array<ImpactColumn & { x: number; width: number }>;
  width: number;
  height: number;
};

export type ImpactGraphModel = {
  files: Map<string, ImpactFile>;
  maxDepth: number;
  counts: { changed: number; impacted: number; tests: number; selectedTests: number; unaffected: number };
  hasFileGraph: boolean;
  /** False when the parser found no file-to-file imports at all (e.g. a language without import resolution). */
  hasImportLinks: boolean;
};

export const NODE_WIDTH = 214;
export const NODE_HEIGHT = 50;
const ROW_GAP = 14;
const SUBCOL_GAP = 18;
const COL_GAP = 96;
const PAD_X = 28;
const PAD_TOP = 64;
const PAD_BOTTOM = 32;
const MAX_ROWS = 10;
/** Columns after this many hops are merged into one "N+ hops" column. */
const DEPTH_CAP = 3;

export function isTestPath(path: string): boolean {
  const p = path.toLowerCase();
  const base = p.split("/").pop() ?? p;
  return (
    /(^|\/)(tests?|__tests__|spec)\//.test(p) ||
    base.startsWith("test_") ||
    /(_test|_tests)\.[a-z]+$/.test(base) ||
    /\.(test|spec)\.[a-z]+$/.test(base)
  );
}

function splitPath(path: string) {
  const parts = path.split("/");
  const name = parts.pop() ?? path;
  return { name, dir: parts.join("/") };
}

export function buildImpactModel(
  nodes: GraphNode[],
  edges: GraphEdge[],
  changedFiles: Array<{ path: string; additions?: number; deletions?: number; change_type?: string }>,
  selectedTestPaths: string[],
): ImpactGraphModel {
  const files = new Map<string, ImpactFile>();
  const idByPath = new Map<string, string>();
  const selected = new Set(selectedTestPaths);

  const addFile = (id: string, path: string) => {
    if (files.has(id)) return files.get(id)!;
    const { name, dir } = splitPath(path);
    const isTest = isTestPath(path);
    const file: ImpactFile = {
      id,
      path,
      name,
      dir,
      kind: "unaffected",
      isTest,
      depth: null,
      via: null,
      symbols: [],
      dependsOn: [],
      usedBy: [],
      selectedTest: selected.has(path),
    };
    files.set(id, file);
    idByPath.set(path, id);
    return file;
  };

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  for (const n of nodes) {
    if (n.node_type === "file" && n.path) addFile(n.id, n.path);
  }
  const hasFileGraph = files.size > 0;

  for (const e of edges) {
    const src = files.get(e.source_id);
    if (!src) continue;
    if (e.edge_type === "contains") {
      const label = nodeById.get(e.target_id)?.label;
      if (label) src.symbols.push(label);
    } else if (e.edge_type === "depends_on") {
      const tgt = files.get(e.target_id);
      if (tgt && tgt.id !== src.id && !src.dependsOn.includes(tgt.id)) {
        src.dependsOn.push(tgt.id);
        tgt.usedBy.push(src.id);
      }
    }
  }

  // Changed files: match graph files by path; keep changed files the parser
  // did not see (deleted, non-code) as standalone nodes so nothing is hidden.
  const queue: string[] = [];
  for (const cf of changedFiles) {
    const id = idByPath.get(cf.path) ?? addFile(`changed:${cf.path}`, cf.path).id;
    const f = files.get(id)!;
    f.kind = "changed";
    f.depth = 0;
    f.additions = cf.additions;
    f.deletions = cf.deletions;
    f.changeType = cf.change_type;
    queue.push(id);
  }
  // Selected tests the graph did not parse still belong on the map.
  for (const p of selected) if (!idByPath.has(p)) addFile(`test:${p}`, p).selectedTest = true;

  // BFS over reverse dependencies: who is affected by the change.
  let maxDepth = 0;
  for (let i = 0; i < queue.length; i++) {
    const cur = files.get(queue[i])!;
    for (const depId of cur.usedBy) {
      const dep = files.get(depId)!;
      if (dep.depth !== null) continue;
      dep.depth = (cur.depth ?? 0) + 1;
      dep.via = cur.id;
      maxDepth = Math.max(maxDepth, dep.depth);
      queue.push(depId);
    }
  }

  const counts = { changed: 0, impacted: 0, tests: 0, selectedTests: 0, unaffected: 0 };
  for (const f of files.values()) {
    if (f.kind !== "changed") {
      if (f.isTest && (f.depth !== null || f.selectedTest)) f.kind = "test";
      else if (f.depth !== null) f.kind = "impacted";
      else f.kind = "unaffected";
    }
    if (f.kind === "changed") counts.changed++;
    else if (f.kind === "impacted") counts.impacted++;
    else if (f.kind === "test") counts.tests++;
    else counts.unaffected++;
    if (f.selectedTest) counts.selectedTests++;
  }
  const hasImportLinks = [...files.values()].some((f) => f.dependsOn.length > 0);
  return { files, maxDepth, counts, hasFileGraph, hasImportLinks };
}

/** Shortest chain from a changed file to `id`, changed file first. */
export function impactChain(model: ImpactGraphModel, id: string): string[] {
  const chain: string[] = [];
  let cur: string | null = id;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    chain.unshift(cur);
    cur = model.files.get(cur)?.via ?? null;
  }
  return chain;
}

/** Everything linked to `id`: what it depends on (transitively) and what depends on it. */
export function linkedSet(model: ImpactGraphModel, id: string, visible: Set<string>): Set<string> {
  const out = new Set<string>([id]);
  const walk = (start: string, next: (f: ImpactFile) => string[]) => {
    const stack = [start];
    while (stack.length) {
      const f = model.files.get(stack.pop()!);
      if (!f) continue;
      for (const n of next(f)) {
        if (!visible.has(n) || out.has(n)) continue;
        out.add(n);
        stack.push(n);
      }
    }
  };
  walk(id, (f) => f.dependsOn);
  walk(id, (f) => f.usedBy);
  return out;
}

export function buildColumns(model: ImpactGraphModel, showUnaffected: boolean, query: string): ImpactColumn[] {
  const q = query.trim().toLowerCase();
  const match = (f: ImpactFile) => !q || f.path.toLowerCase().includes(q);
  const cols: ImpactColumn[] = [
    { key: "changed", title: "Changed in this PR", hint: "edited files", files: [] },
  ];
  const depthCols = Math.min(model.maxDepth, DEPTH_CAP);
  for (let d = 1; d <= depthCols; d++) {
    const capped = d === DEPTH_CAP && model.maxDepth > DEPTH_CAP;
    cols.push({
      key: `d${d}`,
      title: capped ? `${d}+ hops away` : d === 1 ? "Directly affected" : `${d} hops away`,
      hint: d === 1 ? "import a changed file" : "reached through imports",
      files: [],
    });
  }
  cols.push({ key: "tests", title: "Tests", hint: "cover the impacted code", files: [] });
  if (showUnaffected) cols.push({ key: "unaffected", title: "Not affected", hint: "no path from the change", files: [] });

  const byKey = new Map(cols.map((c) => [c.key, c]));
  for (const f of model.files.values()) {
    if (!match(f) && f.kind !== "changed") continue;
    if (f.kind === "changed") byKey.get("changed")!.files.push(f.id);
    else if (f.kind === "test") byKey.get("tests")!.files.push(f.id);
    else if (f.kind === "impacted") byKey.get(`d${Math.min(f.depth ?? 1, DEPTH_CAP)}`)!.files.push(f.id);
    else if (showUnaffected) byKey.get("unaffected")!.files.push(f.id);
  }
  return cols.filter((c) => c.files.length > 0 || c.key === "changed");
}

export function layoutImpact(model: ImpactGraphModel, columns: ImpactColumn[]): ImpactLayout {
  const placed = new Map<string, PlacedFile>();
  const outCols: ImpactLayout["columns"] = [];
  let x = PAD_X;
  let maxBottom = PAD_TOP + NODE_HEIGHT;

  columns.forEach((col, colIndex) => {
    // Order by the average row of already-placed neighbours (barycentre):
    // keeps linked files level with each other and cuts edge crossings.
    const score = (id: string) => {
      const f = model.files.get(id)!;
      const ys = [...f.dependsOn, ...f.usedBy, f.via ?? ""]
        .map((n) => placed.get(n)?.y)
        .filter((y): y is number => typeof y === "number");
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Number.MAX_SAFE_INTEGER;
    };
    const ordered = [...col.files].sort((a, b) => {
      const d = score(a) - score(b);
      if (d !== 0 && Number.isFinite(d)) return d;
      const fa = model.files.get(a)!;
      const fb = model.files.get(b)!;
      if (fa.selectedTest !== fb.selectedTest) return fa.selectedTest ? -1 : 1;
      return fa.path.localeCompare(fb.path);
    });

    const subCols = Math.max(1, Math.ceil(ordered.length / MAX_ROWS));
    const rows = Math.ceil(ordered.length / subCols) || 1;
    const width = subCols * NODE_WIDTH + (subCols - 1) * SUBCOL_GAP;
    ordered.forEach((id, i) => {
      const sub = Math.floor(i / rows);
      const row = i % rows;
      const nx = x + sub * (NODE_WIDTH + SUBCOL_GAP);
      const ny = PAD_TOP + row * (NODE_HEIGHT + ROW_GAP);
      placed.set(id, { ...model.files.get(id)!, x: nx, y: ny, column: colIndex });
      maxBottom = Math.max(maxBottom, ny + NODE_HEIGHT);
    });
    outCols.push({ ...col, x, width });
    x += width + COL_GAP;
  });

  const edges: PlacedEdge[] = [];
  for (const f of placed.values()) {
    for (const depId of f.dependsOn) {
      const dep = placed.get(depId);
      if (!dep) continue;
      // Draw in the direction impact flows: dependency -> dependent.
      const [a, b] = dep.column <= f.column ? [dep, f] : [f, dep];
      let path: string;
      if (a.column === b.column) {
        const sx = a.x + NODE_WIDTH;
        const sy = a.y + NODE_HEIGHT / 2;
        const tx = b.x + NODE_WIDTH;
        const ty = b.y + NODE_HEIGHT / 2;
        const bulge = 36 + Math.min(Math.abs(ty - sy) * 0.15, 60);
        path = `M ${sx} ${sy} C ${sx + bulge} ${sy}, ${tx + bulge} ${ty}, ${tx} ${ty}`;
      } else {
        const sx = a.x + NODE_WIDTH;
        const sy = a.y + NODE_HEIGHT / 2;
        const tx = b.x;
        const ty = b.y + NODE_HEIGHT / 2;
        const c = Math.max((tx - sx) * 0.45, 40);
        path = `M ${sx} ${sy} C ${sx + c} ${sy}, ${tx - c} ${ty}, ${tx} ${ty}`;
      }
      edges.push({ key: `${dep.id}->${f.id}`, from: dep.id, to: f.id, path, reversed: a.id !== dep.id });
    }
  }

  return {
    files: placed,
    edges,
    columns: outCols,
    width: Math.max(x - COL_GAP + PAD_X, 640),
    height: maxBottom + PAD_BOTTOM,
  };
}
