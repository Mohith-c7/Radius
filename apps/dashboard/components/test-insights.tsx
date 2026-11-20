"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, ExternalLink } from "lucide-react";

import { listAnalyses, listRepositories, type Analysis, type Repository } from "../lib/api";
import { getFlakyTests, getRecentExecutions, getTestStatistics, RECENT_LIMIT } from "../lib/test-insights";
import {
  CI_GUIDE_URL,
  analysisForCommit,
  anchorAnalysis,
  formatDuration,
  formatPercent,
  groupRuns,
  historyForTest,
  shortSha,
  sortNewestFirst,
  statusKind,
  summarizeExecutions,
  summarizeTests,
  testKey,
  type FlakyTestsReport,
  type TestExecution,
  type TestStatistics,
} from "../lib/test-insights-model";
import "./test-insights.css";

type RepoData = {
  analyses: Analysis[];
  recent: TestExecution[];
  flaky: FlakyTestsReport | null;
  statistics: TestStatistics | null;
  statisticsAnalysisId: string | null;
  partialError: string | null;
};

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Unknown error.";
}

function StatusPill({ status }: { status: string }) {
  return <span className={`ti-pill ${statusKind(status)}`}>{status || "unknown"}</span>;
}

function GuideLink({ label = "CI integration guide" }: { label?: string }) {
  return (
    <a className="text-link" href={CI_GUIDE_URL} target="_blank" rel="noopener noreferrer">
      {label} <ExternalLink size={14} />
    </a>
  );
}

function StateCard({ title, children, error = false }: { title: string; children: React.ReactNode; error?: boolean }) {
  return (
    <div className={`card detail-card state-card${error ? " error-state" : ""}`}>
      {error && <AlertCircle size={18} />}
      <strong>{title}</strong>
      {children}
    </div>
  );
}

async function loadRepoData(repositoryId: string): Promise<RepoData> {
  const analyses = await listAnalyses({ repositoryId, limit: 100 });
  const anchor = anchorAnalysis(analyses.map((a) => ({ ...a, id: a.id ?? null })));
  if (!anchor?.id) {
    return { analyses, recent: [], flaky: null, statistics: null, statisticsAnalysisId: null, partialError: null };
  }
  const [recent, flaky] = await Promise.allSettled([
    getRecentExecutions(anchor.id, repositoryId),
    getFlakyTests(anchor.id),
  ]);
  const recentRows = recent.status === "fulfilled" ? recent.value : [];
  const errors: string[] = [];
  if (recent.status === "rejected") errors.push(`Recent runs: ${message(recent.reason)}`);
  if (flaky.status === "rejected") errors.push(`Flaky tests: ${message(flaky.reason)}`);

  let statistics: TestStatistics | null = null;
  const newest = sortNewestFirst(recentRows)[0];
  const latest = analysisForCommit(analyses, newest?.commit_sha);
  if (latest?.id) {
    try {
      statistics = await getTestStatistics(latest.id);
    } catch (error) {
      errors.push(`Statistics: ${message(error)}`);
    }
  }
  return {
    analyses,
    recent: recentRows,
    flaky: flaky.status === "fulfilled" ? flaky.value : null,
    statistics,
    statisticsAnalysisId: latest?.id ?? null,
    partialError: errors.length ? errors.join(" ") : null,
  };
}

