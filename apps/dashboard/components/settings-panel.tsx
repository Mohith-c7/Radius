"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Code2,
  Copy,
  ExternalLink,
  FolderGit2,
  GitBranch,
  Github,
  Key,
  Layers,
  Lock,
  Mail,
  Play,
  RefreshCw,
  Server,
  Settings2,
  Shield,
  ShieldCheck,
  Sliders,
  Terminal,
  User,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Repository, listRepositories, radiusConfig, radiusFetch } from "../lib/api";
import { EmptyState, MetricTile, PageHeading, Status } from "./ui";

type SettingsTab = "general" | "integrations" | "account" | "developer";

export function SettingsData() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Connectivity test state
  const [testState, setTestState] = useState<{
    status: "idle" | "running" | "success" | "error";
    latencyMs?: number;
    error?: string;
  }>({ status: "idle" });

  useEffect(() => {
    // Sync active tab with URL hash if present
    const hash = window.location.hash.replace("#", "") as SettingsTab;
    if (["general", "integrations", "account", "developer"].includes(hash)) {
      setActiveTab(hash);
    }

    const onHashChange = () => {
      const newHash = window.location.hash.replace("#", "") as SettingsTab;
      if (["general", "integrations", "account", "developer"].includes(newHash)) {
        setActiveTab(newHash);
      }
    };

    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    let mounted = true;
    listRepositories()
      .then((data) => {
        if (mounted) {
          setRepositories(data);
          setLoadingRepos(false);
        }
      })
      .catch(() => {
        if (mounted) setLoadingRepos(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  function handleTabClick(tab: SettingsTab) {
    setActiveTab(tab);
    window.history.replaceState(null, "", `#${tab}`);
  }

  function copyToClipboard(text: string, key: string) {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  }

  async function testBackendConnection() {
    setTestState({ status: "running" });
    const startTime = performance.now();
    try {
      await radiusFetch<Repository[]>("/repositories");
      const latencyMs = Math.round(performance.now() - startTime);
      setTestState({ status: "success", latencyMs });
    } catch (err) {
      setTestState({
        status: "error",
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const envSnippet = `# Radius Dashboard Runtime Configuration
NEXT_PUBLIC_RADIUS_API_BASE_URL=${radiusConfig.apiBaseUrl}
NEXT_PUBLIC_RADIUS_ORGANIZATION_ID=${radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001"}
NEXT_PUBLIC_RADIUS_API_KEY=${radiusConfig.apiKey || ""}`;

  const curlSnippet = `curl -s -H "X-Radius-Organization-Id: ${
    radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001"
  }" "${radiusConfig.apiBaseUrl.replace(/\/$/, "")}/api/v1/repositories"`;

  return (
    <>
      <PageHeading
        title="Settings"
        description="Manage your workspace identity, repository integrations, account credentials, and developer configuration."
      />

      {/* Settings Section Navigation Tabs */}
      <nav className="settings-nav" aria-label="Settings navigation">
        <button
          className={`settings-tab-btn ${activeTab === "general" ? "active" : ""}`}
          onClick={() => handleTabClick("general")}
          type="button"
        >
          <Sliders size={16} />
          General
        </button>
        <button
          className={`settings-tab-btn ${activeTab === "integrations" ? "active" : ""}`}
          onClick={() => handleTabClick("integrations")}
          type="button"
        >
          <FolderGit2 size={16} />
          Integrations
        </button>
        <button
          className={`settings-tab-btn ${activeTab === "account" ? "active" : ""}`}
          onClick={() => handleTabClick("account")}
          type="button"
        >
          <User size={16} />
          Profile & Account
        </button>
        <button
          className={`settings-tab-btn ${activeTab === "developer" ? "active" : ""}`}
          onClick={() => handleTabClick("developer")}
          type="button"
        >
          <Terminal size={16} />
          Developer Configuration
        </button>
      </nav>

      {/* SECTION 1: GENERAL */}
      {activeTab === "general" && (
        <div className="settings-section">
          {/* Workspace Identity */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Server size={18} style={{ color: "var(--green)" }} />
                  Workspace Identity
                </h2>
                <p>Core organization and environment identifiers for this Radius instance.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Workspace Name</strong>
                <p>The display name displayed on verification reports and pull request comments.</p>
              </div>
              <div className="setting-row-action">
                <span style={{ fontWeight: 600 }}>Radius Workspace</span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Organization Identifier</strong>
                <p>UUID used to authenticate and route API requests to this workspace.</p>
              </div>
              <div className="setting-row-action">
                <div className="readout-box">
                  <code>{radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001"}</code>
                  <button
                    className="readout-copy-btn"
                    onClick={() =>
                      copyToClipboard(
                        radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001",
                        "orgId",
                      )
                    }
                    title="Copy Organization ID"
                    type="button"
                  >
                    {copiedKey === "orgId" ? (
                      <Check size={14} style={{ color: "var(--green)" }} />
                    ) : (
                      <Copy size={14} />
                    )}
                  </button>
                </div>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Deployment Environment</strong>
                <p>Current runtime mode for the Radius client dashboard.</p>
              </div>
              <div className="setting-row-action">
                <Status status="active" />
                <span className="muted" style={{ fontSize: "12px" }}>
                  {typeof window !== "undefined" && window.location.hostname.includes("localhost")
                    ? "Local Development"
                    : "Production Cloud"}
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Monitored Repositories</strong>
                <p>Total codebases connected for automated blast radius analysis and CI test selection.</p>
              </div>
              <div className="setting-row-action">
                <span style={{ fontWeight: 600 }}>
                  {loadingRepos
                    ? "Loading..."
                    : repositories.length === 1
                    ? "1 repository"
                    : `${repositories.length} repositories`}
                </span>
                <Link href="/repositories" className="button secondary" style={{ fontSize: "12px", padding: "4px 10px" }}>
                  Manage
                </Link>
              </div>
            </div>
          </div>

          {/* Verification Policies */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <ShieldCheck size={18} style={{ color: "var(--green)" }} />
                  Verification & Gatekeeper Policies
                </h2>
                <p>Quality gates enforced on pull requests before approving merge safety.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Automated PR Verification</strong>
                <p>Run AST dependency analysis and test selection automatically when pull requests open or update.</p>
              </div>
              <div className="setting-row-action">
                <Status status="healthy" />
                <span style={{ fontSize: "12px", fontWeight: 600 }}>Always Active</span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Minimum Confidence Floor</strong>
                <p>Heuristic evidence threshold required to achieve the "Verified for Merge" status.</p>
              </div>
              <div className="setting-row-action">
                <div className="readout-box" style={{ fontWeight: 700, color: "var(--green)" }}>
                  80 / 100
                </div>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Unmapped Changed File Enforcement</strong>
                <p>Block verification when modified source files lack direct test coverage or CI evidence.</p>
              </div>
              <div className="setting-row-action">
                <span className="status warning" style={{ fontSize: "12px", padding: "3px 8px" }}>
                  Blocking Enabled
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Predictive Test Selection Strategy</strong>
                <p>Derive minimal targeted test suites from sliced Code Property Graph (CPG) reachability.</p>
              </div>
              <div className="setting-row-action">
                <span className="pr-chip" style={{ fontSize: "12px" }}>
                  AST + CPG Slicing
                </span>
              </div>
            </div>
          </div>

          {/* Artifact Retention */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Layers size={18} style={{ color: "var(--green)" }} />
                  Artifacts & Data Retention
                </h2>
                <p>Lifecycles for code property graph snapshots and CI test execution traces.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Code Property Graph Snapshots</strong>
                <p>Parsed symbol tables, caller hierarchies, and sliced dependency subgraphs.</p>
              </div>
              <div className="setting-row-action">
                <span className="muted" style={{ fontSize: "13px" }}>30 days retention</span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>CI Test Execution Traces</strong>
                <p>Parsed JUnit XML test results and standard output traces from CI runners.</p>
              </div>
              <div className="setting-row-action">
                <span className="muted" style={{ fontSize: "13px" }}>14 days retention</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 2: INTEGRATIONS */}
      {activeTab === "integrations" && (
        <div className="settings-section">
          {/* GitHub App Gateway */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Github size={18} style={{ color: "var(--foreground)" }} />
                  GitHub App Integration
                </h2>
                <p>Radius connects to your repositories through our GitHub App to inspect diffs and post check runs.</p>
              </div>
              <Status status="connected" />
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Integration Status</strong>
                <p>GitHub App is installed and listening for repository webhook events.</p>
              </div>
              <div className="setting-row-action">
                <span className="status positive" style={{ fontSize: "12px", padding: "4px 10px" }}>
                  <CheckCircle2 size={13} /> Active & Synced
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Configured Permissions</strong>
                <p>Granted scopes necessary for deterministic verification:</p>
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "8px" }}>
                  <span className="pr-chip" style={{ fontSize: "11px" }}>Contents: Read-only</span>
                  <span className="pr-chip" style={{ fontSize: "11px" }}>Pull Requests: Read & Write</span>
                  <span className="pr-chip" style={{ fontSize: "11px" }}>Checks: Read & Write</span>
                  <span className="pr-chip" style={{ fontSize: "11px" }}>Statuses: Read & Write</span>
                </div>
              </div>
              <div className="setting-row-action">
                <Link href="/repositories/connect" className="button secondary" style={{ fontSize: "12px" }}>
                  Connect Repository
                </Link>
              </div>
            </div>
          </div>

          {/* Connected Repositories */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <FolderGit2 size={18} style={{ color: "var(--green)" }} />
                  Connected Repositories ({repositories.length})
                </h2>
                <p>Codebases monitored by Radius for pull request verification and graph indexing.</p>
              </div>
              <Link href="/repositories/connect" className="button" style={{ fontSize: "12px", padding: "6px 12px" }}>
                Add Repository
              </Link>
            </div>
            {repositories.length > 0 ? (
              <div style={{ display: "grid", gap: "0" }}>
                {repositories.map((repo) => (
                  <div className="setting-row" key={repo.id ?? repo.full_name}>
                    <div className="setting-row-info">
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Link
                          href={`/repositories/${repo.id}`}
                          style={{ fontWeight: 600, color: "var(--foreground)", textDecoration: "none" }}
                        >
                          {repo.full_name}
                        </Link>
                        <span className="pr-chip" style={{ fontSize: "10px", textTransform: "capitalize" }}>
                          {repo.visibility}
                        </span>
                      </div>
                      <p>
                        Target branch: <code>{repo.default_branch}</code> • Provider: {repo.provider}
                      </p>
                    </div>
                    <div className="setting-row-action">
                      <Status status={repo.status} />
                      <Link
                        href={`/repositories/${repo.id}`}
                        className="button secondary"
                        style={{ fontSize: "12px", padding: "4px 10px" }}
                      >
                        Settings →
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: "24px 20px" }}>
                <EmptyState
                  icon={<FolderGit2 size={24} />}
                  title="No repositories connected"
                  detail="Connect your first GitHub repository to enable automated confidence verification."
                  action={
                    <Link href="/repositories/connect" className="button" style={{ marginTop: "12px" }}>
                      Connect Repository
                    </Link>
                  }
                />
              </div>
            )}
          </div>

          {/* CI/CD Test Runners */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Zap size={18} style={{ color: "var(--green)" }} />
                  Supported CI/CD Runners & Test Ingestion
                </h2>
                <p>Seamlessly feed test execution reports back into Radius from your CI pipeline.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Supported Test Frameworks</strong>
                <p>Radius parses and selects tests across multiple ecosystems:</p>
                <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                  <span className="pr-chip" style={{ fontSize: "11px", fontWeight: 600 }}>Python: pytest</span>
                  <span className="pr-chip" style={{ fontSize: "11px", fontWeight: 600 }}>TypeScript: vitest</span>
                  <span className="pr-chip" style={{ fontSize: "11px", fontWeight: 600 }}>JavaScript: jest</span>
                </div>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>JUnit XML Ingestion Endpoint</strong>
                <p>Post test execution results to dynamically calculate coverage and confidence scores:</p>
                <div style={{ marginTop: "8px" }}>
                  <code style={{ fontSize: "12px", background: "var(--card-bg)", padding: "4px 8px", borderRadius: "4px" }}>
                    POST /api/v1/analyses/&#123;analysisId&#125;/test-results
                  </code>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 3: PROFILE & ACCOUNT */}
      {activeTab === "account" && (
        <div className="settings-section">
          {/* User Profile Card */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <User size={18} style={{ color: "var(--green)" }} />
                  User Profile
                </h2>
                <p>Your developer profile, organization role, and account credentials.</p>
              </div>
              <Link href="/profile" className="button secondary" style={{ fontSize: "12px", padding: "6px 12px" }}>
                Edit Full Profile
              </Link>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Full Name</strong>
                <p>Sanjith Madupalli</p>
              </div>
              <div className="setting-row-action">
                <span className="avatar" style={{ width: "32px", height: "32px", fontSize: "12px" }}>
                  SM
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Email Address</strong>
                <p>sanjith@radius.dev</p>
              </div>
              <div className="setting-row-action">
                <span className="status positive" style={{ fontSize: "11px", padding: "2px 8px" }}>
                  Verified
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Workspace Role</strong>
                <p>Workspace Administrator with full access to repositories and organization policies.</p>
              </div>
              <div className="setting-row-action">
                <span className="status neutral" style={{ fontSize: "12px" }}>
                  Admin
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Connected Identity</strong>
                <p>Authenticated via GitHub OAuth as @sanhithamadupalli.</p>
              </div>
              <div className="setting-row-action">
                <span className="pr-chip" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <Github size={13} />
                  @sanhithamadupalli
                </span>
              </div>
            </div>
          </div>

          {/* Security & Access */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Lock size={18} style={{ color: "var(--green)" }} />
                  Security & Access Control
                </h2>
                <p>Authentication methods, active sessions, and access keys.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Two-Factor Authentication (2FA)</strong>
                <p>Enforced through your connected GitHub account.</p>
              </div>
              <div className="setting-row-action">
                <span className="status positive" style={{ fontSize: "12px", padding: "2px 8px" }}>
                  <CheckCircle2 size={12} /> Enabled
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Team Management</strong>
                <p>Manage fellow team members, developers, and invitation permissions.</p>
              </div>
              <div className="setting-row-action">
                <Link href="/organization" className="button secondary" style={{ fontSize: "12px", padding: "6px 12px" }}>
                  View Organization Members
                </Link>
              </div>
            </div>
          </div>

          {/* Notification Preferences */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Mail size={18} style={{ color: "var(--green)" }} />
                  Notification Preferences
                </h2>
                <p>Configure how and when Radius delivers verification reports.</p>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>PR Verification Blockers</strong>
                <p>Send immediate alerts when a pull request fails verification or has unmapped changed files.</p>
              </div>
              <div className="setting-row-action">
                <span className="status positive" style={{ fontSize: "12px" }}>Active</span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Weekly Health Digest</strong>
                <p>Weekly rollup of repository verification pass rates, test savings, and confidence trends.</p>
              </div>
              <div className="setting-row-action">
                <span className="status positive" style={{ fontSize: "12px" }}>Active</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 4: DEVELOPER CONFIGURATION */}
      {activeTab === "developer" && (
        <div className="settings-section">
          {/* API Connection & Runtime Details */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Terminal size={18} style={{ color: "var(--green)" }} />
                  Dashboard API Connection Runtime
                </h2>
                <p>Current runtime configuration used by the browser client to communicate with the Radius backend.</p>
              </div>
              <button
                className="button secondary"
                onClick={testBackendConnection}
                disabled={testState.status === "running"}
                type="button"
                style={{ fontSize: "12px", padding: "6px 12px", display: "flex", alignItems: "center", gap: "6px" }}
              >
                <RefreshCw size={13} className={testState.status === "running" ? "spin" : ""} />
                {testState.status === "running" ? "Testing..." : "Test Connection"}
              </button>
            </div>

            {testState.status !== "idle" && (
              <div
                style={{
                  padding: "12px 20px",
                  borderBottom: "1px solid var(--line-subtle)",
                  background:
                    testState.status === "success"
                      ? "rgba(25, 129, 92, 0.08)"
                      : testState.status === "error"
                      ? "rgba(211, 61, 34, 0.08)"
                      : "rgba(0, 0, 0, 0.02)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: "13px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  {testState.status === "running" && <RefreshCw size={14} className="spin" />}
                  {testState.status === "success" && <CheckCircle2 size={15} style={{ color: "var(--green)" }} />}
                  {testState.status === "error" && <AlertCircle size={15} style={{ color: "var(--red)" }} />}
                  <span>
                    {testState.status === "running" && "Pinging Radius backend API..."}
                    {testState.status === "success" &&
                      `Backend connection healthy! Response latency: ${testState.latencyMs}ms.`}
                    {testState.status === "error" && `Connection failed: ${testState.error}`}
                  </span>
                </div>
                {testState.status === "success" && <Status status="healthy" />}
              </div>
            )}

            <div className="setting-row">
              <div className="setting-row-info">
                <strong>API Base URL</strong>
                <p>Destination endpoint for all graph, analysis, and repository REST calls.</p>
              </div>
              <div className="setting-row-action">
                <div className="readout-box">
                  <code>{radiusConfig.apiBaseUrl}</code>
                  <button
                    className="readout-copy-btn"
                    onClick={() => copyToClipboard(radiusConfig.apiBaseUrl, "apiUrl")}
                    title="Copy API Base URL"
                    type="button"
                  >
                    {copiedKey === "apiUrl" ? (
                      <Check size={14} style={{ color: "var(--green)" }} />
                    ) : (
                      <Copy size={14} />
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="setting-row">
              <div className="setting-row-info">
                <strong>Organization Header</strong>
                <p>Default UUID injected via <code>X-Radius-Organization-Id</code>.</p>
              </div>
              <div className="setting-row-action">
                <div className="readout-box">
                  <code>{radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001"}</code>
                  <button
                    className="readout-copy-btn"
                    onClick={() =>
                      copyToClipboard(
                        radiusConfig.organizationId || "00000000-0000-0000-0000-000000000001",
                        "devOrgId",
                      )
                    }
                    title="Copy Organization ID"
                    type="button"
                  >
                    {copiedKey === "devOrgId" ? (
                      <Check size={14} style={{ color: "var(--green)" }} />
                    ) : (
                      <Copy size={14} />
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="setting-row">
              <div className="setting-row-info">
                <strong>API Key Authentication</strong>
                <p>Optional bearer token sent via <code>X-Radius-API-Key</code> for secured environments.</p>
              </div>
              <div className="setting-row-action">
                <span className={`status ${radiusConfig.apiKey ? "positive" : "neutral"}`}>
                  {radiusConfig.apiKey ? "Configured" : "Not configured (Dev Mode)"}
                </span>
              </div>
            </div>
          </div>

          {/* Environment Variables Reference */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Code2 size={18} style={{ color: "var(--green)" }} />
                  Environment Variables Reference
                </h2>
                <p>Configure these variables in your <code>apps/dashboard/.env.local</code> to target custom backends.</p>
              </div>
              <button
                className="button secondary"
                onClick={() => copyToClipboard(envSnippet, "envSnippet")}
                type="button"
                style={{ fontSize: "12px", padding: "6px 12px", display: "flex", alignItems: "center", gap: "6px" }}
              >
                {copiedKey === "envSnippet" ? (
                  <Check size={13} style={{ color: "var(--green)" }} />
                ) : (
                  <Copy size={13} />
                )}
                {copiedKey === "envSnippet" ? "Copied .env!" : "Copy .env"}
              </button>
            </div>
            <div style={{ padding: "16px 20px" }}>
              <pre
                style={{
                  margin: 0,
                  padding: "14px 16px",
                  borderRadius: "var(--radius-md)",
                  background: "#111B17",
                  border: "1px solid #1F332B",
                  color: "#E2ECE6",
                  fontSize: "12px",
                  lineHeight: "1.6",
                  fontFamily: "var(--font-mono)",
                  overflowX: "auto",
                }}
              >
                <code>{envSnippet}</code>
              </pre>
            </div>
          </div>

          {/* Terminal / CLI Verification Snippet */}
          <div className="setting-card">
            <div className="setting-card-header">
              <div>
                <h2>
                  <Zap size={18} style={{ color: "var(--green)" }} />
                  Terminal Smoke Test Command
                </h2>
                <p>Verify that your local backend API responds with valid JSON envelopes.</p>
              </div>
              <button
                className="button secondary"
                onClick={() => copyToClipboard(curlSnippet, "curlSnippet")}
                type="button"
                style={{ fontSize: "12px", padding: "6px 12px", display: "flex", alignItems: "center", gap: "6px" }}
              >
                {copiedKey === "curlSnippet" ? (
                  <Check size={13} style={{ color: "var(--green)" }} />
                ) : (
                  <Copy size={13} />
                )}
                {copiedKey === "curlSnippet" ? "Copied command!" : "Copy curl"}
              </button>
            </div>
            <div style={{ padding: "16px 20px" }}>
              <pre
                style={{
                  margin: 0,
                  padding: "14px 16px",
                  borderRadius: "var(--radius-md)",
                  background: "#111B17",
                  border: "1px solid #1F332B",
                  color: "#64C89D",
                  fontSize: "12px",
                  lineHeight: "1.6",
                  fontFamily: "var(--font-mono)",
                  overflowX: "auto",
                }}
              >
                <code>{curlSnippet}</code>
              </pre>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
