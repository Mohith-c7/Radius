"use client";

import { useState } from "react";
import { Check, Copy, ExternalLink, KeyRound } from "lucide-react";

import { radiusConfig } from "../lib/api";
import { DOCS_BASE } from "../lib/dashboard-model";
import {
  GITHUB_API_URL_VAR,
  GITHUB_KEY_SECRET,
  GITHUB_ORG_SECRET,
  UPLOAD_KEY_SCOPE,
  ciApiUrl,
  ciUploadEndpoint,
  uploadWorkflowSnippet,
} from "../lib/settings-model";
import { useAuth } from "./auth-provider";
import { PageHeading } from "./ui";
import "./settings-panel.css";

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-button"
      disabled={!value}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : label}
    </button>
  );
}

function ApiKeysSection() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  return (
    <section className="card detail-card">
      <h2><KeyRound size={16} className="inline-icon" />API keys</h2>
      <p className="muted">
        API keys let your CI upload test results to Radius. Each key belongs to your organization and has scopes;
        for CI uploads use a key with only the <code>{UPLOAD_KEY_SCOPE}</code> scope.
      </p>
      <div className="settings-note">
        {isAdmin
          ? "Creating, rotating and revoking keys from the dashboard is not available yet. Until it is, keys are issued by the Radius operator for your organization."
          : "Only organization admins can manage API keys. Ask an admin for a key with the ci-upload scope."}
      </div>
    </section>
  );
}

function CiUploadSection() {
  const apiUrl = ciApiUrl(radiusConfig.apiBaseUrl);
  const endpoint = ciUploadEndpoint(radiusConfig.apiBaseUrl);
  const organizationId = radiusConfig.organizationId;
  const snippet = uploadWorkflowSnippet();
  return (
    <section className="card detail-card">
      <h2>CI test upload setup</h2>
      <p className="muted">
        Radius picks the tests a pull request needs; your CI runs them and uploads the results, which become evidence
        for the verdict and feed Test insights.
      </p>
      <ol className="settings-steps">
        <li>
          Get an API key with the <code>{UPLOAD_KEY_SCOPE}</code> scope (see API keys above).
        </li>
        <li>
          In your GitHub repository open <strong>Settings, Secrets and variables, Actions</strong> and add:
          <div className="settings-kv">
            <div>
              <span>Variable {GITHUB_API_URL_VAR}</span>
              <div className="settings-kv-value"><strong>{apiUrl || "Not configured"}</strong><CopyButton value={apiUrl} /></div>
            </div>
            <div>
              <span>Secret {GITHUB_ORG_SECRET}</span>
              <div className="settings-kv-value"><strong>{organizationId || "Not configured"}</strong><CopyButton value={organizationId} /></div>
            </div>
            <div>
              <span>Secret {GITHUB_KEY_SECRET}</span>
              <div className="settings-kv-value"><strong>Your {UPLOAD_KEY_SCOPE} key</strong></div>
            </div>
          </div>
        </li>
        <li>
          Add the <code>actions/upload-results</code> step after your tests. It uploads to{" "}
          <code>{endpoint || "your Radius API"}</code>, finds the analysis from the pull request and head commit, and
          never fails your job by default.
          <div className="settings-code">
            <CopyButton value={snippet} label="Copy workflow" />
            <pre aria-label="GitHub Actions workflow"><code>{snippet}</code></pre>
          </div>
        </li>
      </ol>
      <div className="settings-links">
        <a className="text-link" href={`${DOCS_BASE}/docs/CI_INTEGRATION_GUIDE.md`} target="_blank" rel="noopener noreferrer">
          CI integration guide <ExternalLink size={14} />
        </a>
        <a className="text-link" href={`${DOCS_BASE}/docs/integrations/github-action.md`} target="_blank" rel="noopener noreferrer">
          Upload action reference (jest, vitest, maven) <ExternalLink size={14} />
        </a>
      </div>
    </section>
  );
}

function DiagnosticsSection() {
  return (
    <details className="card detail-card settings-diagnostics">
      <summary>Diagnostics</summary>
      <div className="stat-list">
        <div><span>API base URL</span><strong>{radiusConfig.apiBaseUrl}</strong></div>
        <div><span>Organization ID</span><strong>{radiusConfig.organizationId || "Missing"}</strong></div>
        <div><span>Dashboard API key</span><strong>Held server-side (never sent to the browser)</strong></div>
      </div>
    </details>
  );
}

export function SettingsPanel() {
  return (
    <>
      <PageHeading title="Settings" description="API keys and CI test upload for your organization." />
      <div className="settings-stack">
        <ApiKeysSection />
        <CiUploadSection />
        <DiagnosticsSection />
      </div>
    </>
  );
}
