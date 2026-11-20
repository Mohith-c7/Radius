"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, KeyRound, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";

import { createApiKey, listApiKeyAudit, listApiKeys, revokeApiKey, rotateApiKey } from "../lib/api-keys";
import {
  API_KEY_SCOPES,
  DEFAULT_KEY_SCOPES,
  KEY_NAME_MAX,
  auditDetailText,
  canManage,
  keyState,
  sortAudit,
  sortKeys,
  validateKeyForm,
  type ApiKey,
  type ApiKeyAuditEvent,
} from "../lib/api-keys-model";
import { UPLOAD_KEY_SCOPE } from "../lib/settings-model";
import { useAuth } from "./auth-provider";
import { CopyButton } from "./copy-id";

type Pending = { action: "rotate" | "revoke"; key: ApiKey } | null;
type Issued = { name: string; token: string; rotated: boolean } | null;

const AUDIT_SHOWN = 25;

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Unknown error.";
}

function StateBadge({ apiKey }: { apiKey: ApiKey }) {
  const state = keyState(apiKey);
  const label =
    state === "expiring" ? `Expires ${formatDate(apiKey.expires_at)}` : state.charAt(0).toUpperCase() + state.slice(1);
  return <span className={`api-key-state ${state}`}>{label}</span>;
}

/** The new token, shown once. It lives only in component state until dismissed. */
function IssuedToken({ issued, onDone }: { issued: NonNullable<Issued>; onDone: () => void }) {
  return (
    <div className="api-key-token" role="alert">
      <div className="api-key-token-head">
        <AlertTriangle size={16} />
        <strong>Copy this token now. It is shown only once.</strong>
      </div>
      <p>
        Radius keeps only a hash of the token for <strong>{issued.name}</strong>, so it cannot be shown again. Put it
        straight into your CI secret store (for example <code>RADIUS_CI_UPLOAD_KEY</code>); if it is lost, rotate the
        key.
        {issued.rotated && " The old token keeps working for 24 hours, then expires."}
      </p>
      <div className="api-key-token-value">
        <code>{issued.token}</code>
        <CopyButton value={issued.token} label="Copy token" />
      </div>
      <button type="button" className="button secondary" onClick={onDone}>
        I have stored the token
      </button>
    </div>
  );
}

function CreateKeyForm({ busy, onCreate }: { busy: boolean; onCreate: (name: string, scopes: string[]) => void }) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(DEFAULT_KEY_SCOPES);
  const [problem, setProblem] = useState<string | null>(null);

  function toggle(scope: string, on: boolean) {
    setScopes((current) => (on ? [...current, scope] : current.filter((value) => value !== scope)));
  }

  return (
    <form
      className="api-key-form"
      onSubmit={(event) => {
        event.preventDefault();
        const invalid = validateKeyForm(name, scopes);
        setProblem(invalid);
        if (!invalid) onCreate(name, scopes);
      }}
    >
      <label className="api-key-name">
        Name
        <input
          className="input"
          value={name}
          maxLength={KEY_NAME_MAX}
          placeholder="e.g. github-actions acme/web"
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <fieldset className="api-key-scopes">
        <legend>Scopes</legend>
        {API_KEY_SCOPES.map((scope) => (
          <label key={scope.value}>
            <input
              type="checkbox"
              checked={scopes.includes(scope.value)}
              onChange={(event) => toggle(scope.value, event.target.checked)}
            />
            <span>
              <code>{scope.value}</code> {scope.description}
            </span>
          </label>
        ))}
      </fieldset>
      <div className="form-actions">
        <button className="button" type="submit" disabled={busy}>
          {busy ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
          Create key
        </button>
        {problem && <p className="muted">{problem}</p>}
      </div>
    </form>
  );
}

