import {
  analyzePullRequestRequest,
  connectGitHubRequest,
  rerunRequest,
  summarizeSync,
  syncPullRequestsRequest,
  type SyncSummary,
} from "./github-actions.ts";

export type UUID = string;

type ApiEnvelope<T> = {
  success: boolean;
  data: T | null;
  error?: { code: string; message: string } | null;
  meta?: Record<string, unknown>;
};

export type Repository = {
  id: UUID | null;
  organization_id: UUID;
  github_repository_id: number;
  name: string;
  owner: string;
  full_name: string;
  provider: string;
  default_branch: string;
  clone_url: string;
  visibility: string;
  status: string;
  branches?: Branch[];
};

export type Branch = {
  id: UUID | null;
  repository_id: UUID;
  name: string;
  latest_commit_sha: string | null;
};

export type Analysis = {
  id: UUID | null;
  repository_id: UUID;
  pull_request_id: UUID;
  commit_sha: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  changed_files?: ChangedFile[];
  blast_radius?: BlastRadius | null;
};

export type ChangedFile = {
  id: UUID | null;
  analysis_id: UUID;
  path: string;
  change_type: string;
  additions: number;
  deletions: number;
};

export type BlastRadius = {
  id: UUID | null;
  analysis_id: UUID;
  affected_files: number;
  affected_symbols: number;
  affected_modules: number;
  affected_tests: number;
  dependency_depth: number;
};

export type ConfidenceEvidence = {
  category: string;
  label: string;
  message: string;
  impact: string;
  value: number | null;
};

export type ConfidenceReport = {
  id: UUID | null;
  analysis_id: UUID;
  confidence_score: number;
  /** "heuristic_uncalibrated" until calibration ships (F-12). */
  score_kind?: string | null;
  risk_level: string;
  summary: string;
  evidence: ConfidenceEvidence[];
  recommendations: string[];
  generated_at: string;
  change_risk?: string | null;
  verification_confidence?: number | null;
  analysis_completeness?: number | null;
  verification_status?: string | null;
};

export type TestCase = {
  id: UUID;
  name: string;
  path: string;
  framework: string;
  test_type: string;
  target_path: string | null;
};

export type TestSelection = {
  analysis_id: UUID;
  selected_count: number;
  skipped_count?: number;
  total_count?: number;
  time_saved_percent?: number;
  cli_args?: string;
  selected_tests: Array<{ test: TestCase; reason: string }>;
  skipped_tests?: TestCase[];
  created_at: string;
};

export type TestRunResult = {
  id: UUID;
  analysis_id: UUID;
  status: string;
  total_tests: number;
  passed: number;
  failed: number;
  skipped: number;
  duration_ms: number;
  coverage_percent?: number | null;
  output: string;
};

export type GraphNode = {
  id: string;
  node_type: string;
  label: string;
  path: string | null;
};

export type GraphEdge = {
  source_id: string;
  target_id: string;
  edge_type: string;
};

export type GraphSnapshot = {
  repository_id: UUID;
  analysis_id: UUID;
  node_count: number;
  edge_count: number;
  graph_version: string;
  created_at: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type ConnectRepositoryPayload = {
  organizationId: UUID;
  repositoryId: number;
  name: string;
  owner: string;
  defaultBranch: string;
  cloneUrl: string;
  visibility: "private" | "public";
};

export const radiusConfig = {
  apiBaseUrl:
    process.env.NEXT_PUBLIC_RADIUS_API_BASE_URL ?? "http://localhost:8000",
  organizationId: process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID ?? "",
};

// The browser never talks to the Radius API directly and never holds the API
// key. Requests go to the same-origin proxy (app/api/radius), which attaches
// the server-only RADIUS_API_KEY. During SSR (no window) the absolute
// dashboard URL is needed; RADIUS_DASHBOARD_INTERNAL_URL provides it.
const PROXY_PREFIX = "/api/radius";

function apiUrl(path: string) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const origin =
    typeof window === "undefined"
      ? (process.env.RADIUS_DASHBOARD_INTERNAL_URL ?? "http://localhost:3000")
      : "";
  return `${origin}${PROXY_PREFIX}${normalized}`;
}

