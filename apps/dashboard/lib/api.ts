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

export function listRepositories() {
  return radiusFetch<Repository[]>("/repositories");
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
  return radiusFetch<PullRequest[]>(`/repositories/${repositoryId}/pull-requests`);
}

export function syncPullRequests(repositoryId: UUID, autoAnalyze = true) {
  return radiusFetch<PullRequest[]>(
    `/repositories/${repositoryId}/sync-pull-requests${buildQuery({
      auto_analyze: autoAnalyze ? "true" : "false",
    })}`,
    { method: "POST" },
  );
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
} = {}) {
  return radiusFetch<Analysis[]>(
    `/analyses${buildQuery({
      repositoryId: params.repositoryId,
      pullRequestId: params.pullRequestId,
      status: params.status,
    })}`,
  );
}

export function getAnalysis(analysisId: UUID) {
  return radiusFetch<Analysis>(`/analyses/${analysisId}`);
}

export function rerunAnalysis(analysisId: UUID) {
  return radiusFetch<Analysis>(`/analyses/${analysisId}/rerun`, {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
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

export function uploadTestResults(
  analysisId: UUID,
  payload: string,
  isXml = true,
): Promise<TestRunResult> {
  return radiusFetch<TestRunResult>(`/analyses/${analysisId}/tests/results`, {
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