function ConfirmBar({
  pending,
  busy,
  onConfirm,
  onCancel,
}: {
  pending: NonNullable<Pending>;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const rotate = pending.action === "rotate";
  return (
    <div className="api-key-confirm" role="alertdialog" aria-label={rotate ? "Confirm rotation" : "Confirm revocation"}>
      <p>
        {rotate ? (
          <>
            Rotate <strong>{pending.key.name}</strong>? A new token is issued now; the current token keeps working for 24
            hours, then expires. Update your CI secret before then.
          </>
        ) : (
          <>
            Revoke <strong>{pending.key.name}</strong> now? Anything using this key is rejected immediately. This cannot
            be undone.
          </>
        )}
      </p>
      <div className="form-actions">
        <button type="button" className={`button${rotate ? "" : " danger"}`} disabled={busy} onClick={onConfirm}>
          {busy && <Loader2 size={15} className="spin" />}
          {rotate ? "Rotate key" : "Revoke key"}
        </button>
        <button type="button" className="button secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function AdminKeys() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [audit, setAudit] = useState<ApiKeyAuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [issued, setIssued] = useState<Issued>(null);

  const load = useCallback(async () => {
    try {
      const [list, events] = await Promise.all([listApiKeys(), listApiKeyAudit()]);
      setKeys(list);
      setAudit(events);
      setError(null);
    } catch (err) {
      setKeys((current) => current ?? []);
      setError(message(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedKeys = useMemo(() => sortKeys(keys ?? []), [keys]);
  const sortedAudit = useMemo(() => sortAudit(audit), [audit]);
  const names = useMemo(() => new Map((keys ?? []).map((key) => [key.id, key.name])), [keys]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  function create(name: string, scopes: string[]) {
    void run(async () => {
      const created = await createApiKey(name, scopes);
      setIssued({ name: created.key.name, token: created.token, rotated: false });
      setCreating(false);
    });
  }

  function confirm() {
    if (!pending) return;
    const { action, key } = pending;
    void run(async () => {
      if (action === "rotate") {
        const rotated = await rotateApiKey(key.id);
        setIssued({ name: rotated.key.name, token: rotated.token, rotated: true });
      } else {
        await revokeApiKey(key.id);
      }
      setPending(null);
    });
  }

  return (
    <>
      {issued && <IssuedToken issued={issued} onDone={() => setIssued(null)} />}
      {error && <div className="settings-note">{error}</div>}

      <div className="api-key-toolbar">
        <strong>{keys === null ? "Loading keys..." : `${sortedKeys.length} key${sortedKeys.length === 1 ? "" : "s"}`}</strong>
        {!creating && (
          <button type="button" className="button secondary" onClick={() => setCreating(true)} disabled={busy}>
            <Plus size={15} />
            New key
          </button>
        )}
      </div>
      {creating && (
        <div className="api-key-create">
          <CreateKeyForm busy={busy} onCreate={create} />
          <button type="button" className="text-link api-key-cancel" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </div>
      )}

      {keys !== null && !sortedKeys.length && (
        <p className="muted api-key-empty">No keys yet. Create one with the {UPLOAD_KEY_SCOPE} scope for your CI.</p>
      )}
      <ul className="api-key-list">
        {sortedKeys.map((key) => (
          <li key={key.id} className="api-key-row">
            <div className="api-key-main">
              <strong>{key.name}</strong>
              <code>{key.prefix}...</code>
              <StateBadge apiKey={key} />
            </div>
            <div className="api-key-meta">
              <span>Scopes: {key.scopes.join(", ") || "-"}</span>
              <span>Created {formatDate(key.created_at)}</span>
              <span>Last used {key.last_used_at ? formatDate(key.last_used_at) : "never"}</span>
            </div>
            {canManage(key) && (
              <div className="api-key-actions">
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => setPending({ action: "rotate", key })}
                >
                  <RefreshCw size={14} />
                  Rotate
                </button>
                <button
                  type="button"
                  className="button secondary danger-text"
                  disabled={busy}
                  onClick={() => setPending({ action: "revoke", key })}
                >
                  <Trash2 size={14} />
                  Revoke
                </button>
              </div>
            )}
            {pending?.key.id === key.id && (
              <ConfirmBar pending={pending} busy={busy} onConfirm={confirm} onCancel={() => setPending(null)} />
            )}
          </li>
        ))}
      </ul>

      <details className="api-key-audit">
        <summary>Audit log ({sortedAudit.length})</summary>
        {sortedAudit.length ? (
          <ul>
            {sortedAudit.slice(0, AUDIT_SHOWN).map((event) => (
              <li key={event.id}>
                <span className="api-key-audit-action">{event.action}</span>
                <span>
                  <strong>{names.get(event.api_key_id) ?? event.api_key_id.slice(0, 8)}</strong>
                  {auditDetailText(event.detail) && <> ({auditDetailText(event.detail)})</>}
                </span>
                <span className="muted">
                  by <code>{event.actor}</code>, {formatDate(event.created_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No key events yet.</p>
        )}
        {sortedAudit.length > AUDIT_SHOWN && (
          <p className="muted">Showing the newest {AUDIT_SHOWN} of {sortedAudit.length} events.</p>
        )}
      </details>
    </>
  );
}

export function ApiKeysSection() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  return (
    <section className="card detail-card">
      <h2><KeyRound size={16} className="inline-icon" />API keys</h2>
      <p className="muted">
        API keys let your CI upload test results to Radius. Each key belongs to your organization and has scopes;
        for CI uploads use a key with only the <code>{UPLOAD_KEY_SCOPE}</code> scope.
      </p>
      {isAdmin ? (
        <AdminKeys />
      ) : (
        <div className="settings-note">
          Only organization admins can create, rotate or revoke API keys. Ask an admin of your organization for a key
          with the <code>{UPLOAD_KEY_SCOPE}</code> scope, then add it to your CI as described below.
        </div>
      )}
    </section>
  );
}
