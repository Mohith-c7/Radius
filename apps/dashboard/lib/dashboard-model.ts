// Pure view helpers shared by the analysis lists, search, compare, overview and
// help pages. No React or fetch here so they can be unit tested with node.

import type { Analysis, ConfidenceReport, PullRequest, Repository } from "./api.ts";

/** Repository docs on GitHub (help and settings links). */
export const DOCS_BASE = "https://github.com/Mohith-c7/Radius/blob/develop";
export const ISSUES_URL = "https://github.com/Mohith-c7/Radius/issues/new/choose";

export type PullRequestIndex = Map<string, PullRequest>;

export function shortId(id: string | null | undefined, length = 8): string {
  return id ? id.slice(0, length) : "-";
}

export function truncate(text: string, max = 60): string {
  const clean = text.trim();
  return clean.length > max ? `${clean.slice(0, Math.max(max - 1, 1)).trimEnd()}…` : clean;
}

export function indexPullRequests(pullRequests: PullRequest[]): PullRequestIndex {
  return new Map(pullRequests.filter((pr) => pr.id).map((pr) => [pr.id, pr]));
}

export type AnalysisLabel = {
  /** "#154 build(deps): Bump ..." when the PR is known, else the short analysis id. */
  title: string;
  /** Secondary line: the short analysis id, or why no PR is shown. */
  secondary: string;
  pullRequest: PullRequest | null;
};

export function analysisLabel(
  analysis: Pick<Analysis, "id" | "pull_request_id">,
  pullRequests: PullRequestIndex,
  max = 60,
): AnalysisLabel {
  const pr = analysis.pull_request_id ? pullRequests.get(analysis.pull_request_id) ?? null : null;
  if (pr) {
    return {
      title: `#${pr.github_pr_number} ${truncate(pr.title, max)}`,
      secondary: `Analysis ${shortId(analysis.id)}`,
      pullRequest: pr,
    };
  }
  return {
    title: `Analysis ${shortId(analysis.id)}`,
    secondary: "Manual run or pull request not synced",
    pullRequest: null,
  };
}

/** https://github.com/<owner>/<repo>/pull/<n>, or null for a malformed name or number. */
export function pullRequestUrl(fullName: string | null | undefined, number: number): string | null {
  if (!fullName || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(fullName)) return null;
  if (!Number.isInteger(number) || number <= 0) return null;
  return `https://github.com/${fullName}/pull/${number}`;
}

function timestamp(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Completed analyses with an id, newest first. */
export function completedAnalyses<T extends Pick<Analysis, "id" | "status" | "created_at">>(
  analyses: T[],
): T[] {
  return analyses
    .filter((analysis) => analysis.id && analysis.status.toLowerCase() === "completed")
    .sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at));
}

/** The two newest completed analyses (newer one first), or nulls when missing. */
export function defaultComparePair(
  analyses: Array<Pick<Analysis, "id" | "status" | "created_at">>,
): [string | null, string | null] {
  const [first, second] = completedAnalyses(analyses);
  return [first?.id ?? null, second?.id ?? null];
}

/** Rounded mean of the reports' confidence scores, or null when there are none. */
export function averageConfidence(
  reports: Array<Pick<ConfidenceReport, "confidence_score">>,
): number | null {
  const scores = reports
    .map((report) => report.confidence_score)
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  if (scores.length === 0) return null;
  return Math.round(scores.reduce((total, value) => total + value, 0) / scores.length);
}

function matches(query: string, values: Array<string | number | null | undefined>): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return values.some(
    (value) => value !== null && value !== undefined && String(value).toLowerCase().includes(needle),
  );
}

function prFields(pr: PullRequest | null | undefined) {
  return pr ? [`#${pr.github_pr_number}`, pr.title, pr.source_branch, pr.author] : [];
}

/** Analysis search: id prefix, commit sha, status, repository, PR number and title. */
export function analysisMatches(
  analysis: Pick<Analysis, "id" | "commit_sha" | "status">,
  query: string,
  context: { repositoryName: string; pullRequest?: PullRequest | null },
): boolean {
  return matches(query, [
    analysis.id,
    analysis.commit_sha,
    analysis.status,
    context.repositoryName,
    ...prFields(context.pullRequest),
  ]);
}

export function pullRequestMatches(pr: PullRequest, query: string, repositoryName: string): boolean {
  return matches(query, [...prFields(pr), repositoryName, pr.id]);
}

export function repositoryMatches(repository: Pick<Repository, "full_name">, query: string): boolean {
  return matches(query, [repository.full_name]);
}

export type ServiceStatus = { tone: "positive" | "warning" | "neutral"; text: string };

/** Help page status line from GET /ready (through the proxy). */
export function describeReadiness(result: "loading" | "error" | { status: number }): ServiceStatus {
  if (result === "loading") return { tone: "neutral", text: "Checking the Radius API…" };
  if (result === "error") return { tone: "warning", text: "The Radius API could not be reached." };
  if (result.status >= 200 && result.status < 300) {
    return { tone: "positive", text: "The Radius API reports ready (database and job queue reachable)." };
  }
  if (result.status === 401 || result.status === 403) {
    return { tone: "neutral", text: "Sign in to check the Radius API status." };
  }
  return { tone: "warning", text: `The Radius API is not ready (HTTP ${result.status}).` };
}