export function TestInsights() {
  const [repositories, setRepositories] = useState<Repository[] | null>(null);
  const [repositoryId, setRepositoryId] = useState<string>("");
  const [data, setData] = useState<RepoData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTest, setSelectedTest] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listRepositories()
      .then((repos) => {
        if (!active) return;
        const usable = repos.filter((repo) => repo.id);
        setRepositories(usable);
        if (usable.length) setRepositoryId(usable[0].id as string);
      })
      .catch((err: unknown) => active && setError(message(err)));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!repositoryId) return;
    let active = true;
    setLoading(true);
    setData(null);
    setSelectedTest(null);
    setError(null);
    loadRepoData(repositoryId)
      .then((result) => active && setData(result))
      .catch((err: unknown) => active && setError(message(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [repositoryId]);

  const summary = useMemo(() => summarizeExecutions(data?.recent ?? []), [data]);
  const runs = useMemo(() => groupRuns(data?.recent ?? []).slice(0, 20), [data]);
  const tests = useMemo(() => summarizeTests(data?.recent ?? []), [data]);
  const history = useMemo(
    () => (selectedTest ? historyForTest(data?.recent ?? [], selectedTest) : []),
    [data, selectedTest],
  );

  if (error && !repositories) {
    return (
      <StateCard title="Dashboard could not reach the Radius API." error>
        <p className="muted">{error}</p>
      </StateCard>
    );
  }
  if (!repositories) return <StateCard title="Loading repositories..."><p className="muted">One moment.</p></StateCard>;
  if (!repositories.length) {
    return (
      <StateCard title="No repositories connected yet">
        <p className="muted">
          Connect a repository first. Test insights appear once your CI uploads results for its pull requests.
        </p>
        <Link className="text-link" href="/repositories">Connect a repository</Link>
      </StateCard>
    );
  }

  const selectedRepo = repositories.find((repo) => repo.id === repositoryId);
  const flakyRows = data?.flaky?.quarantined ?? [];
  const selectedName = selectedTest
    ? (tests.find((t) => t.key === selectedTest)?.testName ??
      flakyRows.find((f) => f.test_path === selectedTest)?.test_name ??
      selectedTest)
    : null;

  return (
    <>
      {repositories.length > 1 && (
        <div className="ti-toolbar">
          <label htmlFor="ti-repository">Repository</label>
          <select
            id="ti-repository"
            className="ti-select"
            value={repositoryId}
            onChange={(event) => setRepositoryId(event.target.value)}
          >
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id as string}>{repo.full_name}</option>
            ))}
          </select>
        </div>
      )}

      {error && (
        <StateCard title="Test insights could not be loaded." error>
          <p className="muted">{error}</p>
        </StateCard>
      )}
      {loading && <StateCard title={`Loading test insights for ${selectedRepo?.full_name ?? "repository"}...`}><p className="muted">One moment.</p></StateCard>}

      {data && !loading && !data.analyses.length && (
        <StateCard title="No analyses for this repository yet">
          <p className="muted">
            Radius creates an analysis for each pull request. Open or sync a pull request, then add the{" "}
            <code>actions/upload-results</code> step to your CI so test results attach to it.
          </p>
          <GuideLink />
        </StateCard>
      )}

      {data && !loading && data.analyses.length > 0 && !data.recent.length && (
        <StateCard title="No test results uploaded yet">
          <p className="muted">
            Test insights come from CI uploads. Add the <code>actions/upload-results</code> step after your tests
            run (JUnit XML), using an API key with the <code>ci-upload</code> scope. Results show up here after the
            next pull request run.
          </p>
          <p style={{ display: "flex", gap: "16px", flexWrap: "wrap", margin: 0 }}>
            <GuideLink />
            <Link className="text-link" href="/settings">CI upload setup in Settings</Link>
          </p>
          {data.partialError && <p className="muted">{data.partialError}</p>}
        </StateCard>
      )}

      {data && !loading && data.recent.length > 0 && (
        <>
          {data.partialError && (
            <StateCard title="Some insights are unavailable." error>
              <p className="muted">{data.partialError}</p>
            </StateCard>
          )}
          <dl className="metric-grid">
            <div className="metric-card">
              <dt>Test executions</dt>
              <dd>{summary.total}</dd>
              <small>Last {RECENT_LIMIT} recorded at most</small>
            </div>
            <div className="metric-card">
              <dt>Pass rate</dt>
              <dd>{formatPercent(summary.passRate)}</dd>
              <small>Skipped tests excluded</small>
            </div>
            <div className="metric-card">
              <dt>Failures</dt>
              <dd>{summary.failed}</dd>
              <small>{summary.skipped} skipped</small>
            </div>
            <div className="metric-card">
              <dt>Flaky tests</dt>
              <dd>{data.flaky ? flakyRows.length : "-"}</dd>
              <small>Last run {formatDate(summary.lastRun)}</small>
            </div>
          </dl>

          <div className="ti-grid">
            <section className="card">
              <div className="card-heading">
                <div>
                  <h2>Flaky tests</h2>
                  <p>Tests whose result changed between reruns of the same commit.</p>
                </div>
              </div>
              {!data.flaky ? (
                <div className="ti-empty"><p>Flaky test data is unavailable.</p></div>
              ) : flakyRows.length === 0 ? (
                <div className="ti-empty">
                  <p>
                    No flaky tests detected. A test is flagged when reruns of the same commit disagree at least{" "}
                    {Math.round(data.flaky.threshold * 100)}% of the time (window {data.flaky.window} runs).
                  </p>
                  {data.flaky.insufficient_history_count > 0 && (
                    <p>
                      {data.flaky.insufficient_history_count} test(s) need more reruns of the same commit (at least{" "}
                      {data.flaky.min_comparable}) before they can be scored.
                    </p>
                  )}
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Test</th><th>Score</th><th>Flips</th><th>Last status</th></tr></thead>
                    <tbody>
                      {flakyRows.map((row) => (
                        <tr key={row.test_path} className={selectedTest === row.test_path ? "ti-selected" : undefined}>
                          <td>
                            <button type="button" className="ti-test-button" onClick={() => setSelectedTest(row.test_path)}>
                              <strong>{row.test_name}</strong>
                              <div className="subtext">{row.test_path}</div>
                            </button>
                          </td>
                          <td className="ti-mono">{row.score === null ? "-" : row.score.toFixed(2)}</td>
                          <td>{row.flips} / {row.comparable}</td>
                          <td><StatusPill status={row.last_status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="card detail-card">
              <h2>Latest run statistics</h2>
              {data.statistics ? (
                <div className="stat-list">
                  <div><span>Analysis</span>
                    {data.statisticsAnalysisId
                      ? <Link className="text-link" href={`/analyses/${data.statisticsAnalysisId}`}>{shortSha(data.statisticsAnalysisId)}</Link>
                      : <strong>-</strong>}
                  </div>
                  <div><span>Tests executed</span><strong>{data.statistics.total_runs}</strong></div>
                  <div><span>Passed</span><strong>{data.statistics.pass_count}</strong></div>
                  <div><span>Failed</span><strong>{data.statistics.failure_count}</strong></div>
                  <div><span>Pass rate</span><strong>{formatPercent(data.statistics.pass_rate)}</strong></div>
                  <div><span>Average duration</span><strong>{formatDuration(data.statistics.average_duration_ms)}</strong></div>
                  <div><span>Last execution</span><strong>{formatDate(data.statistics.last_execution)}</strong></div>
                </div>
              ) : (
                <p className="muted">
                  No analysis matches the newest uploaded commit, so per-run statistics are not available. Upload
                  results for the pull request head commit.
                </p>
              )}
            </section>
          </div>

          <section className="card" style={{ marginBottom: "25px" }}>
            <div className="card-heading">
              <div>
                <h2>Recent runs</h2>
                <p>Uploaded results grouped by commit, newest first.</p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Commit</th><th>When</th><th>Tests</th><th>Passed</th><th>Failed</th><th>Pass rate</th></tr></thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.key}>
                      <td><strong className="ti-mono">{shortSha(run.commitSha)}</strong>{run.branch && <div className="subtext">{run.branch}</div>}</td>
                      <td>{formatDate(run.timestamp)}</td>
                      <td>{run.total}</td>
                      <td>{run.passed}</td>
                      <td>{run.failed}</td>
                      <td>{formatPercent(run.passRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="ti-grid">
            <section className="card">
              <div className="card-heading">
                <div>
                  <h2>Tests</h2>
                  <p>Select a test to see its history.</p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Test</th><th>Runs</th><th>Failures</th><th>Last status</th></tr></thead>
                  <tbody>
                    {tests.map((row) => (
                      <tr key={row.key} className={selectedTest === row.key ? "ti-selected" : undefined}>
                        <td>
                          <button type="button" className="ti-test-button" onClick={() => setSelectedTest(row.key)}>
                            <strong>{row.testName}</strong>
                            <div className="subtext">{row.testPath}</div>
                          </button>
                        </td>
                        <td>{row.runs}</td>
                        <td>{row.failures}</td>
                        <td><StatusPill status={row.lastStatus} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="card">
              <div className="card-heading">
                <div>
                  <h2>Test history</h2>
                  <p>{selectedName ? selectedName : "No test selected."}</p>
                </div>
              </div>
              {!selectedTest ? (
                <div className="ti-empty"><p>Click a test in the Tests or Flaky tests table to see each recorded run.</p></div>
              ) : history.length === 0 ? (
                <div className="ti-empty"><p>No recent executions recorded for this test.</p></div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>When</th><th>Status</th><th>Commit</th><th>Duration</th></tr></thead>
                    <tbody>
                      {history.map((row) => (
                        <tr key={`${row.id}-${testKey(row)}`}>
                          <td>{formatDate(row.timestamp)}</td>
                          <td><StatusPill status={row.status} /></td>
                          <td className="ti-mono">{shortSha(row.commit_sha)}</td>
                          <td>{formatDuration(row.duration_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </>
  );
}