function buildQuery(params: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

function requireOrganizationId() {
  if (!radiusConfig.organizationId) {
    throw new Error(
      "Set NEXT_PUBLIC_RADIUS_ORGANIZATION_ID before using the Radius dashboard.",
    );
  }
  return radiusConfig.organizationId;
}

export async function radiusFetch<T>(
  path: string,
  init: RequestInit & { idempotencyKey?: string } = {},
): Promise<T> {
  const { idempotencyKey, headers, body, ...requestInit } = init;
  const requestHeaders = new Headers(headers);
  requireOrganizationId();
  if (idempotencyKey) requestHeaders.set("Idempotency-Key", idempotencyKey);
  if (body && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const response = await fetch(apiUrl(path), {
    cache: "no-store",
    ...requestInit,
    body,
    headers: requestHeaders,
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !envelope.success) {
    throw new Error(
      envelope.error?.message || `Radius API request failed (${response.status})`,
    );
  }
  if (envelope.data === null) {
    throw new Error("Radius API returned an empty data payload.");
  }
  return envelope.data;
}

/** Error from the Radius API (through the proxy) with the API error code, e.g. INTENT_STALE. */
export class RadiusApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  /** Envelope `meta` of the error response (for example `{ reason: "disabled" }`). */
  readonly meta: Record<string, unknown>;
  constructor(
    message: string,
    status: number,
    code: string | null,
    meta: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "RadiusApiError";
    this.status = status;
    this.code = code;
    this.meta = meta;
  }
}

export type RadiusResult<T> = {
  data: T;
  status: number;
  /** Strong ETag of the response, when the API sent one (intent routes). */
  etag: string | null;
  meta: Record<string, unknown>;
};

/**
 * Like radiusFetch but keeps the status, ETag and meta, accepts the intent
 * concurrency/audit headers, and throws a RadiusApiError carrying the API
 * error code (INTENT_STALE, INTENT_NOT_FOUND, ...). `ifMatch` and `actor` are
 * forwarded by the server proxy only after validation (lib/proxy.ts).
 */
export async function radiusRequest<T>(
  path: string,
  init: RequestInit & { idempotencyKey?: string; ifMatch?: string | null; actor?: string | null } = {},
): Promise<RadiusResult<T>> {
  const { idempotencyKey, ifMatch, actor, headers, body, ...requestInit } = init;
  const requestHeaders = new Headers(headers);
  requireOrganizationId();
  if (idempotencyKey) requestHeaders.set("Idempotency-Key", idempotencyKey);
  if (ifMatch) requestHeaders.set("If-Match", ifMatch);
  if (actor) requestHeaders.set("X-Radius-Actor", actor);
  if (body && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  const response = await fetch(apiUrl(path), {
    cache: "no-store",
    ...requestInit,
    body,
    headers: requestHeaders,
  });
  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    envelope = null;
  }
  if (!response.ok || !envelope || !envelope.success) {
    const apiError = envelope?.error;
    throw new RadiusApiError(
      apiError?.message || `Radius API request failed (${response.status})`,
      response.status,
      typeof apiError?.code === "string" ? apiError.code : null,
      envelope?.meta ?? {},
    );
  }
  if (envelope.data === null) {
    throw new RadiusApiError("Radius API returned an empty data payload.", response.status, null);
  }
  return {
    data: envelope.data,
    status: response.status,
    etag: response.headers.get("ETag"),
    meta: envelope.meta ?? {},
  };
}

/** API list endpoints are paginated (default 100, hard maximum 500); ask for the maximum page. */
export const LIST_PAGE_SIZE = 500;

export function listRepositories() {
  return radiusFetch<Repository[]>(`/repositories?limit=${LIST_PAGE_SIZE}`);
}

export function getRepository(repositoryId: UUID) {
  return radiusFetch<Repository>(`/repositories/${repositoryId}`);
}

export function connectRepository(payload: ConnectRepositoryPayload) {
  return radiusFetch<Repository>("/repositories", {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey: crypto.randomUUID(),
  });
}

export type PullRequest = {
  id: UUID;
  repository_id: UUID;
  github_pr_number: number;
  title: string;
  source_branch: string;
  target_branch: string;
  author: string;
  status: string;
  opened_at: string;
  merged_at: string | null;
};

export function getPullRequestByNumber(repositoryId: UUID, prNumber: number) {
  return radiusFetch<PullRequest>(`/repositories/${repositoryId}/pull-requests/${prNumber}`);
}

export function listPullRequests(repositoryId: UUID) {
  return radiusFetch<PullRequest[]>(
    `/repositories/${repositoryId}/pull-requests?limit=${LIST_PAGE_SIZE}`,
  );
}

export type SyncResult = {
  pullRequests: PullRequest[];
  summary: SyncSummary;
};

/** Pull open pull requests from GitHub; keeps `meta` (analysis ids, skipped reasons). */
export async function syncPullRequestsDetailed(
  repositoryId: UUID,
  autoAnalyze = true,
): Promise<SyncResult> {
  const spec = syncPullRequestsRequest(repositoryId, autoAnalyze);
  const result = await radiusRequest<PullRequest[]>(spec.path, { method: spec.method });
  return {
    pullRequests: result.data,
    summary: summarizeSync(result.data.length, result.meta),
  };
}

export async function syncPullRequests(repositoryId: UUID, autoAnalyze = true) {
  return (await syncPullRequestsDetailed(repositoryId, autoAnalyze)).pullRequests;
}

export type ConnectGitHubResult = {
  repository: Repository;
  created: boolean;
  installationId: number | null;
};

/** Connect a repository by "owner/name" through the GitHub App (no webhook needed). */
export async function connectGitHubRepository(repository: string): Promise<ConnectGitHubResult> {
  const spec = connectGitHubRequest(repository);
  const result = await radiusRequest<Repository>(spec.path, {
    method: spec.method,
    body: spec.body,
  });
  return {
    repository: result.data,
    created: result.meta.created === true,
    installationId: typeof result.meta.installationId === "number" ? result.meta.installationId : null,
  };
}

/** Fetch one pull request from GitHub by number and queue an analysis for its head commit. */
export async function analyzePullRequest(repositoryId: UUID, prNumber: number) {
  const spec = analyzePullRequestRequest(repositoryId, prNumber);
  const result = await radiusRequest<Analysis>(spec.path, { method: spec.method });
  return result.data;
}

export function disconnectRepository(repositoryId: UUID) {
  return radiusFetch<Repository>(`/repositories/${repositoryId}`, {
    method: "DELETE",
  });
}

export function updateRepository(repositoryId: UUID, payload: { defaultBranch: string }) {
  return radiusFetch<Repository>(`/repositories/${repositoryId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listAnalyses(params: {
  repositoryId?: UUID;
  pullRequestId?: UUID;
  status?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return radiusFetch<Analysis[]>(
    `/analyses${buildQuery({
      repositoryId: params.repositoryId,
      pullRequestId: params.pullRequestId,
      status: params.status,
      limit: String(Math.min(Math.max(params.limit ?? LIST_PAGE_SIZE, 1), LIST_PAGE_SIZE)),
      offset: params.offset ? String(Math.max(params.offset, 0)) : undefined,
    })}`,
  );
}

export function getAnalysis(analysisId: UUID) {
  return radiusFetch<Analysis>(`/analyses/${analysisId}`);
}

export async function rerunAnalysis(analysisId: UUID) {
  const spec = rerunRequest(analysisId);
  const result = await radiusRequest<Analysis>(spec.path, {
    method: spec.method,
    idempotencyKey: crypto.randomUUID(),
  });
  return result.data;
}

export type ImportedPullRequest = {
  repositoryId: UUID;
  pullRequestId: UUID;
  analysisId: UUID;
  repository: string;
  pullRequestNumber: number;
  title: string;
  commitSha: string;
};

/** Connect a public GitHub repo from a PR link and queue an analysis of that PR. */
export function importPullRequest(url: string) {
  return radiusFetch<ImportedPullRequest>("/repositories/import-pull-request", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function startAnalysis(payload: {
  repositoryId: UUID;
  pullRequestId?: UUID;
  commitSha: string;
}) {
  return radiusFetch<Analysis>("/analyses", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify({
      repository_id: payload.repositoryId,
      pull_request_id: payload.pullRequestId ?? crypto.randomUUID(),
      commit_sha: payload.commitSha,
    }),
  });
}

export function getBlastRadius(analysisId: UUID) {
  return radiusFetch<BlastRadius>(`/analyses/${analysisId}/blast-radius`);
}

export function getConfidence(analysisId: UUID) {
  return radiusFetch<ConfidenceReport>(`/analyses/${analysisId}/confidence`);
}

export function getTests(analysisId: UUID) {
  return radiusFetch<TestSelection>(`/analyses/${analysisId}/tests`);
}

export async function getTestRunResult(analysisId: UUID): Promise<TestRunResult | null> {
  try {
    return await radiusFetch<TestRunResult>(`/analyses/${analysisId}/tests/results`);
  } catch {
    return null;
  }
}

/** Path of the results upload. The API binds results to a revision, so it requires the head commit. */
export function testResultsUploadPath(analysisId: UUID, commitSha: string): string {
  return `/analyses/${analysisId}/tests/results?commit_sha=${encodeURIComponent(commitSha.trim())}`;
}

export function uploadTestResults(
  analysisId: UUID,
  payload: string,
  isXml = true,
  commitSha = "",
): Promise<TestRunResult> {
  if (!commitSha.trim()) {
    return Promise.reject(
      new Error("The analysis has no commit to bind the results to; re-run the analysis and try again."),
    );
  }
  return radiusFetch<TestRunResult>(testResultsUploadPath(analysisId, commitSha), {
    method: "POST",
    headers: {
      "Content-Type": isXml ? "application/xml" : "application/json",
    },
    body: payload,
  });
}

export function getGraph(analysisId: UUID) {
  return radiusFetch<GraphSnapshot>(`/analyses/${analysisId}/graph`);
}

