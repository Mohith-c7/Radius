"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  FileCode2,
  FolderGit2,
  GitBranch,
  GitPullRequest,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  TestTube2,
  Trash2,
  UploadCloud,
  XCircle,
  Zap,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  Analysis,
  BlastRadius,
  ConfidenceReport,
  ConnectRepositoryPayload,
  GraphSnapshot,
  PullRequest,
  Repository,
  TestRunResult,
  TestSelection,
  connectRepository,
  disconnectRepository,
  getAnalysis,
  getBlastRadius,
  getConfidence,
  getGraph,
  getPullRequestByNumber,
  getRepository,
  getTestRunResult,
  getTests,
  listAnalyses,
  listPullRequests,
  listRepositories,
  radiusConfig,
  rerunAnalysis,
  startAnalysis,
  syncPullRequests,
  updateRepository,
  uploadTestResults,
} from "../lib/api";
import { ConfidenceRing, OpenLink, PageHeading, Status } from "./ui";
import { InteractiveGraphViewer } from "./interactive-graph";

type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; data: T };

function useRadiusData<T>(load: () => Promise<T>, deps: React.DependencyList) {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  const loadRef = useRef(load);
  const dependencyKey = JSON.stringify(deps);

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    loadRef
      .current()
      .then((data) => active && setState({ status: "ready", data }))
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          status: "error",
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return () => {
      active = false;
    };
  }, [dependencyKey]);

  return state;
}

