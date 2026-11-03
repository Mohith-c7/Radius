// Pure logic for the pull-based GitHub actions (connect by owner/name, analyze a
// pull request, sync open pull requests, re-run). No React and no fetch here, so
// node --test covers it. All strings returned are plain text; the components
// render them as React text nodes only.

export type RequestSpec = {
  path: string;
  method: "POST";
  body?: string;
};

// ---- repository name ---------------------------------------------------------

const ALLOWED_NAME = /^[A-Za-z0-9._-]+$/;
const URL_PREFIXES = ["https://github.com/", "http://github.com/", "github.com/"];

export type RepositoryInput =
  | { ok: true; value: string; owner: string; name: string }
  | { ok: false; message: string };

/**
 * Same rules as the API (radius_api.github_pull.parse_owner_repo): `owner/name`,
 * a github.com URL and a `.git` suffix are accepted. The API stays the authority;
 * this only saves a round trip for obvious typos.
 */
export function parseRepositoryInput(raw: string): RepositoryInput {
  let text = raw.trim();
  if (!text) return { ok: false, message: "Enter the repository as owner/name, for example acme/widgets." };
  for (const prefix of URL_PREFIXES) {
    if (text.toLowerCase().startsWith(prefix)) text = text.slice(prefix.length);
  }
  text = text.replace(/^\/+|\/+$/g, "");
  if (text.endsWith(".git")) text = text.slice(0, -4);
  const parts = text.split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return { ok: false, message: "The repository must look like owner/name, for example acme/widgets." };
  }
  const [owner, name] = parts;
  if (!ALLOWED_NAME.test(owner) || !ALLOWED_NAME.test(name)) {
    return {
      ok: false,
      message: "The repository contains characters GitHub does not allow (letters, digits, - _ . only).",
    };
  }
  if (text.length > 300) return { ok: false, message: "The repository name is too long." };
  return { ok: true, value: `${owner}/${name}`, owner, name };
}

// ---- request builders --------------------------------------------------------

export function connectGitHubRequest(repository: string): RequestSpec {
  return {
    path: "/repositories/connect-github",
    method: "POST",
    body: JSON.stringify({ repository }),
  };
}

export function analyzePullRequestRequest(repositoryId: string, prNumber: number): RequestSpec {
  if (!Number.isInteger(prNumber) || prNumber < 1) {
    throw new RangeError("Pull request number must be a positive integer.");
  }
  return {
    path: `/repositories/${encodeURIComponent(repositoryId)}/pull-requests/${prNumber}/analyze`,
    method: "POST",
  };
}

export function syncPullRequestsRequest(repositoryId: string, autoAnalyze = true): RequestSpec {
  return {
    path: `/repositories/${encodeURIComponent(repositoryId)}/sync-pull-requests?auto_analyze=${
      autoAnalyze ? "true" : "false"
    }`,
    method: "POST",
  };
}

export function rerunRequest(analysisId: string): RequestSpec {
  return { path: `/analyses/${encodeURIComponent(analysisId)}/rerun`, method: "POST" };
}

// ---- errors ------------------------------------------------------------------

export type ErrorInfo = { status: number | null; code: string | null; message: string };

/** Reads status/code/message from a RadiusApiError or any thrown value. */
export function toErrorInfo(error: unknown): ErrorInfo {
  if (error && typeof error === "object") {
    const e = error as { status?: unknown; code?: unknown; message?: unknown };
    return {
      status: typeof e.status === "number" ? e.status : null,
      code: typeof e.code === "string" ? e.code : null,
      message: typeof e.message === "string" ? e.message : String(error),
    };
  }
  return { status: null, code: null, message: String(error) };
}

const MESSAGES: Record<string, string> = {
  GITHUB_APP_NOT_CONFIGURED:
    "The Radius API has no GitHub App credentials. Set GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY for the api service, restart it, and try again.",
  GITHUB_APP_NOT_INSTALLED:
    "The Radius GitHub App is not installed on this repository. Install it from the App's settings page (Install App), then connect again.",
  GITHUB_APP_AUTH_FAILED:
    "GitHub rejected the App credentials. Check GITHUB_APP_ID, that the private key belongs to this App, and that this computer's clock is correct.",
  GITHUB_REPOSITORY_NOT_ACCESSIBLE:
    "GitHub could not find this repository for the App. Check the spelling of owner/name and that the App is installed on it.",
  GITHUB_INSTALLATION_MISMATCH:
    "This organization is already linked to a different GitHub installation. Use a repository under the same GitHub account.",
  GITHUB_RATE_LIMITED:
    "GitHub is rate limiting the App. Wait a minute and try again.",
  GITHUB_API_ERROR:
    "GitHub returned an error. The details below say what GitHub reported.",
  REPOSITORY_DISCONNECTED:
    "This repository is disconnected. Connect it again with the form on the Repositories page first.",
  VALIDATION_ERROR: "The request was not valid.",
};

