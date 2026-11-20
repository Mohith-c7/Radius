// Pure helpers for the Test insights page. No Next.js or fetch imports so they
// can be unit tested with node --test.

/** One recorded test execution (GET /analyses/{id}/tests/recent). */
export type TestExecution = {
  id: string;
  test_name: string;
  test_path: string;
  repository_id?: string | null;
  status: string;
  duration_ms: number | null;
  timestamp: string | null;
  branch?: string | null;
  commit_sha?: string | null;
  pr_id?: string | null;
};

/** GET /analyses/{id}/tests/statistics. */
export type TestStatistics = {
  total_runs: number;
  pass_count: number;
  failure_count: number;
  pass_rate: number;
  failure_rate: number;
  average_duration_ms: number;
  recent_failures: number;
  last_execution: string | null;
};

export type FlakyTest = {
  test_path: string;
  test_name: string;
  score: number | null;
  comparable: number;
  flips: number;
  samples_considered: number;
  quarantined: boolean;
  last_status: string;
};

/** GET /analyses/{id}/tests/flaky. */
export type FlakyTestsReport = {
  repository_id: string;
  window: number;
  min_comparable: number;
  threshold: number;
  quarantined: FlakyTest[];
  insufficient_history_count: number;
};

export type AnalysisRef = {
  id: string | null;
  commit_sha: string;
  created_at: string;
};

export type ExecutionSummary = {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  /** Passed share of executed (non-skipped) tests, 0-100; null when nothing ran. */
  passRate: number | null;
  lastRun: string | null;
};

export type TestRun = {
  key: string;
  commitSha: string | null;
  branch: string | null;
  timestamp: string | null;
} & ExecutionSummary;

export type TestOverview = {
  key: string;
  testName: string;
  testPath: string;
  runs: number;
  failures: number;
  lastStatus: string;
  lastRun: string | null;
};

export const CI_GUIDE_URL =
  "https://github.com/Mohith-c7/Radius/blob/develop/docs/CI_INTEGRATION_GUIDE.md";

const FAILED = new Set(["failed", "failure", "error", "errored", "broken"]);
const SKIPPED = new Set(["skipped", "skip", "ignored", "pending", "xfail"]);

export type StatusKind = "passed" | "failed" | "skipped" | "other";

export function statusKind(status: string | null | undefined): StatusKind {
  const value = (status ?? "").trim().toLowerCase();
  if (value === "passed" || value === "pass" || value === "success") return "passed";
  if (FAILED.has(value)) return "failed";
  if (SKIPPED.has(value)) return "skipped";
  return "other";
}

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Newest first; ties keep a stable order by id. */
export function sortNewestFirst<T extends { timestamp: string | null; id?: string }>(rows: T[]): T[] {
  return [...rows].sort(
    (a, b) => time(b.timestamp) - time(a.timestamp) || String(a.id ?? "").localeCompare(String(b.id ?? "")),
  );
}

export function summarizeExecutions(rows: TestExecution[]): ExecutionSummary {
  let passed = 0;
  let failed = 0;
  let skipped = 0;
  let last: string | null = null;
  for (const row of rows) {
    const kind = statusKind(row.status);
    if (kind === "passed") passed += 1;
    else if (kind === "failed") failed += 1;
    else if (kind === "skipped") skipped += 1;
    if (row.timestamp && time(row.timestamp) > time(last)) last = row.timestamp;
  }
  const executed = rows.length - skipped;
  return {
    total: rows.length,
    passed,
    failed,
    skipped,
    passRate: executed > 0 ? Math.round((passed * 1000) / executed) / 10 : null,
    lastRun: last,
  };
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Math.round(value * 10) / 10}%`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${Math.round(ms / 100) / 10} s`;
}

/** Group executions into CI runs: one run per commit (and branch), newest first. */
export function groupRuns(rows: TestExecution[]): TestRun[] {
  const groups = new Map<string, TestExecution[]>();
  for (const row of rows) {
    const key = `${row.commit_sha ?? "unknown"}|${row.branch ?? ""}`;
    const list = groups.get(key);
    if (list) list.push(row);
    else groups.set(key, [row]);
  }
  const runs: TestRun[] = [];
  for (const [key, list] of groups) {
    const summary = summarizeExecutions(list);
    runs.push({
      key,
      commitSha: list[0].commit_sha ?? null,
      branch: list[0].branch ?? null,
      timestamp: summary.lastRun,
      ...summary,
    });
  }
  return runs.sort((a, b) => time(b.timestamp) - time(a.timestamp) || a.key.localeCompare(b.key));
}

export function testKey(row: { test_path: string; test_name: string }): string {
  return `${row.test_path}::${row.test_name}`;
}

/** One row per distinct test, most recently run first. */
export function summarizeTests(rows: TestExecution[]): TestOverview[] {
  const byTest = new Map<string, TestExecution[]>();
  for (const row of sortNewestFirst(rows)) {
    const key = testKey(row);
    const list = byTest.get(key);
    if (list) list.push(row);
    else byTest.set(key, [row]);
  }
  return [...byTest.entries()].map(([key, list]) => ({
    key,
    testName: list[0].test_name,
    testPath: list[0].test_path,
    runs: list.length,
    failures: list.filter((row) => statusKind(row.status) === "failed").length,
    lastStatus: list[0].status,
    lastRun: list[0].timestamp,
  }));
}

/** Executions of one test, newest first. Flaky rows key by path only, so match either. */
export function historyForTest(rows: TestExecution[], key: string): TestExecution[] {
  return sortNewestFirst(
    rows.filter((row) => testKey(row) === key || row.test_path === key),
  );
}

/** The newest analysis with an id: the anchor for repository-scoped test routes. */
export function anchorAnalysis<T extends AnalysisRef>(analyses: T[]): T | null {
  const withId = analyses.filter((analysis) => analysis.id);
  if (!withId.length) return null;
  return [...withId].sort((a, b) => time(b.created_at) - time(a.created_at))[0];
}

/** The newest analysis for a commit, so its statistics describe that CI run. */
export function analysisForCommit<T extends AnalysisRef>(analyses: T[], commitSha: string | null | undefined): T | null {
  if (!commitSha) return null;
  return anchorAnalysis(analyses.filter((analysis) => analysis.commit_sha === commitSha));
}

export function shortSha(value: string | null | undefined): string {
  return value ? value.slice(0, 8) : "-";
}
