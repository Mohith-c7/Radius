"use client";

// Pull-based GitHub actions (no webhook): connect a repository by owner/name,
// analyze one pull request, show the result of a sync.
//
// SECURITY: error messages, repository names and skip reasons come from the API
// or GitHub and are untrusted. They are rendered ONLY as React text nodes (no
// dangerouslySetInnerHTML, no markdown, no links built from them). The only
// links are internal /repositories/<id> and /analyses/<id> routes.

import Link from "next/link";
import { AlertCircle, CheckCircle2, Loader2, Play, Plus } from "lucide-react";
import { FormEvent, useState } from "react";

import { analyzePullRequest, connectGitHubRepository } from "../lib/api";
import {
  connectMessage,
  describeGitHubError,
  parseRepositoryInput,
  skippedLabel,
  type SyncSummary,
} from "../lib/github-actions";
import "./github-actions.css";

type ConnectState =
  | { phase: "idle" }
  | { phase: "busy" }
  | { phase: "invalid"; message: string }
  | { phase: "error"; title: string; detail: string | null }
  | { phase: "done"; repositoryId: string | null; message: string; fullName: string };

export function ConnectGitHubRepositoryCard({ onConnected }: { onConnected?: () => void }) {
  const [value, setValue] = useState("");
  const [state, setState] = useState<ConnectState>({ phase: "idle" });
  const busy = state.phase === "busy";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const parsed = parseRepositoryInput(value);
    if (!parsed.ok) {
      setState({ phase: "invalid", message: parsed.message });
      return;
    }
    setState({ phase: "busy" });
    try {
      const result = await connectGitHubRepository(parsed.value);
      setState({
        phase: "done",
        repositoryId: result.repository.id,
        fullName: result.repository.full_name,
        message: connectMessage(result.repository.full_name, result.created),
      });
      setValue("");
      onConnected?.();
    } catch (error) {
      const view = describeGitHubError(error);
      setState({ phase: "error", title: view.title, detail: view.detail });
    }
  }

  return (
    <section className="card gh-connect" aria-labelledby="gh-connect-title">
      <h2 id="gh-connect-title">Connect GitHub repository</h2>
      <p className="muted">
        Enter <code>owner/name</code>. Radius finds the GitHub App installation itself; no webhook,
        tunnel or installation id is needed. The App must be installed on the repository.
      </p>
      <form className="gh-connect-form" onSubmit={(event) => void submit(event)} noValidate>
        <label htmlFor="gh-connect-input" className="gh-visually-hidden">
          Repository as owner/name
        </label>
        <input
          id="gh-connect-input"
          name="repository"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            if (state.phase === "invalid") setState({ phase: "idle" });
          }}
          placeholder="your-user/your-test-repo"
          autoComplete="off"
          spellCheck={false}
          maxLength={300}
          aria-invalid={state.phase === "invalid"}
          aria-describedby="gh-connect-status"
          disabled={busy}
        />
        <button className="button" type="submit" disabled={busy || value.trim() === ""}>
          {busy ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
          {busy ? "Connecting..." : "Connect"}
        </button>
      </form>
      <div id="gh-connect-status" role="status" aria-live="polite">
        {state.phase === "invalid" && (
          <p className="gh-note gh-note-warn">
            <AlertCircle size={14} /> {state.message}
          </p>
        )}
        {state.phase === "error" && (
          <p className="gh-note gh-note-error">
            <AlertCircle size={14} />
            <span>
              {state.title}
              {state.detail && <span className="gh-detail"> GitHub/Radius said: {state.detail}</span>}
            </span>
          </p>
        )}
        {state.phase === "done" && (
          <p className="gh-note gh-note-ok">
            <CheckCircle2 size={14} />
            <span>
              {state.message}{" "}
              {state.repositoryId && (
                <Link href={`/repositories/${encodeURIComponent(state.repositoryId)}`}>
                  Open {state.fullName}
                </Link>
              )}
            </span>
          </p>
        )}
      </div>
    </section>
  );
}

type AnalyzeState =
  | { phase: "idle" }
  | { phase: "busy" }
  | { phase: "queued"; analysisId: string }
  | { phase: "error"; text: string };

export function AnalyzePullRequestButton({
  repositoryId,
  prNumber,
  onQueued,
  label = "Analyze",
}: {
  repositoryId: string;
  prNumber: number;
  onQueued?: (analysisId: string) => void;
  label?: string;
}) {
  const [state, setState] = useState<AnalyzeState>({ phase: "idle" });
  const busy = state.phase === "busy";

  async function run() {
    if (busy) return;
    setState({ phase: "busy" });
    try {
      const analysis = await analyzePullRequest(repositoryId, prNumber);
      if (!analysis.id) throw new Error("Radius returned an analysis without an id.");
      setState({ phase: "queued", analysisId: analysis.id });
      onQueued?.(analysis.id);
    } catch (error) {
      const view = describeGitHubError(error);
      setState({ phase: "error", text: view.detail ? `${view.title} (${view.detail})` : view.title });
    }
  }

  return (
    <span className="gh-analyze">
      <button
        className="button secondary gh-analyze-button"
        type="button"
        onClick={() => void run()}
        disabled={busy}
        title={`Read the current head commit of #${prNumber} from GitHub and queue an analysis`}
      >
        {busy ? <Loader2 size={12} className="spin" /> : <Play size={12} />}
        {busy ? "Queuing..." : label}
      </button>
      <span role="status" aria-live="polite" className="gh-analyze-status">
        {state.phase === "queued" && (
          <>
            <CheckCircle2 size={12} /> Queued.{" "}
            <Link href={`/analyses/${encodeURIComponent(state.analysisId)}`}>Open analysis</Link>
          </>
        )}
        {state.phase === "error" && (
          <span className="gh-analyze-error">
            <AlertCircle size={12} /> {state.text}
          </span>
        )}
      </span>
    </span>
  );
}

/** Result of a sync: the summary line plus the reason for each skipped pull request. */
export function SyncSummaryList({ summary }: { summary: SyncSummary }) {
  if (summary.skipped.length === 0) return null;
  return (
    <ul className="gh-skipped" aria-label="Skipped pull requests">
      {summary.skipped.map((item, index) => (
        <li key={`${item.number ?? "x"}-${index}`}>{skippedLabel(item)}</li>
      ))}
    </ul>
  );
}