export type ErrorView = { title: string; detail: string | null };

/**
 * Human text for an API error. Known codes get a fixed explanation plus the
 * server message (which names what GitHub said); unknown codes show the server
 * message; network failures say the dashboard server could not be reached.
 */
export function describeGitHubError(input: unknown): ErrorView {
  const info = toErrorInfo(input);
  const known = info.code ? MESSAGES[info.code] : undefined;
  if (known) {
    const same = info.message === known;
    return { title: known, detail: same || !info.message ? null : info.message };
  }
  if (info.status === null && !info.code) {
    return {
      title: "Could not reach the Radius dashboard server. Check that it is running, then try again.",
      detail: info.message || null,
    };
  }
  if (info.status === 401 || (info.status === 403 && !info.code)) {
    return { title: "Radius refused the request (not authorised). Check RADIUS_API_KEY for the dashboard.", detail: info.message || null };
  }
  if (info.status === 429) {
    return { title: "Too many requests. Wait a few seconds and try again.", detail: info.message || null };
  }
  if (info.status === 404 && info.message) {
    return { title: info.message, detail: null };
  }
  return { title: info.message || "The request failed.", detail: null };
}

/** One line for status banners. */
export function errorText(input: unknown): string {
  const view = describeGitHubError(input);
  return view.detail ? `${view.title} (${view.detail})` : view.title;
}

// ---- sync summary --------------------------------------------------------------

export type SkippedPullRequest = { number: number | null; reason: string };

export type SyncSummary = {
  kind: "not_configured" | "synced";
  pullRequests: number;
  analysesQueued: number;
  skipped: SkippedPullRequest[];
  text: string;
};

/** Reads `meta` of POST /repositories/{id}/sync-pull-requests defensively. */
export function summarizeSync(pullRequestCount: number, meta: Record<string, unknown> | null | undefined): SyncSummary {
  const m = meta ?? {};
  if (m.github === "not_configured") {
    return {
      kind: "not_configured",
      pullRequests: pullRequestCount,
      analysesQueued: 0,
      skipped: [],
      text: "GitHub is not configured on the Radius API, so nothing was pulled. Showing the pull requests already stored. Set GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY for the api service.",
    };
  }
  const analysisIds = Array.isArray(m.analysisIds) ? m.analysisIds : [];
  const skipped: SkippedPullRequest[] = [];
  if (Array.isArray(m.skipped)) {
    for (const item of m.skipped) {
      if (!item || typeof item !== "object") continue;
      const entry = item as { number?: unknown; reason?: unknown };
      skipped.push({
        number: typeof entry.number === "number" ? entry.number : null,
        reason: typeof entry.reason === "string" ? entry.reason : "unknown reason",
      });
    }
  }
  const parts = [
    `Synced ${pullRequestCount} pull request${pullRequestCount === 1 ? "" : "s"} from GitHub`,
    `${analysisIds.length} new analys${analysisIds.length === 1 ? "is" : "es"} queued`,
  ];
  if (skipped.length > 0) parts.push(`${skipped.length} skipped`);
  return {
    kind: "synced",
    pullRequests: pullRequestCount,
    analysesQueued: analysisIds.length,
    skipped,
    text: `${parts.join(", ")}.`,
  };
}

export function skippedLabel(item: SkippedPullRequest): string {
  return item.number === null ? `A pull request: ${item.reason}` : `#${item.number}: ${item.reason}`;
}

// ---- connect result ------------------------------------------------------------

export function connectMessage(fullName: string, created: boolean): string {
  return created
    ? `Connected ${fullName}.`
    : `${fullName} was already connected. Nothing changed.`;
}

/** Only open pull requests can be analyzed (GitHub is asked for the current head commit). */
export function canAnalyze(pullRequest: { status: string }): boolean {
  return pullRequest.status === "open";
}
