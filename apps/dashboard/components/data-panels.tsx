"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  FileCode2,
  FolderGit2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  TestTube2,
  Trash2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  Analysis,
  BlastRadius,
  ConfidenceReport,
  ConnectRepositoryPayload,
  GraphSnapshot,
  Repository,
  TestSelection,
  connectRepository,
  disconnectRepository,
  getAnalysis,
  getBlastRadius,
  getConfidence,
  getGraph,
  getRepository,
  getTests,
  listAnalyses,
  listRepositories,
  radiusConfig,
  rerunAnalysis,
} from "../lib/api";
import { ConfidenceRing, OpenLink, PageHeading, Status } from "./ui";

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
  const state = useRadiusData(async () => {
    const repository = await getRepository(repositoryId);
    const analyses = await listAnalyses({ repositoryId });
    return { repository, analyses };
  }, [repositoryId]);

  if (state.status === "loading") return <LoadingState label="Loading repository" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  const { repository, analyses } = state.data;
  return (
    <>
      <PageHeading
        eyebrow={`Repository / ${repository.provider}`}
        title={repository.full_name}
        description={`${repository.visibility} / ${repository.status}`}
        action={<Status status={repository.status} />}
      />
      <section className="metric-grid">
        <Metric label="Default branch" value={repository.default_branch} />
        <Metric label="Analyses" value={analyses.length} />
        <Metric label="Branches indexed" value={repository.branches?.length ?? 0} />
        <Metric label="GitHub repo ID" value={repository.github_repository_id} />
      </section>
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
    </>
  );
}

