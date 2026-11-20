// Fetch helpers for the Test insights page. All routes are GET, tenant-scoped
// by the API, and allowlisted in lib/proxy.ts.

import { radiusFetch, type UUID } from "./api";
import type { FlakyTestsReport, TestExecution, TestStatistics } from "./test-insights-model";

export const RECENT_LIMIT = 200;

export function testInsightsPath(
  analysisId: UUID,
  route: "statistics" | "flaky" | "recent",
  repositoryId?: UUID,
): string {
  const base = `/analyses/${encodeURIComponent(analysisId)}/tests/${route}`;
  if (route !== "recent" || !repositoryId) return base;
  const query = new URLSearchParams({ repositoryId, limit: String(RECENT_LIMIT) });
  return `${base}?${query.toString()}`;
}

/** Recent executions of the repository (the analysis id only anchors the route). */
export function getRecentExecutions(analysisId: UUID, repositoryId: UUID) {
  return radiusFetch<TestExecution[]>(testInsightsPath(analysisId, "recent", repositoryId));
}

/** Quarantined (flaky) tests of the analysis' repository. */
export function getFlakyTests(analysisId: UUID) {
  return radiusFetch<FlakyTestsReport>(testInsightsPath(analysisId, "flaky"));
}

/** Pass/fail statistics of one analysis' uploaded results. */
export function getTestStatistics(analysisId: UUID) {
  return radiusFetch<TestStatistics>(testInsightsPath(analysisId, "statistics"));
}