function LoadingState({ label = "Loading Radius data" }: { label?: string }) {
  return (
    <div className="card detail-card state-card">
      <Loader2 size={18} className="spin" />
      <strong>{label}</strong>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="card detail-card state-card error-state">
      <AlertCircle size={18} />
      <strong>Dashboard could not reach the Radius API.</strong>
      <p className="muted">{message}</p>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="card detail-card state-card">
      <strong>{title}</strong>
      <p className="muted">{detail}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="metric-card">
      <dt>{label}</dt>
      <dd>{value}</dd>
      <small>Live Radius API data</small>
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function shortSha(value: string) {
  return value.slice(0, 8);
}

function score(report?: ConfidenceReport | null) {
  return Math.round(report?.confidence_score ?? 0);
}

function repositoryName(repositories: Repository[], repositoryId: string) {
  return (
    repositories.find((repository) => repository.id === repositoryId)
      ?.full_name ?? repositoryId
  );
}

function settledValue<T>(result: PromiseSettledResult<T>) {
  return result.status === "fulfilled" ? result.value : null;
}

async function loadOverview() {
  const repositories = await listRepositories();
  const analyses = await listAnalyses();
  const reports = await Promise.allSettled(
    analyses
      .slice(0, 6)
      .filter((analysis) => analysis.id)
      .map((analysis) => getConfidence(analysis.id as string)),
  );
  return {
    repositories,
    analyses,
    reports: reports
      .filter((result): result is PromiseFulfilledResult<ConfidenceReport> => {
        return result.status === "fulfilled";
      })
      .map((result) => result.value),
  };
}

export function DashboardOverviewData() {
  const state = useRadiusData(loadOverview, []);
  if (state.status === "loading") return <LoadingState />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  const { repositories, analyses, reports } = state.data;
  const average =
    reports.length > 0
      ? Math.round(
          reports.reduce((total, report) => total + report.confidence_score, 0) /
            reports.length,
        )
      : 0;
  const attention = analyses.filter((item) =>
    ["failed", "cancelled"].includes(item.status.toLowerCase()),
  ).length;

  return (
    <>
      <PageHeading
        title="Engineering workspace"
        description="Live verification health from Radius backend services."
        action={
          <Link href="/repositories/connect" className="button">
            <Plus size={16} />
            Connect repository
          </Link>
        }
      />
      <section className="metric-grid">
        <Metric label="Connected repositories" value={repositories.length} />
        <Metric label="Analyses tracked" value={analyses.length} />
        <Metric label="Average confidence" value={average ? `${average}/100` : "-"} />
        <Metric label="Attention needed" value={attention} />
      </section>
      <div className="content-grid">
        <RecentAnalysesCard analyses={analyses.slice(0, 5)} repositories={repositories} />
        <section className="card">
          <div className="card-heading">
            <div>
              <h2>Workspace confidence</h2>
              <p>Computed from available confidence reports</p>
            </div>
          </div>
          <div className="confidence-summary">
            <ConfidenceRing score={average} />
            <div>
              <h3>{average ? "Evidence available" : "No reports yet"}</h3>
              <p>
                {average
                  ? "Radius is aggregating confidence from recent analyses."
                  : "Run analyses to generate confidence evidence."}
              </p>
            </div>
          </div>
          <RepositoryRows repositories={repositories.slice(0, 6)} />
        </section>
      </div>
    </>
  );
}

function RecentAnalysesCard({
  analyses,
  repositories,
}: {
  analyses: Analysis[];
  repositories: Repository[];
}) {
  return (
    <section className="card">
      <div className="card-heading">
        <div>
          <h2>Recent analyses</h2>
          <p>Latest pull request verification runs</p>
        </div>
        <OpenLink href="/analyses">View all</OpenLink>
      </div>
      {analyses.length === 0 ? (
        <div className="detail-card">
          <p className="muted">No analyses have been created yet.</p>
        </div>
      ) : (
        <AnalysisTable analyses={analyses} repositories={repositories} />
      )}
    </section>
  );
}

function RepositoryRows({ repositories }: { repositories: Repository[] }) {
  if (repositories.length === 0) {
    return (
      <div className="repo-list">
        <p className="muted">No repositories connected yet.</p>
      </div>
    );
  }
  return (
    <div className="repo-list">
      {repositories.map((repository) => (
        <div className="repo-row" key={repository.id ?? repository.full_name}>
          <span className="repo-icon">
            <FolderGit2 size={17} />
          </span>
          <span>
            <strong>{repository.full_name}</strong>
            <small>
              {repository.provider} / {repository.visibility}
            </small>
          </span>
          <Status status={repository.status} />
        </div>
      ))}
    </div>
  );
}

export function RepositoriesData() {
  const [refreshKey, setRefreshKey] = useState(0);
  const state = useRadiusData(listRepositories, [refreshKey]);

  async function remove(repositoryId: string) {
    await disconnectRepository(repositoryId);
    setRefreshKey((value) => value + 1);
  }

  if (state.status === "loading") return <LoadingState label="Loading repositories" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  return (
    <>
      <PageHeading
        eyebrow="Repository management"
        title="Repositories"
        description="Connected GitHub repositories and their backend sync status."
        action={
          <Link href="/repositories/connect" className="button">
            <Plus size={16} />
            Connect repository
          </Link>
        }
      />
      {state.data.length === 0 ? (
        <EmptyState
          title="No repositories connected"
          detail="Connect a GitHub repository to begin synchronization and analysis."
        />
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Default branch</th>
                  <th>Provider</th>
                  <th>Visibility</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {state.data.map((repository) => (
                  <tr key={repository.id ?? repository.full_name}>
                    <td>
                      <div className="repo-name">
                        <span className="repo-icon">
                          <FolderGit2 size={16} />
                        </span>
                        <span>
                          <Link
                            href={`/repositories/${repository.id}`}
                            style={{ color: "inherit", textDecoration: "none" }}
                          >
                            <strong>{repository.full_name}</strong>
                          </Link>
                          <div className="subtext">{repository.clone_url}</div>
                        </span>
                      </div>
                    </td>
                    <td>
                      <code>{repository.default_branch}</code>
                    </td>
                    <td>{repository.provider}</td>
                    <td>{repository.visibility}</td>
                    <td>
                      <Status status={repository.status} />
                    </td>
                    <td>
                      {repository.id && (
                        <button
                          className="icon-action"
                          onClick={() => void remove(repository.id as string)}
                          title="Disconnect repository"
                          type="button"
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

export function ConnectRepositoryForm() {
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    const form = new FormData(event.currentTarget);
    const payload: ConnectRepositoryPayload = {
      organizationId: String(form.get("organizationId")),
      repositoryId: Number(form.get("repositoryId")),
      owner: String(form.get("owner")),
      name: String(form.get("name")),
      defaultBranch: String(form.get("defaultBranch") || "main"),
      cloneUrl: String(form.get("cloneUrl")),
      visibility: String(form.get("visibility")) as "private" | "public",
    };
    try {
      const repository = await connectRepository(payload);
      setMessage(`Connected ${repository.full_name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="Repository management"
        title="Connect a repository"
        description="Create a backend repository record Radius can synchronize and analyze."
      />
      
      <div className="card" style={{ marginBottom: "2rem", padding: "2rem", display: "flex", flexDirection: "column", alignItems: "center", border: "1px solid var(--border-color)" }}>
        <h2 style={{ marginBottom: "0.5rem" }}>Install GitHub App</h2>
        <p className="muted" style={{ marginBottom: "1.5rem", textAlign: "center", maxWidth: "600px" }}>
          Install the Radius GitHub App to automatically synchronize repositories and trigger verification pipelines on push.
        </p>
        <a 
          href={process.env.NEXT_PUBLIC_GITHUB_APP_URL || "https://github.com/apps/radius-verification/installations/new"} 
          target="_blank" 
          rel="noreferrer" 
          className="button primary"
          style={{ padding: "0.75rem 1.5rem", fontSize: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}
        >
          <Plus size={18} />
          Install App
        </a>
      </div>

      <h3 style={{ marginBottom: "1rem", marginTop: "2rem", color: "var(--text-color)", fontSize: "1.1rem", fontWeight: 600 }}>Manual configuration</h3>
      <p className="muted" style={{ marginBottom: "1.5rem" }}>
        Manually register a repository for local testing or custom CI/CD integrations.
      </p>
      <div className="detail-grid">
        <form className="card detail-card form-grid" onSubmit={submit}>
          <label>
            Organization ID
            <input name="organizationId" defaultValue={radiusConfig.organizationId} required />
          </label>
          <label>
            GitHub repository ID
            <input name="repositoryId" required type="number" min="1" />
          </label>
          <label>
            Owner
            <input name="owner" placeholder="Mohith-c7" required />
          </label>
          <label>
            Repository name
            <input name="name" placeholder="Radius" required />
          </label>
          <label>
            Default branch
            <input name="defaultBranch" defaultValue="develop" required />
          </label>
          <label>
            Visibility
            <select name="visibility" defaultValue="private">
              <option value="private">Private</option>
              <option value="public">Public</option>
            </select>
          </label>
          <label className="full-span">
            Clone URL
            <input
              name="cloneUrl"
              placeholder="https://github.com/Mohith-c7/Radius.git"
              required
              type="url"
            />
          </label>
          <div className="form-actions full-span">
            <button className="button" disabled={submitting} type="submit">
              {submitting ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
              Connect repository
            </button>
            {message && <p className="muted">{message}</p>}
          </div>
        </form>
        <aside className="card detail-card">
          <h2>Backend endpoint</h2>
          <p className="muted">
            This form posts to <code>POST /api/v1/repositories</code> and sends
            the configured organization header.
          </p>
        </aside>
      </div>
    </>
  );
}

export function RepositoryDetailData({ repositoryId }: { repositoryId: string }) {
  const router = useRouter();
  const [refreshKey, setRefreshKey] = useState(0);
  const [syncingPrs, setSyncingPrs] = useState(false);
  const [syncNotice, setSyncNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [targetBranchInput, setTargetBranchInput] = useState("");
  const [updatingBranch, setUpdatingBranch] = useState(false);
  const [triggerModalOpen, setTriggerModalOpen] = useState(false);

  const state = useRadiusData(async () => {
    const repository = await getRepository(repositoryId);
    const analyses = await listAnalyses({ repositoryId });
    const pullRequests = await listPullRequests(repositoryId);
    return { repository, analyses, pullRequests };
  }, [repositoryId, refreshKey]);

  useEffect(() => {
    if (state.status === "ready" && state.data.repository.default_branch && !targetBranchInput) {
      setTargetBranchInput(state.data.repository.default_branch);
    }
  }, [state, targetBranchInput]);

  if (state.status === "loading") return <LoadingState label="Loading repository" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  const { repository, analyses, pullRequests } = state.data;

  async function handleSyncPullRequests() {
    setSyncingPrs(true);
    setSyncNotice(null);
    try {
      const prs = await syncPullRequests(repositoryId);
      setSyncNotice({
        type: "success",
        text: `Successfully synced ${prs.length} pull request(s) from GitHub.`,
      });
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setSyncNotice({
        type: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSyncingPrs(false);
    }
  }

  async function handleUpdateDefaultBranch(branchToSet: string) {
    if (!branchToSet.trim()) return;
    setUpdatingBranch(true);
    setSyncNotice(null);
    try {
      await updateRepository(repositoryId, { defaultBranch: branchToSet.trim() });
      setSyncNotice({
        type: "success",
        text: `Default target branch updated to '${branchToSet.trim()}'.`,
      });
      setTargetBranchInput(branchToSet.trim());
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setSyncNotice({
        type: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setUpdatingBranch(false);
    }
  }

  async function handleQuickVerify(commitSha: string, pullRequestId?: string) {
    try {
      const res = await startAnalysis({
        repositoryId,
        commitSha,
        pullRequestId,
      });
      if (res.id) {
        router.push(`/analyses/${res.id}`);
      }
    } catch (err) {
      setSyncNotice({
        type: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <>
      <PageHeading
        eyebrow={`Repository / ${repository.provider}`}
        title={repository.full_name}
        description={`${repository.visibility} / ${repository.status}`}
        action={
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <button
              className="button secondary"
              onClick={handleSyncPullRequests}
              disabled={syncingPrs}
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
            >
              <RefreshCw size={14} className={syncingPrs ? "spin" : ""} />
              {syncingPrs ? "Syncing PRs..." : "Sync Pull Requests"}
            </button>
            <button
              className="button"
              onClick={() => setTriggerModalOpen(true)}
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
            >
              <Play size={14} />
              Run Verification
            </button>
            <Status status={repository.status} />
          </div>
        }
      />

      {syncNotice && (
        <div
          className="card"
          style={{
            marginBottom: "16px",
            padding: "12px 16px",
            borderLeft: `4px solid ${
              syncNotice.type === "success" ? "var(--green, #22c55e)" : "var(--red, #ef4444)"
            }`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: "14px" }}>{syncNotice.text}</span>
          <button
            onClick={() => setSyncNotice(null)}
            style={{ background: "none", border: "none", color: "inherit", cursor: "pointer" }}
          >
            ×
          </button>
        </div>
      )}

      <section className="metric-grid">
        <Metric label="Target branch" value={repository.default_branch} />
        <Metric label="Pull requests" value={pullRequests.length} />
        <Metric label="Branches indexed" value={repository.branches?.length ?? 0} />
        <Metric label="Verification runs" value={analyses.length} />
      </section>

      {/* Target Branch Configuration & Branch Selection Panel */}
      <div className="card detail-card" style={{ marginBottom: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 style={{ margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
              <GitBranch size={18} style={{ color: "var(--accent)" }} />
              Branches & Verification Targets
            </h2>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: "13px" }}>
              Select which branch Radius monitors and runs verification against.
            </p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "12px", alignItems: "center", marginBottom: "16px" }}>
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <input
              type="text"
              value={targetBranchInput}
              onChange={(e) => setTargetBranchInput(e.target.value)}
              placeholder="e.g. main, master, develop"
              className="input"
              style={{
                padding: "8px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border)",
                background: "var(--card-bg, #1a221f)",
                color: "inherit",
                width: "240px",
              }}
            />
            <button
              className="button secondary"
              onClick={() => handleUpdateDefaultBranch(targetBranchInput)}
              disabled={updatingBranch || targetBranchInput === repository.default_branch}
            >
              {updatingBranch ? "Updating..." : "Set as Target Default"}
            </button>
          </div>
        </div>

        {repository.branches && repository.branches.length > 0 ? (
          <div style={{ display: "grid", gap: "8px" }}>
            {repository.branches.map((b) => {
              const isDefault = b.name === repository.default_branch;
              return (
                <div
                  key={b.id || b.name}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "10px 14px",
                    borderRadius: "6px",
                    background: isDefault ? "rgba(34, 197, 94, 0.08)" : "var(--card-bg, rgba(255,255,255,0.03))",
                    border: `1px solid ${isDefault ? "rgba(34, 197, 94, 0.3)" : "var(--border)"}`,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <GitBranch size={16} style={{ color: isDefault ? "var(--green)" : "var(--muted)" }} />
                    <span style={{ fontWeight: 600 }}>{b.name}</span>
                    {isDefault && (
                      <span
                        style={{
                          fontSize: "11px",
                          padding: "2px 8px",
                          borderRadius: "10px",
                          background: "var(--green, #22c55e)",
                          color: "#fff",
                          fontWeight: 700,
                        }}
                      >
                        Default Target
                      </span>
                    )}
                    {b.latest_commit_sha && (
                      <span className="muted" style={{ fontFamily: "monospace", fontSize: "12px" }}>
                        {shortSha(b.latest_commit_sha)}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "8px" }}>
                    {!isDefault && (
                      <button
                        className="button secondary"
                        style={{ padding: "4px 10px", fontSize: "12px" }}
                        onClick={() => handleUpdateDefaultBranch(b.name)}
                      >
                        Make Default
                      </button>
                    )}
                    {b.latest_commit_sha && (
                      <button
                        className="button"
                        style={{ padding: "4px 10px", fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}
                        onClick={() => handleQuickVerify(b.latest_commit_sha!)}
                      >
                        <Play size={12} />
                        Verify Branch
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: "13px" }}>
            No secondary branches cached yet. Push commits or open pull requests to discover branches.
          </p>
        )}
      </div>

      {/* Pull Requests Section */}
      <div className="card detail-card" style={{ marginBottom: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 style={{ margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
              <GitPullRequest size={18} style={{ color: "var(--accent)" }} />
              Pull Requests ({pullRequests.length})
            </h2>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: "13px" }}>
              Detected pull requests with automated confidence verification reports.
            </p>
          </div>
          <button
            className="button secondary"
            onClick={handleSyncPullRequests}
            disabled={syncingPrs}
            style={{ display: "flex", alignItems: "center", gap: "6px" }}
          >
            <RefreshCw size={14} className={syncingPrs ? "spin" : ""} />
            Sync from GitHub
          </button>
        </div>

        {pullRequests.length > 0 ? (
          <div style={{ display: "grid", gap: "10px" }}>
            {pullRequests.map((pr) => {
              const matchingAnalysis = analyses.find((a) => a.pull_request_id === pr.id);
              return (
                <div
                  key={pr.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "12px 16px",
                    borderRadius: "6px",
                    border: "1px solid var(--border)",
                    background: "var(--card-bg, rgba(255,255,255,0.02))",
                  }}
                >
                  <div style={{ display: "grid", gap: "4px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                      <Link
                        href={`/pull-requests/${pr.id}`}
                        style={{ fontWeight: 600, color: "var(--foreground)", textDecoration: "none" }}
                      >
                        #{pr.github_pr_number} {pr.title}
                      </Link>
                      <span
                        style={{
                          fontSize: "11px",
                          padding: "2px 8px",
                          borderRadius: "10px",
                          textTransform: "capitalize",
                          background:
                            pr.status === "open"
                              ? "rgba(34, 197, 94, 0.15)"
                              : pr.status === "merged"
                              ? "rgba(168, 85, 247, 0.15)"
                              : "rgba(156, 163, 175, 0.15)",
                          color:
                            pr.status === "open"
                              ? "var(--green, #22c55e)"
                              : pr.status === "merged"
                              ? "#c084fc"
                              : "#9ca3af",
                        }}
                      >
                        {pr.status}
                      </span>
                      <span
                        title={`Radius Internal PR UUID: ${pr.id}`}
                        style={{
                          fontSize: "11px",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          background: "rgba(255, 255, 255, 0.06)",
                          border: "1px solid var(--border)",
                          fontFamily: "monospace",
                          color: "var(--muted)",
                        }}
                      >
                        ID: {pr.id ? pr.id.slice(0, 8) : "-"}
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: "12px", display: "flex", gap: "16px", flexWrap: "wrap" }}>
                      <span>Author: {pr.author}</span>
                      <span>
                        Route: <code>{pr.source_branch}</code> → <code>{pr.target_branch}</code>
                      </span>
                      <span>Opened: {formatDate(pr.opened_at)}</span>
                      <span>
                        Full ID: <code style={{ fontSize: "11px" }}>{pr.id}</code>
                      </span>
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    {matchingAnalysis ? (
                      <Link
                        href={`/analyses/${matchingAnalysis.id}`}
                        className="button secondary"
                        style={{ padding: "6px 12px", fontSize: "12px" }}
                      >
                        View Analysis ({matchingAnalysis.status})
                      </Link>
                    ) : (
                      <span className="muted" style={{ fontSize: "12px" }}>
                        No analysis yet
                      </span>
                    )}
                    <Link
                      href={`/pull-requests/${pr.id}`}
                      className="button"
                      style={{ padding: "6px 12px", fontSize: "12px" }}
                    >
                      Details →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="empty-state" style={{ padding: "24px 0", textAlign: "center" }}>
            <p className="muted" style={{ marginBottom: "12px" }}>
              No pull requests recorded for this repository yet.
            </p>
            <button className="button" onClick={handleSyncPullRequests} disabled={syncingPrs}>
              Sync Pull Requests from GitHub
            </button>
          </div>
        )}
      </div>

      <div className="detail-grid">
        <RecentAnalysesCard analyses={analyses} repositories={[repository]} />
        <aside className="card detail-card">
          <h2>Repository details</h2>
          <div className="stat-list">
            <div>
              <span>Owner</span>
              <strong>{repository.owner}</strong>
            </div>
            <div>
              <span>Clone URL</span>
              <strong>{repository.clone_url}</strong>
            </div>
            <div>
              <span>Organization</span>
              <strong>{repository.organization_id}</strong>
            </div>
          </div>
        </aside>
      </div>

      {triggerModalOpen && (
        <TriggerAnalysisModal
          repositories={[repository]}
          onClose={() => setTriggerModalOpen(false)}
          onSuccess={(id) => {
            setTriggerModalOpen(false);
            router.push(`/analyses/${id}`);
          }}
        />
      )}
    </>
  );
}

function TriggerAnalysisModal({
  repositories,
  onClose,
  onSuccess,
}: {
  repositories: Repository[];
  onClose: () => void;
  onSuccess: (newAnalysisId: string) => void;
}) {
  const [repositoryId, setRepositoryId] = useState(repositories[0]?.id ?? "");
  const selectedRepo = useMemo(
    () => repositories.find((r) => r.id === repositoryId) || repositories[0],
    [repositories, repositoryId],
  );
  const defaultSha = useMemo(() => {
    if (!selectedRepo?.branches?.length) return "";
    const def = selectedRepo.branches.find((b) => b.name === selectedRepo.default_branch);
    return def?.latest_commit_sha || selectedRepo.branches[0]?.latest_commit_sha || "";
  }, [selectedRepo]);

  const [commitSha, setCommitSha] = useState(defaultSha);
  const [pullRequestId, setPullRequestId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (defaultSha && !commitSha) {
      setCommitSha(defaultSha);
    }
  }, [defaultSha, commitSha]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!repositoryId) {
      setError("Please select a repository.");
      return;
    }
    if (!commitSha.trim()) {
      setError("Please enter a commit SHA.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await startAnalysis({
        repositoryId,
        commitSha: commitSha.trim(),
        pullRequestId: pullRequestId.trim() || undefined,
      });
      if (res.id) {
        onSuccess(res.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        className="card"
        style={{
          width: "520px",
          maxWidth: "92vw",
          padding: "24px",
          boxShadow: "0 20px 40px rgba(0,0,0,0.3)",
        }}
      >
        <h2 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: "8px" }}>
          <Play size={18} style={{ color: "var(--green)" }} />
          Trigger New Analysis
        </h2>
        <p className="muted" style={{ fontSize: "13px", marginBottom: "16px" }}>
          Run an AST Code Property Graph slice, predictive test selection, and confidence calculation for a commit or PR.
        </p>

        <form onSubmit={handleSubmit} style={{ display: "grid", gap: "14px" }}>
          <label style={{ display: "block" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
              Target Repository
            </span>
            <select
              value={repositoryId}
              onChange={(e) => setRepositoryId(e.target.value)}
              className="input"
              style={{
                width: "100%",
                padding: "8px 10px",
                borderRadius: "6px",
                background: "var(--card-bg, #1a221f)",
                color: "inherit",
                border: "1px solid var(--border)",
              }}
            >
              {repositories.map((repo) => (
                <option key={repo.id} value={repo.id ?? ""}>
                  {repo.full_name} ({repo.default_branch})
                </option>
              ))}
            </select>
          </label>

          {selectedRepo?.branches && selectedRepo.branches.length > 0 && (
            <label style={{ display: "block" }}>
              <span style={{ fontSize: "12px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
                Branch (Auto-fills latest commit)
              </span>
              <select
                onChange={(e) => {
                  const b = selectedRepo.branches?.find((branch) => branch.name === e.target.value);
                  if (b?.latest_commit_sha) setCommitSha(b.latest_commit_sha);
                }}
                defaultValue={selectedRepo.default_branch}
                className="input"
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  background: "var(--card-bg, #1a221f)",
                  color: "inherit",
                  border: "1px solid var(--border)",
                }}
              >
                {selectedRepo.branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name} {b.name === selectedRepo.default_branch ? "(Default Target)" : ""}{" "}
                    {b.latest_commit_sha ? `(${shortSha(b.latest_commit_sha)})` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label style={{ display: "block" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
              Commit SHA
            </span>
            <input
              type="text"
              value={commitSha}
              onChange={(e) => setCommitSha(e.target.value)}
              placeholder="e.g. 90bd4aa7439419186a85446f2aa05c23e3ba7103"
              required
              className="input"
              style={{
                width: "100%",
                padding: "8px 10px",
                borderRadius: "6px",
                background: "var(--card-bg, #1a221f)",
                color: "inherit",
                border: "1px solid var(--border)",
                fontFamily: "monospace",
                fontSize: "12px",
              }}
            />
          </label>

          <label style={{ display: "block" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
              Pull Request ID (optional)
            </span>
            <input
              type="text"
              value={pullRequestId}
              onChange={(e) => setPullRequestId(e.target.value)}
              placeholder="Auto-generated if left blank"
              className="input"
              style={{
                width: "100%",
                padding: "8px 10px",
                borderRadius: "6px",
                background: "var(--card-bg, #1a221f)",
                color: "inherit",
                border: "1px solid var(--border)",
                fontFamily: "monospace",
                fontSize: "12px",
              }}
            />
          </label>

          {error && (
            <p style={{ color: "var(--red)", fontSize: "12px", margin: "4px 0" }}>
              {error}
            </p>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "12px" }}>
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button"
              disabled={loading}
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
            >
              {loading ? (
                <>
                  <Loader2 size={14} className="spin" />
                  Starting Analysis...
                </>
              ) : (
                <>
                  <Play size={14} />
                  Start Verification Run
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function AnalysesData() {
  const [showModal, setShowModal] = useState(false);
  const router = useRouter();
  const state = useRadiusData(async () => {
    const [analyses, repositories] = await Promise.all([
      listAnalyses(),
      listRepositories(),
    ]);
    return { analyses, repositories };
  }, []);

  if (state.status === "loading") return <LoadingState label="Loading analyses" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "16px" }}>
        <button
          className="button"
          onClick={() => setShowModal(true)}
          type="button"
          style={{ display: "flex", alignItems: "center", gap: "8px" }}
        >
          <Play size={15} />
          Trigger New Analysis
        </button>
      </div>

      {state.data.analyses.length === 0 ? (
        <EmptyState
          title="No analyses yet"
          detail="Repository webhooks or manual runs will appear here."
        />
      ) : (
        <section className="card">
          <AnalysisTable
            analyses={state.data.analyses}
            repositories={state.data.repositories}
          />
        </section>
      )}

      {showModal && (
        <TriggerAnalysisModal
          repositories={state.data.repositories}
          onClose={() => setShowModal(false)}
          onSuccess={(id) => {
            setShowModal(false);
            router.push(`/analyses/${id}`);
          }}
        />
      )}
    </>
  );
}

function AnalysisTable({
  analyses,
  repositories,
}: {
  analyses: Analysis[];
  repositories: Repository[];
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Analysis</th>
            <th>Repository</th>
            <th>Status</th>
            <th>Commit</th>
            <th>Started</th>
            <th>Completed</th>
          </tr>
        </thead>
        <tbody>
          {analyses.map((analysis) => (
            <tr key={analysis.id ?? analysis.commit_sha}>
              <td>
                <Link
                  href={`/analyses/${analysis.id}`}
                  style={{ color: "inherit", fontWeight: 700, textDecoration: "none" }}
                >
                  {analysis.id}
                </Link>
                {analysis.pull_request_id ? (
                  <div className="subtext">
                    <Link
                      href={`/pull-requests/${analysis.pull_request_id}`}
                      style={{ color: "var(--accent)", textDecoration: "none" }}
                    >
                      PR ID: {shortSha(analysis.pull_request_id)}...
                    </Link>
                  </div>
                ) : (
                  <div className="subtext">No PR attached</div>
                )}
              </td>
              <td>{repositoryName(repositories, analysis.repository_id)}</td>
              <td>
                <Status status={analysis.status} />
              </td>
              <td>
                <code>{shortSha(analysis.commit_sha)}</code>
              </td>
              <td className="subtext">{formatDate(analysis.started_at)}</td>
              <td className="subtext">{formatDate(analysis.completed_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AnalysisDetailData({ analysisId }: { analysisId: string }) {
  const [rerunMessage, setRerunMessage] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const state = useRadiusData(async () => {
    const [analysis, repositories] = await Promise.all([
      getAnalysis(analysisId),
      listRepositories(),
    ]);
    const [blast, confidence, tests, graph, testResult] = await Promise.allSettled([
      getBlastRadius(analysisId),
      getConfidence(analysisId),
      getTests(analysisId),
      getGraph(analysisId),
      getTestRunResult(analysisId),
    ]);
    return {
      analysis,
      repositories,
      blast: settledValue(blast),
      confidence: settledValue(confidence),
      tests: settledValue(tests),
      graph: settledValue(graph),
      testResult: settledValue(testResult),
    };
  }, [analysisId, refreshKey]);

  async function runAgain() {
    try {
      const next = await rerunAnalysis(analysisId);
      setRerunMessage(`Queued rerun ${next.id}.`);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setRerunMessage(error instanceof Error ? error.message : String(error));
    }
  }

  if (state.status === "loading") return <LoadingState label="Loading analysis" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  const { analysis, repositories, blast, confidence, tests, graph, testResult } = state.data;
  const repo = repositoryName(repositories, analysis.repository_id);

  return (
    <>
      <PageHeading
        eyebrow={`Analysis / ${analysis.id}`}
        title="Pull request verification"
        description={`${repo} / PR ${analysis.pull_request_id}`}
        action={
          <button className="button secondary" onClick={() => void runAgain()} type="button">
            <RefreshCw size={15} />
            Re-run analysis
          </button>
        }
      />
      {rerunMessage && <p className="muted action-message">{rerunMessage}</p>}
      <section className="analysis-hero">
        <div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", marginBottom: "8px" }}>
            <Status status={analysis.status} />
            {confidence && (
              <span
                className="pr-chip"
                style={{ color: verdictPresentation(confidence.verification_status).color, fontWeight: 600 }}
              >
                {verdictPresentation(confidence.verification_status).label}
              </span>
            )}
            {confidence?.change_risk && (
              <span className="pr-chip">Change size risk: {confidence.change_risk.toLowerCase()}</span>
            )}
            {confidence?.analysis_completeness !== undefined && confidence?.analysis_completeness !== null && (
              <span className="pr-chip">
                Changed files with test evidence: {Math.round(confidence.analysis_completeness)}%
              </span>
            )}
          </div>
          <h2>{confidence?.summary ?? "Analysis artifacts are being prepared"}</h2>
          <p className="muted">
            Started {formatDate(analysis.started_at)} / completed{" "}
            {formatDate(analysis.completed_at)}
          </p>
        </div>
        <div style={{ textAlign: "center" }}>
          <ConfidenceRing score={score(confidence)} />
          <p className="muted" style={{ fontSize: "12px", marginTop: "6px" }}>
            Heuristic score (not a probability)
          </p>
        </div>
      </section>
      <VerdictGapsCard confidence={confidence} />
      <nav className="analysis-tabs">
        <a href="#summary">Summary</a>
        <a href="#impact">Blast radius</a>
        <a href="#tests">Tests & CI</a>
      </nav>
      <div className="detail-grid" id="summary">
        <ConfidenceEvidenceCard confidence={confidence} />
        <aside className="card detail-card">
          <h2>Recommendation</h2>
          <p className="muted">
            {confidence?.recommendations.join(" ") ||
              "Radius has not generated recommendations for this analysis yet."}
          </p>
        </aside>
      </div>

      <div id="impact" style={{ marginTop: "24px", display: "grid", gap: "20px" }}>
        <BlastRadiusVisualizerCard blast={blast} graph={graph} analysisId={analysisId} />
        {graph && graph.nodes.length > 0 && (
          <InteractiveGraphViewer
            nodes={graph.nodes}
            edges={graph.edges}
            title={`Interactive CPG Slice & Dependency Visualizer (${graph.node_count} nodes, ${graph.edge_count} edges)`}
            subtitle="Explore directly modified entrypoints, caller traversal, and targeted tests."
            height={520}
          />
        )}
      </div>


      <div id="tests" style={{ marginTop: "24px", display: "grid", gap: "20px" }}>
        <CiTestResultsCard
          testResult={testResult}
          analysisId={analysisId}
          onRefresh={() => setRefreshKey((k) => k + 1)}
        />
        <TestSelectionHub tests={tests} analysisId={analysisId} />
      </div>
    </>
  );
}

const GAP_FILE_LABELS: Record<string, string> = {
  unmapped_changed_file: "No test reaches this changed file",
  unanalyzed_changed_file: "File type Radius cannot analyze",
  parse_failure: "File could not be parsed",
  selected_test_not_in_results: "Selected test missing from CI results",
};

export function verdictPresentation(status?: string | null): { label: string; color: string } {
  switch ((status ?? "").toLowerCase()) {
    case "verified":
      return { label: "Verified", color: "#64C89D" };
    case "failed":
      return { label: "Failed", color: "#F87171" };
    default:
      return { label: "Not verified (insufficient evidence)", color: "#FBBF24" };
  }
}

function VerdictGapsCard({ confidence }: { confidence: ConfidenceReport | null }) {
  if (!confidence) return null;
  const gaps = confidence.evidence.filter(
    (item) => item.category === "analysis" && item.label === "verdict_gap",
  );
  const files = confidence.evidence.filter((item) => item.label in GAP_FILE_LABELS);
  if (gaps.length === 0 && files.length === 0) return null;
  return (
    <section className="card" style={{ marginBottom: "20px" }}>
      <div className="card-heading">
        <div>
          <h2>Why this is not verified</h2>
          <p>Radius only reports a change as verified when every changed file has passing test evidence.</p>
        </div>
      </div>
      {gaps.length > 0 && (
        <ul>
          {gaps.map((gap, index) => (
            <li key={`gap-${index}`}>{gap.message}</li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <div className="evidence">
          {files.map((item, index) => (
            <div className="evidence-row" key={`gap-file-${index}`}>
              <div>
                <strong>{item.message}</strong>
                <p>{GAP_FILE_LABELS[item.label]}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ConfidenceEvidenceCard({
  confidence,
}: {
  confidence: ConfidenceReport | null;
}) {
  return (
    <section className="card">
      <div className="card-heading">
        <div>
          <h2>
            <Sparkles size={16} className="inline-icon" />
            Confidence evidence
          </h2>
          <p>
            {confidence
              ? `Evidence behind the heuristic score of ${score(confidence)}/100`
              : "No confidence report is available yet"}
          </p>
        </div>
      </div>
      <div className="evidence">
        {confidence?.evidence.length ? (
          confidence.evidence.map((item, index) => {
            const isPositive = item.impact.toLowerCase() === "positive";
            return (
              <div className="evidence-row" key={`${item.category}-${item.label}-${index}`}>
                <div>
                  <strong>{item.label}</strong>
                  <p>{item.message}</p>
                </div>
                <span style={{ color: isPositive ? "var(--green)" : "var(--amber)" }}>
                  {item.impact}
                </span>
              </div>
            );
          })
        ) : (
          <p className="muted">Confidence evidence will appear after worker execution.</p>
        )}
      </div>
    </section>
  );
}

function BlastRadiusVisualizerCard({
  blast,
  graph,
  analysisId,
}: {
  blast: BlastRadius | null;
  graph: GraphSnapshot | null;
  analysisId: string;
}) {
  return (
    <section className="card detail-card">
      <div className="test-hub-header">
        <div>
          <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <FileCode2 size={18} style={{ color: "var(--green)" }} />
            Blast Radius & Dependency Slice
          </h2>
          <p className="muted">
            Transitive callers and impacted modules sliced from modified code property graphs.
          </p>
        </div>
        {blast && (
          <Link href={`/analyses/${analysisId}/blast-radius`} className="text-link">
            Explore blast radius <ArrowRight size={14} />
          </Link>
        )}
      </div>

      <div className="stat-list">
        <div>
          <span>Changed or affected files</span>
          <strong>{blast?.affected_files ?? "-"}</strong>
        </div>
        <div>
          <span>Affected symbols</span>
          <strong>{blast?.affected_symbols ?? "-"}</strong>
        </div>
        <div>
          <span>Affected modules</span>
          <strong>{blast?.affected_modules ?? "-"}</strong>
        </div>
        <div>
          <span>Dependency depth</span>
          <strong>{blast ? `${blast.dependency_depth} hops` : "-"}</strong>
        </div>
      </div>

      {graph && graph.nodes.length > 0 && (
        <div className="cpg-slice-card">
          <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: "8px", color: "var(--muted)" }}>
            CPG Dependency Slice Nodes ({graph.node_count} nodes, {graph.edge_count} edges)
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {graph.nodes.slice(0, 16).map((node) => {
              const isFile = node.node_type === "FILE" || node.node_type === "file";
              const isTest = node.label.includes("test") || (node.path && node.path.includes("test"));
              return (
                <span
                  key={node.id}
                  className={`cpg-node-chip ${isTest ? "test" : isFile ? "caller" : "modified"}`}
                  title={`${node.id} (${node.node_type})`}
                >
                  {node.label}
                </span>
              );
            })}
            {graph.nodes.length > 16 && (
              <span className="subtext" style={{ alignSelf: "center", marginLeft: "6px" }}>
                + {graph.nodes.length - 16} more nodes
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function CiTestResultsCard({
  testResult,
  analysisId,
  onRefresh,
}: {
  testResult: TestRunResult | null;
  analysisId: string;
  onRefresh: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [xmlInput, setXmlInput] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleUpload(payload: string, isXml: boolean) {
    setUploading(true);
    setErrorMsg(null);
    try {
      await uploadTestResults(analysisId, payload, isXml);
      setShowModal(false);
      setXmlInput("");
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const isXml = file.name.endsWith(".xml") || content.trim().startsWith("<");
      void handleUpload(content, isXml);
    };
    reader.readAsText(file);
  }

  const isPassed = testResult?.status?.toLowerCase() === "passed" || (testResult && testResult.failed === 0);

  return (
    <div className="card detail-card">
      <div className="test-hub-header">
        <div>
          <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <TestTube2 size={18} style={{ color: "var(--green)" }} />
            CI Test Execution Evidence
          </h2>
          <p className="muted">
            Ingested test execution reports from CI/CD runners (pytest, vitest, jest).
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => setShowModal(true)}
          type="button"
          style={{ fontSize: "12px", padding: "8px 12px" }}
        >
          <UploadCloud size={14} />
          Upload JUnit XML
        </button>
      </div>

      {testResult ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: "14px", margin: "14px 0" }}>
            <div className={`ci-status-badge ${isPassed ? "passed" : "failed"}`}>
              {isPassed ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
              {testResult.status.toUpperCase()}
            </div>
            <span className="muted" style={{ fontSize: "13px" }}>
              Executed in <strong>{testResult.duration_ms} ms</strong>
            </span>
          </div>

          <div className="metric-grid" style={{ marginBottom: "16px" }}>
            <Metric label="Total tests run" value={testResult.total_tests} />
            <Metric label="Passed" value={testResult.passed} />
            <Metric label="Failed" value={testResult.failed} />
            <Metric label="Skipped" value={testResult.skipped} />
          </div>

          {testResult.output && (
            <div style={{ marginTop: "14px" }}>
              <h3 style={{ fontSize: "13px", fontWeight: 700, margin: "0 0 6px" }}>
                Execution Trace & Failure Details
              </h3>
              <pre className="trace-box">{testResult.output}</pre>
            </div>
          )}
        </>
      ) : (
        <div style={{ padding: "18px 0", textAlign: "center" }}>
          <p className="muted" style={{ marginBottom: "12px" }}>
            No test run results ingested yet for this analysis.
          </p>
          <button
            className="button"
            onClick={() => setShowModal(true)}
            type="button"
            style={{ fontSize: "12px", padding: "8px 14px" }}
          >
            <UploadCloud size={14} />
            Ingest CI JUnit Report
          </button>
        </div>
      )}

      {showModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            className="card"
            style={{
              width: "540px",
              maxWidth: "92vw",
              padding: "24px",
              boxShadow: "0 20px 40px rgba(0,0,0,0.3)",
            }}
          >
            <h2 style={{ marginTop: 0 }}>Upload Test Results</h2>
            <p className="muted" style={{ fontSize: "12px", marginBottom: "14px" }}>
              Upload or paste a standard JUnit XML or JSON report to update the confidence score dynamically.
            </p>

            <label style={{ display: "block", marginBottom: "12px" }}>
              <span style={{ fontSize: "12px", fontWeight: 600 }}>Choose file (JUnit XML or JSON)</span>
              <input
                type="file"
                accept=".xml,.json"
                onChange={onFileChange}
                style={{ display: "block", marginTop: "6px" }}
                disabled={uploading}
              />
            </label>

            <div style={{ textAlign: "center", margin: "10px 0", color: "var(--muted)", fontSize: "11px" }}>
              — OR PASTE XML / JSON CONTENT —
            </div>

            <textarea
              rows={6}
              value={xmlInput}
              onChange={(e) => setXmlInput(e.target.value)}
              placeholder="<testsuite tests='3' failures='0'>..."
              style={{
                width: "100%",
                padding: "8px",
                fontFamily: "monospace",
                fontSize: "12px",
                borderRadius: "6px",
                border: "1px solid var(--line)",
                marginBottom: "12px",
              }}
              disabled={uploading}
            />

            {errorMsg && (
              <p style={{ color: "#D33D22", fontSize: "12px", marginBottom: "12px" }}>
                {errorMsg}
              </p>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                className="button secondary"
                onClick={() => setShowModal(false)}
                type="button"
                disabled={uploading}
              >
                Cancel
              </button>
              <button
                className="button"
                onClick={() => {
                  const isXml = xmlInput.trim().startsWith("<");
                  void handleUpload(xmlInput, isXml);
                }}
                disabled={uploading || !xmlInput.trim()}
                type="button"
              >
                {uploading ? <Loader2 size={14} className="spin" /> : "Submit Report"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TestSelectionHub({
  tests,
  analysisId,
}: {
  tests: TestSelection | null;
  analysisId: string;
}) {
  const [activeTab, setActiveTab] = useState<"pytest" | "vitest" | "jest">("pytest");
  const [copied, setCopied] = useState(false);

  const apiBase = radiusConfig.apiBaseUrl.replace(/\/$/, "");
  const cliUrl = `${apiBase}/api/v1/analyses/${analysisId}/tests?format=cli`;

  const commands = {
    pytest: `pytest $(curl -s "${cliUrl}")`,
    vitest: `vitest run $(curl -s "${cliUrl}")`,
    jest: `jest $(curl -s "${cliUrl}")`,
  };

  function copyCommand() {
    navigator.clipboard.writeText(commands[activeTab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const selectedCount = tests?.selected_count ?? 0;
  const skippedCount = tests?.skipped_count ?? 0;
  const totalCount = tests?.total_count ?? (selectedCount + skippedCount);

  return (
    <div className="card detail-card">
      <div className="test-hub-header">
        <div>
          <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Zap size={18} style={{ color: "var(--green)" }} />
            Predictive Test Selection
          </h2>
          <p className="muted">
            Targeted test execution derived from sliced AST and CPG dependencies.
          </p>
        </div>
        {totalCount > 0 && (
          <span className="savings-pill">
            <Zap size={14} />
            {selectedCount} of {totalCount} test files selected
          </span>
        )}
      </div>

      <div className="metric-grid" style={{ marginBottom: "16px" }}>
        <Metric label="Selected for run" value={selectedCount} />
        <Metric label="Not selected" value={skippedCount} />
        <Metric label="Discovered in repo" value={totalCount} />
      </div>

      <div className="cli-box">
        <div className="cli-box-header">
          <div className="cli-tabs">
            {(["pytest", "vitest", "jest"] as const).map((tab) => (
              <button
                key={tab}
                className={`cli-tab ${activeTab === tab ? "active" : ""}`}
                onClick={() => setActiveTab(tab)}
                type="button"
              >
                {tab}
              </button>
            ))}
          </div>
          <button className="copy-btn" onClick={copyCommand} type="button">
            {copied ? <Check size={13} style={{ color: "#64C89D" }} /> : <Copy size={13} />}
            {copied ? "Copied!" : "Copy command"}
          </button>
        </div>
        <pre className="cli-command">
          <code>{commands[activeTab]}</code>
        </pre>
      </div>

      <h3 style={{ fontSize: "14px", margin: "16px 0 8px" }}>
        Selected Tests ({selectedCount})
      </h3>
      {tests?.selected_tests && tests.selected_tests.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Test file</th>
                <th>Framework</th>
                <th>Selection rationale</th>
              </tr>
            </thead>
            <tbody>
              {tests.selected_tests.map((item, idx) => (
                <tr key={idx}>
                  <td>
                    <strong>{item.test.name}</strong>
                    <div className="subtext">{item.test.path}</div>
                  </td>
                  <td>
                    <code>{item.test.framework}</code>
                  </td>
                  <td>
                    <span className="reason-tag">{item.reason}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted" style={{ padding: "8px 0" }}>
          No tests selected for this analysis.
        </p>
      )}

      {tests?.skipped_tests && tests.skipped_tests.length > 0 && (
        <details style={{ marginTop: "16px", cursor: "pointer" }}>
          <summary style={{ fontSize: "13px", fontWeight: 700, color: "var(--muted)" }}>
            View {tests.skipped_tests.length} Tests not selected for this change
          </summary>
          <div className="table-wrap" style={{ marginTop: "10px" }}>
            <table>
              <thead>
                <tr>
                  <th>Skipped test path</th>
                  <th>Framework</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {tests.skipped_tests.map((test, idx) => (
                  <tr key={idx}>
                    <td>
                      <code>{test.path}</code>
                    </td>
                    <td>{test.framework}</td>
                    <td>
                      <span className="reason-tag skipped">Skipped (Benign)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

export function BlastRadiusData({ analysisId }: { analysisId: string }) {
  const state = useRadiusData(async () => {
    const [blast, graph, analysis] = await Promise.all([
      getBlastRadius(analysisId),
      getGraph(analysisId).catch(() => null),
      getAnalysis(analysisId).catch(() => null),
    ]);
    return { blast, graph, analysis };
  }, [analysisId]);

  if (state.status === "loading") return <LoadingState label="Loading blast radius" />;
  if (state.status === "error") return <ErrorState message={state.error} />;
  const { blast, graph, analysis } = state.data;
  const rows = [
    ["Affected files", blast.affected_files],
    ["Affected symbols", blast.affected_symbols],
    ["Affected modules", blast.affected_modules],
    ["Affected tests", blast.affected_tests],
    ["Dependency depth", blast.dependency_depth],
  ];
  return (
    <>
      <PageHeading
        eyebrow={`Analysis / ${analysisId}`}
        title="Blast radius & CPG slice"
        description="Deterministic dependency traversal and AST semantic impact."
      />
      <section className="metric-grid">
        {rows.slice(0, 4).map(([label, value]) => (
          <Metric key={label} label={String(label)} value={String(value)} />
        ))}
      </section>

      {analysis?.changed_files && analysis.changed_files.length > 0 && (
        <section className="card" style={{ marginBottom: "24px" }}>
          <div className="card-heading">
            <div>
              <h2>Directly Modified Files ({analysis.changed_files.length})</h2>
              <p>Git diff hunks identified in Pull Request</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File path</th>
                  <th>Change type</th>
                  <th>Additions</th>
                  <th>Deletions</th>
                </tr>
              </thead>
              <tbody>
                {analysis.changed_files.map((file) => (
                  <tr key={file.path}>
                    <td>
                      <code>{file.path}</code>
                    </td>
                    <td>
                      <span className="reason-tag">{file.change_type}</span>
                    </td>
                    <td style={{ color: "var(--green)", fontWeight: 700 }}>+{file.additions}</td>
                    <td style={{ color: "var(--amber)", fontWeight: 700 }}>-{file.deletions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {graph && graph.nodes.length > 0 ? (
        <section style={{ marginBottom: "24px" }}>
          <InteractiveGraphViewer
            nodes={graph.nodes}
            edges={graph.edges}
            title={`Interactive CPG Slice & Dependency Visualizer (${graph.node_count} nodes, ${graph.edge_count} edges)`}
            subtitle="Explore directly modified entrypoints, caller traversal, and targeted tests."
            height={580}
          />
        </section>
      ) : null}



      <section className="card">
        <div className="card-heading">
          <h2>Blast Radius Signal Breakdown</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Signal</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label}>
                  <td>
                    <strong>{label}</strong>
                  </td>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function GraphOverviewData() {
  const state = useRadiusData(async () => {
    const analyses = await listAnalyses();
    const latest = analyses.find((analysis) => analysis.id);
    const graph = latest?.id ? await getGraph(latest.id) : null;
    return { latest, graph };
  }, []);
  if (state.status === "loading") return <LoadingState label="Loading dependency graph" />;
  if (state.status === "error") return <ErrorState message={state.error} />;
  if (!state.data.latest || !state.data.graph) {
    return (
      <EmptyState
        title="No dependency graph available"
        detail="Run an analysis with worker execution to build graph artifacts."
      />
    );
  }
  return <GraphCard graph={state.data.graph} />;
}

function GraphCard({ graph }: { graph: GraphSnapshot }) {
  return (
    <InteractiveGraphViewer
      nodes={graph.nodes}
      edges={graph.edges}
      title="Dependency Graph & Module Relationships"
      subtitle={`Snapshot version ${graph.graph_version} / created ${formatDate(graph.created_at)} (${graph.node_count} nodes, ${graph.edge_count} edges)`}
      height={600}
    />
  );
}


export function SearchData() {
  const [query, setQuery] = useState("");
  const state = useRadiusData(async () => {
    const [analyses, repositories] = await Promise.all([
      listAnalyses(),
      listRepositories(),
    ]);
    return { analyses, repositories };
  }, []);

  const results = useMemo(() => {
    if (state.status !== "ready") return [];
    const lower = query.toLowerCase();
    return state.data.analyses.filter((analysis) => {
      const repo = repositoryName(state.data.repositories, analysis.repository_id);
      return [analysis.id, analysis.commit_sha, analysis.status, repo]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(lower));
    });
  }, [query, state]);

  if (state.status === "loading") return <LoadingState label="Loading search index" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  return (
    <>
      <div className="card detail-card">
        <div className="search boxed-search">
          <Search size={18} />
          <input
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by analysis ID, commit, status, or repository"
            value={query}
          />
        </div>
      </div>
      <section className="card wide-card">
        <AnalysisTable analyses={results} repositories={state.data.repositories} />
      </section>
    </>
  );
}

export function PullRequestData({ pullRequestId }: { pullRequestId: string }) {
  const isUuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      pullRequestId,
    );
  const cleanNumber = pullRequestId.replace(/^#/, "");
  const isNumeric = /^\d+$/.test(cleanNumber);

  const state = useRadiusData(async () => {
    if (isUuid) {
      const [analyses, repositories] = await Promise.all([
        listAnalyses({ pullRequestId }),
        listRepositories(),
      ]);
      let resolvedPr: PullRequest | null = null;
      if (analyses.length > 0 && analyses[0].repository_id) {
        try {
          const prs = await listPullRequests(analyses[0].repository_id);
          resolvedPr = prs.find((p) => p.id === pullRequestId) || null;
        } catch {}
      }
      return { analyses, repositories, pr: resolvedPr };
    }
    if (isNumeric) {
      const repositories = await listRepositories();
      const prNumber = parseInt(cleanNumber, 10);
      for (const repo of repositories) {
        if (!repo.id) continue;
        try {
          const pr = await getPullRequestByNumber(repo.id, prNumber);
          if (pr && pr.id) {
            const analyses = await listAnalyses({ pullRequestId: pr.id });
            return { analyses, repositories, pr };
          }
        } catch {
          // Continue checking other connected repositories
        }
      }
      return { analyses: [], repositories, pr: null };
    }
    return { analyses: [], repositories: [], pr: null };
  }, [pullRequestId, isUuid, isNumeric, cleanNumber]);

  if (state.status === "loading") return <LoadingState label="Loading pull request analyses" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  const { analyses, repositories, pr } = state.data;
  const pageTitle = pr?.title || (isNumeric ? `PR #${cleanNumber} analyses` : "Pull request analyses");
  const subtitle = pr
    ? `Route: ${pr.source_branch} → ${pr.target_branch} • Author: ${pr.author} • Status: ${pr.status}`
    : "Verification runs and blast radius records associated with this pull request.";

  return (
    <>
      <PageHeading
        eyebrow={`Pull request / ${pr ? `#${pr.github_pr_number}` : (isNumeric ? `#${cleanNumber}` : pullRequestId)}`}
        title={pageTitle}
        description={subtitle}
        action={
          <div style={{ display: "flex", gap: "10px" }}>
            {pr && (
              <button
                className="button"
                onClick={async () => {
                  if (analyses[0]?.repository_id && analyses[0]?.commit_sha) {
                    const res = await startAnalysis({
                      repositoryId: analyses[0].repository_id,
                      commitSha: analyses[0].commit_sha,
                      pullRequestId: pr.id,
                    });
                    if (res.id) window.location.href = `/analyses/${res.id}`;
                  }
                }}
                style={{ display: "flex", alignItems: "center", gap: "6px" }}
              >
                <Play size={14} />
                Re-run Verification
              </button>
            )}
            <Link href="/repositories" className="button secondary">
              <FolderGit2 size={15} />
              All repositories
            </Link>
          </div>
        }
      />

      <section className="metric-grid" style={{ marginBottom: "16px" }}>
        <Metric label="GitHub PR Number" value={pr ? `#${pr.github_pr_number}` : (isNumeric ? `#${cleanNumber}` : "-")} />
        <Metric label="Radius PR UUID" value={pr?.id ? pr.id.slice(0, 8) + "..." : (isUuid ? pullRequestId.slice(0, 8) + "..." : "-")} />
        <Metric label="Status" value={pr?.status ?? "unknown"} />
        <Metric label="Verification Runs" value={analyses.length} />
      </section>

      {pr && (
        <div className="card" style={{ marginBottom: "16px", padding: "14px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <div style={{ display: "flex", gap: "20px", alignItems: "center", flexWrap: "wrap", fontSize: "13px" }}>
            <div>
              <span className="muted">Full Radius PR ID: </span>
              <code style={{ fontSize: "12px", background: "rgba(255,255,255,0.06)", padding: "2px 6px", borderRadius: "4px" }}>{pr.id}</code>
            </div>
            <div>
              <span className="muted">GitHub Number: </span>
              <strong>#{pr.github_pr_number}</strong>
            </div>
            <div>
              <span className="muted">Branch: </span>
              <code>{pr.source_branch}</code> → <code>{pr.target_branch}</code>
            </div>
          </div>
        </div>
      )}
      {analyses.length === 0 ? (
        <EmptyState
          title="No analyses found for this pull request"
          detail={
            isNumeric
              ? `No verification runs have been registered yet for PR #${cleanNumber}. Open a pull request or push a commit to trigger analysis.`
              : "A GitHub webhook or manual analysis will create the first record."
          }
        />
      ) : (
        <section className="card">
          <AnalysisTable analyses={analyses} repositories={repositories} />
        </section>
      )}
    </>
  );
}

export function SettingsData() {
  return (
    <>
      <PageHeading
        title="Settings"
        description="Runtime configuration used by the dashboard API client."
      />
      <div className="detail-grid">
        <section className="card detail-card">
          <h2>API connection</h2>
          <div className="stat-list">
            <div>
              <span>API base URL</span>
              <strong>{radiusConfig.apiBaseUrl}</strong>
            </div>
            <div>
              <span>Organization header</span>
              <strong>{radiusConfig.organizationId || "Missing"}</strong>
            </div>
            <div>
              <span>API key</span>
              <strong>{radiusConfig.apiKey ? "Configured" : "Not configured"}</strong>
            </div>
          </div>
        </section>
        <section className="card detail-card">
          <h2>Required environment</h2>
          <p className="muted">
            Set <code>NEXT_PUBLIC_RADIUS_API_BASE_URL</code> and{" "}
            <code>NEXT_PUBLIC_RADIUS_ORGANIZATION_ID</code> before running the
            dashboard against a real backend.
          </p>
        </section>
      </div>
    </>
  );
}

export function CompareData() {
  const state = useRadiusData(async () => {
    const analyses = (await listAnalyses()).filter((analysis) => analysis.id).slice(0, 2);
    const artifacts = await Promise.all(
      analyses.map(async (analysis) => {
        const [confidence, blast, tests] = await Promise.allSettled([
          getConfidence(analysis.id as string),
          getBlastRadius(analysis.id as string),
          getTests(analysis.id as string),
        ]);
        return {
          analysis,
          confidence: settledValue(confidence),
          blast: settledValue(blast),
          tests: settledValue(tests),
        };
      }),
    );
    return artifacts;
  }, []);

  if (state.status === "loading") return <LoadingState label="Loading comparison" />;
  if (state.status === "error") return <ErrorState message={state.error} />;
  if (state.data.length < 2) {
    return (
      <EmptyState
        title="Need two analyses"
        detail="Radius can compare verification evidence after at least two analyses exist."
      />
    );
  }

  const [left, right] = state.data;
  const rows = [
    [
      "Confidence score",
      left.confidence ? `${score(left.confidence)} / 100` : "-",
      right.confidence ? `${score(right.confidence)} / 100` : "-",
    ],
    [
      "Risk level",
      left.confidence?.risk_level ?? "-",
      right.confidence?.risk_level ?? "-",
    ],
    [
      "Affected files",
      String(left.blast?.affected_files ?? "-"),
      String(right.blast?.affected_files ?? "-"),
    ],
    [
      "Affected tests",
      String(left.blast?.affected_tests ?? "-"),
      String(right.blast?.affected_tests ?? "-"),
    ],
    [
      "Selected tests",
      String(left.tests?.selected_count ?? "-"),
      String(right.tests?.selected_count ?? "-"),
    ],
  ];

  return (
    <section className="card">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Verification signal</th>
              <th>{left.analysis.id}</th>
              <th>{right.analysis.id}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, leftValue, rightValue]) => (
              <tr key={label}>
                <td>
                  <strong>{label}</strong>
                </td>
                <td>{leftValue}</td>
                <td>{rightValue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function PullRequestsOverviewData() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [pullRequests, setPullRequests] = useState<{ pr: PullRequest; repo: Repository }[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [reposResult, analysesResult] = await Promise.all([
        listRepositories(),
        listAnalyses().catch(() => [] as Analysis[]),
      ]);
      setRepositories(reposResult);
      setAnalyses(analysesResult);

      const prPromises = reposResult.map(async (repo) => {
        if (!repo.id) return [];
        try {
          const prs = await listPullRequests(repo.id);
          return prs.map((pr) => ({ pr, repo }));
        } catch {
          return [];
        }
      });

      const settledPRs = await Promise.all(prPromises);
      const allPRs = settledPRs.flat();
      allPRs.sort((a, b) => new Date(b.pr.opened_at).getTime() - new Date(a.pr.opened_at).getTime());
      setPullRequests(allPRs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load pull requests.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSyncAll = async () => {
    try {
      setSyncing(true);
      await Promise.all(
        repositories
          .filter((repo): repo is Repository & { id: string } => Boolean(repo.id))
          .map((repo) => syncPullRequests(repo.id).catch(() => []))
      );
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sync pull requests.");
    } finally {
      setSyncing(false);
    }
  };

  const copyToClipboard = (id: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(id);
    }
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (loading) return <LoadingState label="Loading pull requests across repositories" />;
  if (error && pullRequests.length === 0) return <ErrorState message={error} />;

  const filtered = pullRequests.filter(({ pr, repo }) => {
    if (statusFilter !== "all" && pr.status !== statusFilter) return false;
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      pr.title.toLowerCase().includes(q) ||
      String(pr.github_pr_number).includes(q) ||
      pr.id.toLowerCase().includes(q) ||
      pr.author.toLowerCase().includes(q) ||
      repo.name.toLowerCase().includes(q) ||
      pr.source_branch.toLowerCase().includes(q) ||
      pr.target_branch.toLowerCase().includes(q)
    );
  });

  const openCount = pullRequests.filter((p) => p.pr.status === "open").length;
  const mergedCount = pullRequests.filter((p) => p.pr.status === "merged").length;

  return (
    <div style={{ display: "grid", gap: "24px" }}>
      <section className="metric-grid">
        <Metric label="Total Pull Requests" value={pullRequests.length} />
        <Metric label="Open PRs" value={openCount} />
        <Metric label="Merged PRs" value={mergedCount} />
        <Metric label="Tracked Repositories" value={repositories.length} />
      </section>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div style={{ display: "flex", gap: "10px", alignItems: "center", flex: "1 1 300px", flexWrap: "wrap" }}>
          <div style={{ position: "relative", width: "100%", maxWidth: "360px" }}>
            <Search size={16} style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)", color: "var(--muted)" }} />
            <input
              type="text"
              placeholder="Search by title, #number, Radius UUID, author..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input"
              style={{ paddingLeft: "34px", width: "100%" }}
            />
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            {(["all", "open", "merged", "closed"] as const).map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => setStatusFilter(status)}
                className={`button ${statusFilter === status ? "primary" : "secondary"}`}
                style={{ padding: "6px 12px", fontSize: "12px", textTransform: "capitalize" }}
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleSyncAll}
          disabled={syncing}
          className="button secondary"
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
        >
          <RefreshCw size={14} className={syncing ? "spin" : ""} />
          {syncing ? "Syncing PRs..." : "Sync Open PRs from GitHub"}
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title={pullRequests.length === 0 ? "No pull requests found" : "No matching pull requests"}
          detail={
            pullRequests.length === 0
              ? "Connect a repository and open pull requests on GitHub or click 'Sync Open PRs from GitHub' above to discover them."
              : "Try adjusting your search query or status filter."
          }
        />
      ) : (
        <section className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pull Request & IDs</th>
                  <th>Repository</th>
                  <th>Branch Route</th>
                  <th>Author</th>
                  <th>Status</th>
                  <th>Verification</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(({ pr, repo }) => {
                  const matchingAnalysis = analyses.find(
                    (a) => a.pull_request_id === pr.id || a.commit_sha === pr.source_branch
                  );
                  return (
                    <tr key={pr.id}>
                      <td>
                        <div style={{ display: "grid", gap: "4px" }}>
                          <Link
                            href={`/pull-requests/${pr.id}`}
                            style={{ fontWeight: 600, color: "var(--foreground)", textDecoration: "none" }}
                          >
                            #{pr.github_pr_number} {pr.title}
                          </Link>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <span
                              title={`Full Radius PR UUID: ${pr.id}`}
                              style={{
                                fontSize: "11px",
                                padding: "1px 6px",
                                borderRadius: "4px",
                                background: "rgba(255, 255, 255, 0.06)",
                                border: "1px solid var(--border)",
                                fontFamily: "monospace",
                                color: "var(--muted)",
                              }}
                            >
                              UUID: {pr.id.slice(0, 8)}...
                            </span>
                            <button
                              type="button"
                              onClick={() => copyToClipboard(pr.id)}
                              title="Copy full Radius PR UUID"
                              style={{
                                background: "transparent",
                                border: "none",
                                padding: "2px",
                                cursor: "pointer",
                                color: copiedId === pr.id ? "var(--green, #22c55e)" : "var(--muted)",
                              }}
                            >
                              {copiedId === pr.id ? <Check size={12} /> : <Copy size={12} />}
                            </button>
                          </div>
                        </div>
                      </td>
                      <td>
                        <Link
                          href={`/repositories/${repo.id}`}
                          style={{ color: "var(--accent)", textDecoration: "none" }}
                        >
                          {repo.full_name || repo.name}
                        </Link>
                      </td>
                      <td>
                        <span style={{ fontSize: "12px", fontFamily: "monospace" }}>
                          <code>{pr.source_branch}</code> → <code>{pr.target_branch}</code>
                        </span>
                      </td>
                      <td>
                        <span style={{ fontSize: "13px" }}>{pr.author}</span>
                      </td>
                      <td>
                        <span
                          style={{
                            fontSize: "11px",
                            padding: "2px 8px",
                            borderRadius: "10px",
                            textTransform: "capitalize",
                            background:
                              pr.status === "open"
                                ? "rgba(34, 197, 94, 0.15)"
                                : pr.status === "merged"
                                ? "rgba(168, 85, 247, 0.15)"
                                : "rgba(156, 163, 175, 0.15)",
                            color:
                              pr.status === "open"
                                ? "var(--green, #22c55e)"
                                : pr.status === "merged"
                                ? "#c084fc"
                                : "#9ca3af",
                          }}
                        >
                          {pr.status}
                        </span>
                      </td>
                      <td>
                        {matchingAnalysis ? (
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <Status status={matchingAnalysis.status} />
                            <Link
                              href={`/analyses/${matchingAnalysis.id}`}
                              className="button secondary"
                              style={{ padding: "4px 8px", fontSize: "11px" }}
                            >
                              View Run
                            </Link>
                          </div>
                        ) : (
                          <Link
                            href={`/pull-requests/${pr.id}`}
                            className="button secondary"
                            style={{ padding: "4px 8px", fontSize: "11px" }}
                          >
                            Verify
                          </Link>
                        )}
                      </td>
                      <td className="subtext" style={{ fontSize: "12px" }}>
                        {formatDate(pr.opened_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