export function AnalysesData() {
  const state = useRadiusData(async () => {
    const [analyses, repositories] = await Promise.all([
      listAnalyses(),
      listRepositories(),
    ]);
    return { analyses, repositories };
  }, []);

  if (state.status === "loading") return <LoadingState label="Loading analyses" />;
  if (state.status === "error") return <ErrorState message={state.error} />;

  return state.data.analyses.length === 0 ? (
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
                <div className="subtext">PR {analysis.pull_request_id}</div>
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
    const [blast, confidence, tests, graph] = await Promise.allSettled([
      getBlastRadius(analysisId),
      getConfidence(analysisId),
      getTests(analysisId),
      getGraph(analysisId),
    ]);
    return {
      analysis,
      repositories,
      blast: settledValue(blast),
      confidence: settledValue(confidence),
      tests: settledValue(tests),
      graph: settledValue(graph),
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

  const { analysis, repositories, blast, confidence, tests, graph } = state.data;
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
          <Status status={analysis.status} />
          <h2>{confidence?.summary ?? "Analysis artifacts are being prepared"}</h2>
          <p className="muted">
            Started {formatDate(analysis.started_at)} / completed{" "}
            {formatDate(analysis.completed_at)}
          </p>
        </div>
        <ConfidenceRing score={score(confidence)} />
      </section>
      <nav className="analysis-tabs">
        <a href="#summary">Summary</a>
        <a href="#impact">Blast radius</a>
        <a href="#tests">Tests</a>
        <a href="#graph">Dependencies</a>
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
      <AnalysisArtifacts blast={blast} tests={tests} graph={graph} />
    </>
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
          <h2>Confidence evidence</h2>
          <p>
            {confidence
              ? `Why Radius scored this ${score(confidence)}/100`
              : "No confidence report is available yet"}
          </p>
        </div>
      </div>
      <div className="evidence">
        {confidence?.evidence.length ? (
          confidence.evidence.map((item) => (
            <div className="evidence-row" key={`${item.category}-${item.label}`}>
              <div>
                <strong>{item.label}</strong>
                <p>{item.message}</p>
              </div>
              <span>{item.impact}</span>
            </div>
          ))
        ) : (
          <p className="muted">Confidence evidence will appear after worker execution.</p>
        )}
      </div>
    </section>
  );
}

function AnalysisArtifacts({
  blast,
  tests,
  graph,
}: {
  blast: BlastRadius | null;
  tests: TestSelection | null;
  graph: GraphSnapshot | null;
}) {
  return (
    <div className="detail-grid wide-card" id="impact">
      <section className="card detail-card">
        <h2>
          <FileCode2 className="inline-icon" size={17} />
          Blast radius
        </h2>
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
        {blast && (
          <Link href={`/analyses/${blast.analysis_id}/blast-radius`} className="text-link">
            Explore blast radius <ArrowRight size={14} />
          </Link>
        )}
      </section>
      <section className="card detail-card" id="tests">
        <h2>
          <TestTube2 className="inline-icon" size={17} />
          Targeted validation
        </h2>
        <div className="stat-list">
          <div>
            <span>Selected tests</span>
            <strong>{tests?.selected_count ?? "-"}</strong>
          </div>
          <div>
            <span>Graph nodes</span>
            <strong>{graph?.node_count ?? "-"}</strong>
          </div>
          <div>
            <span>Graph edges</span>
            <strong>{graph?.edge_count ?? "-"}</strong>
          </div>
        </div>
      </section>
    </div>
  );
}

export function BlastRadiusData({ analysisId }: { analysisId: string }) {
  const state = useRadiusData(() => getBlastRadius(analysisId), [analysisId]);
  if (state.status === "loading") return <LoadingState label="Loading blast radius" />;
  if (state.status === "error") return <ErrorState message={state.error} />;
  const blast = state.data;
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
        title="Blast radius"
        description="Deterministic dependency traversal from backend analysis artifacts."
      />
      <section className="metric-grid">
        {rows.slice(0, 4).map(([label, value]) => (
          <Metric key={label} label={String(label)} value={String(value)} />
        ))}
      </section>
      <section className="card">
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
  const visibleNodes = graph.nodes.slice(0, 8);
  return (
    <section className="card">
      <div className="card-heading">
        <div>
          <h2>Module relationships</h2>
          <p>
            Version {graph.graph_version} / created {formatDate(graph.created_at)}
          </p>
        </div>
        <span className="status positive">
          {graph.node_count} nodes / {graph.edge_count} edges
        </span>
      </div>
      <div className="graph-canvas">
        {visibleNodes.map((node, index) => (
          <div
            className={`node ${index === 0 ? "active" : ""}`}
            key={node.id}
            style={{
              left: `${40 + (index % 4) * 190}px`,
              top: `${80 + Math.floor(index / 4) * 150}px`,
            }}
          >
            {node.label}
          </div>
        ))}
      </div>
      <div className="graph-legend">
        <span>
          <i className="legend-dot" />
          Backend graph snapshot
        </span>
        <span>Edges are available from the graph API response.</span>
      </div>
    </section>
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
  const state = useRadiusData(
    () => (isUuid ? listAnalyses({ pullRequestId }) : Promise.resolve([])),
    [pullRequestId, isUuid],
  );
  if (state.status === "loading") return <LoadingState label="Loading pull request analyses" />;
  if (state.status === "error") return <ErrorState message={state.error} />;
  return (
    <>
      <PageHeading
        eyebrow={`Pull request / ${pullRequestId}`}
        title="Pull request analyses"
        description="Radius currently exposes pull request history through analysis records."
        action={
          <Link href="/repositories" className="button secondary">
            <Play size={15} />
            Choose repository
          </Link>
        }
      />
      {state.data.length === 0 ? (
        <EmptyState
          title={isUuid ? "No analyses for this pull request" : "Backend UUID required"}
          detail={
            isUuid
              ? "A GitHub webhook or manual analysis will create the first record."
              : "Phase 1 stores pull request references by internal UUID. GitHub PR-number lookup needs a backend endpoint before this page can resolve numeric PR URLs."
          }
        />
      ) : (
        <section className="card">
          <AnalysisTable analyses={state.data} repositories={[]} />
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
