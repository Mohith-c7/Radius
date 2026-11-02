"use client";

// Intent panel (IN-11): what this change is supposed to do, as a checklist of
// criteria with provenance and testability that a human can confirm, reject,
// edit and extend.
//
// SECURITY: criteria, rationales, source text and error messages are
// untrusted. They are rendered ONLY as React text nodes (no
// dangerouslySetInnerHTML, no markdown). Highlighting slices text with
// validated offsets (lib/intent-model.ts).

import {
  AlertTriangle,
  Bot,
  Check,
  FileText,
  History,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Upload,
  User,
  X,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import {
  addCriterion,
  getCriterionHistory,
  getIntent,
  getIntentDiff,
  getIntentSources,
  listSnapshots,
  patchCriterion,
  rebuildIntent,
  submitIntentSource,
  type SubmittableKind,
} from "../lib/intent";
import {
  CRITERION_STATES,
  DISPLAY_TRUNCATE_CHARS,
  MAX_CRITERION_CHARS,
  MAX_SOURCE_BYTES,
  actorLabel,
  applyOptimistic,
  classifyIntentError,
  countByState,
  countCodePoints,
  describeSourceFlags,
  filterByState,
  formatByteCount,
  formatKiB,
  formatPercent,
  highlightSegments,
  legalActions,
  methodLabel,
  needsAttention,
  sourceKindLabel,
  stateMeta,
  testabilityMeta,
  truncateText,
  validateCriterionText,
  validateSourceText,
  type BuildResult,
  type CriterionAction,
  type CriterionChange,
  type IntentCriterion,
  type IntentErrorInfo,
  type IntentSnapshot,
  type IntentSourceDetail,
  type SnapshotDiff,
  type SnapshotSummary,
} from "../lib/intent-model";
import { useAuth } from "./auth-provider";
import "./intent-panel.css";

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

type Load =
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error"; message: string }
  | { status: "ready" };

type Banner = { tone: "error" | "stale" | "notice"; message: string; lines?: string[] };

// ---------------------------------------------------------------------------
// Generic modal / drawer built on the native <dialog> (focus trap, Esc, focus
// restore are provided by the browser).
// ---------------------------------------------------------------------------

function Modal({
  open,
  onClose,
  title,
  variant = "dialog",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  variant?: "dialog" | "drawer";
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  if (!open) return null;
  return (
    <dialog
      ref={ref}
      className={`intent-modal ${variant}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="intent-modal-body">
        <div className="intent-modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="intent-icon-btn" aria-label={`Close ${title}`} onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

function Badge({ tone, children, title }: { tone: string; children: ReactNode; title?: string }) {
  return (
    <span className={`intent-badge ${tone}`} title={title}>
      {children}
    </span>
  );
}

function ErrorList({ info }: { info: IntentErrorInfo }) {
  if (info.kind === "spec_invalid" && info.lines.length > 0) {
    return (
      <div role="alert" className="intent-alert error">
        <strong>The spec has errors. Fix them and submit again.</strong>
        <ul>
          {info.lines.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <p role="alert" className="intent-alert error">
      {info.message}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Text with "show more"
// ---------------------------------------------------------------------------

function LongText({ text, max = DISPLAY_TRUNCATE_CHARS }: { text: string; max?: number }) {
  const [expanded, setExpanded] = useState(false);
  const view = useMemo(() => truncateText(text, max), [text, max]);
  return (
    <span className="intent-text">
      {expanded || !view.truncated ? text : `${view.text}...`}
      {view.truncated && (
        <button type="button" className="intent-link-btn" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Source viewer drawer with span highlighting
// ---------------------------------------------------------------------------

const VIEWER_LIMIT = 20000;

function SourceViewer({
  analysisId,
  criteria,
  focus,
  onClose,
}: {
  analysisId: string;
  criteria: IntentCriterion[];
  focus: IntentCriterion | null;
  onClose: () => void;
}) {
  const [sources, setSources] = useState<IntentSourceDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(focus?.span.source_id ?? null);
  const [showAll, setShowAll] = useState(false);
  const focusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    getIntentSources(analysisId)
      .then((rows) => {
        if (!active) return;
        setSources(rows);
        setSourceId((current) => current ?? rows[0]?.source_id ?? null);
      })
      .catch((e: unknown) => active && setError(classifyIntentError(e).message));
    return () => {
      active = false;
    };
  }, [analysisId]);

  const source = sources?.find((s) => s.source_id === sourceId) ?? null;
  const spans = useMemo(
    () =>
      source
        ? criteria
            .filter((c) => c.span.source_id === source.source_id)
            .map((c) => ({ id: c.id, start: c.span.start, end: c.span.end }))
        : [],
    [criteria, source],
  );
  const total = source ? countCodePoints(source.text) : 0;
  const focusEnd = focus && source && focus.span.source_id === source.source_id ? focus.span.end : 0;
  const expanded = showAll || total <= VIEWER_LIMIT || focusEnd > VIEWER_LIMIT;
  const view = useMemo(() => {
    if (!source) return { segments: [], invalid: 0 };
    const text = expanded ? source.text : Array.from(source.text).slice(0, VIEWER_LIMIT).join("");
    const limit = expanded ? total : VIEWER_LIMIT;
    // Clamp spans that run past the visible part; spans that start beyond it are dropped.
    const visible = spans
      .filter((s) => s.start < limit)
      .map((s) => ({ ...s, end: Math.min(s.end, limit) }));
    return highlightSegments(text, visible);
  }, [source, spans, expanded, total]);
  const focusInvalid = focus && source && focus.span.source_id === source.source_id
    ? highlightSegments(source.text, [{ id: focus.id, start: focus.span.start, end: focus.span.end }]).invalid > 0
    : false;

  useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center" });
  }, [view, focus]);

  return (
    <Modal open onClose={onClose} title="Source text" variant="drawer">
      {error && <p role="alert" className="intent-alert error">{error}</p>}
      {!sources && !error && (
        <p className="muted"><Loader2 size={14} className="spin" /> Loading sources...</p>
      )}
      {sources && sources.length === 0 && <p className="muted">No sources are stored for this analysis.</p>}
      {sources && sources.length > 0 && (
        <>
          <label className="intent-field">
            <span>Source</span>
            <select value={sourceId ?? ""} onChange={(e) => { setSourceId(e.target.value); setShowAll(false); }}>
              {sources.map((s) => (
                <option key={`${s.kind}:${s.source_id}`} value={s.source_id}>
                  {sourceKindLabel(s.kind)} ({s.source_id})
                </option>
              ))}
            </select>
          </label>
          {source && describeSourceFlags(source).map((flag) => (
            <p key={flag} className="intent-alert warn"><AlertTriangle size={14} /> {flag}</p>
          ))}
          {focusInvalid && (
            <p role="status" className="intent-alert warn">
              The highlighted range for this criterion does not fit the stored source text, so it cannot be shown.
            </p>
          )}
          {source && (
            <>
              <pre className="intent-source" tabIndex={0} aria-label="Source text with highlighted criteria">
                {view.segments.map((segment, index) => {
                  if (segment.ids.length === 0) return <span key={index}>{segment.text}</span>;
                  const isFocus = !!focus && segment.ids.includes(focus.id);
                  return (
                    <mark
                      key={index}
                      className={isFocus ? "focus" : undefined}
                      ref={isFocus && !focusRef.current ? (el) => { focusRef.current = el; } : undefined}
                    >
                      {segment.text}
                    </mark>
                  );
                })}
              </pre>
              {!expanded && (
                <button type="button" className="intent-link-btn" onClick={() => setShowAll(true)}>
                  Show all ({formatKiB(formatByteCount(source.text))})
                </button>
              )}
              {view.invalid > 0 && (
                <p className="muted">{view.invalid} highlighted range(s) did not fit the text and were skipped.</p>
              )}
            </>
          )}
        </>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// History / diff drawer
// ---------------------------------------------------------------------------

function DeltaList({ title, rows }: { title: string; rows: Array<{ key: string; text: string }> }) {
  if (rows.length === 0) return null;
  return (
    <section className="intent-diff-group">
      <h3>{title} ({rows.length})</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.key}><LongText text={row.text} /></li>
        ))}
      </ul>
    </section>
  );
}

function SnapshotHistory({ analysisId, current, onClose }: { analysisId: string; current: number; onClose: () => void }) {
  const [snaps, setSnaps] = useState<SnapshotSummary[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number>(current);
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);
  const [diffBusy, setDiffBusy] = useState(false);

  const load = useCallback(
    async (cursor?: number) => {
      setLoading(true);
      try {
        const page = await listSnapshots(analysisId, cursor);
        setSnaps((prev) => (cursor ? [...prev, ...page.snapshots] : page.snapshots));
        setNext(page.nextCursor);
        setFrom((prev) => prev ?? page.snapshots[1]?.version ?? null);
      } catch (e) {
        setError(classifyIntentError(e).message);
      } finally {
        setLoading(false);
      }
    },
    [analysisId],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function compare(event: FormEvent) {
    event.preventDefault();
    if (from === null) return;
    setDiffBusy(true);
    setError(null);
    try {
      setDiff(await getIntentDiff(analysisId, from, to));
    } catch (e) {
      setError(classifyIntentError(e).message);
    } finally {
      setDiffBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Intent history" variant="drawer">
      {error && <p role="alert" className="intent-alert error">{error}</p>}
      {snaps.length < 2 && !loading && <p className="muted">Only one version exists so far, so there is nothing to compare yet.</p>}
      {snaps.length >= 2 && (
        <form className="intent-compare" onSubmit={compare}>
          <label className="intent-field">
            <span>From version</span>
            <select value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value))}>
              {snaps.map((s) => <option key={s.id} value={s.version}>v{s.version}</option>)}
            </select>
          </label>
          <label className="intent-field">
            <span>To version</span>
            <select value={to} onChange={(e) => setTo(Number(e.target.value))}>
              {snaps.map((s) => <option key={s.id} value={s.version}>v{s.version}</option>)}
            </select>
          </label>
          <button type="submit" className="button secondary" disabled={diffBusy || from === null}>
            {diffBusy ? <Loader2 size={14} className="spin" /> : null} Compare
          </button>
        </form>
      )}
      {diff && (
        <div className="intent-diff" aria-live="polite">
          <p className="muted">Changes from v{diff.from_version} to v{diff.to_version}</p>
          {diff.added.length + diff.removed.length + diff.changed.length + diff.state_changed.length === 0 && (
            <p>No criterion changes between these versions.</p>
          )}
          <DeltaList title="Added" rows={diff.added.map((c) => ({ key: c.criterion_id, text: c.text }))} />
          <DeltaList title="Removed" rows={diff.removed.map((c) => ({ key: c.criterion_id, text: c.text }))} />
          <DeltaList
            title="Reworded"
            rows={diff.changed.map((c) => ({ key: c.criterion_id, text: `${c.text_before}  ->  ${c.text_after}` }))}
          />
          <DeltaList
            title="State changed"
            rows={diff.state_changed.map((c) => ({
              key: c.criterion_id,
              text: `${stateMeta(c.state_before).label} -> ${stateMeta(c.state_after).label}: ${c.text_after}`,
            }))}
          />
          {diff.sources_added.length + diff.sources_removed.length + diff.sources_changed.length > 0 && (
            <p className="muted">
              Sources: {diff.sources_added.length} added, {diff.sources_removed.length} removed, {diff.sources_changed.length} changed.
            </p>
          )}
        </div>
      )}
      <h3>Versions</h3>
      <ol className="intent-versions">
        {snaps.map((s) => (
          <li key={s.id}>
            <strong>v{s.version}</strong> {formatDate(s.created_at)} - {s.criteria_count} criteria, {s.source_count} sources
          </li>
        ))}
      </ol>
      {loading && <p className="muted"><Loader2 size={14} className="spin" /> Loading...</p>}
      {next !== null && !loading && (
        <button type="button" className="button secondary" onClick={() => void load(next)}>Load older versions</button>
      )}
    </Modal>
  );
}

function CriterionHistory({ analysisId, criterion, onClose }: { analysisId: string; criterion: IntentCriterion; onClose: () => void }) {
  const [rows, setRows] = useState<CriterionChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getCriterionHistory(analysisId, criterion.id)
      .then((r) => active && setRows(r))
      .catch((e: unknown) => active && setError(classifyIntentError(e).message));
    return () => {
      active = false;
    };
  }, [analysisId, criterion.id]);
  return (
    <Modal open onClose={onClose} title="Criterion history" variant="drawer">
      <p><LongText text={criterion.text} /></p>
      {error && <p role="alert" className="intent-alert error">{error}</p>}
      {!rows && !error && <p className="muted"><Loader2 size={14} className="spin" /> Loading...</p>}
      {rows && rows.length === 0 && <p className="muted">No decisions recorded yet.</p>}
      {rows && rows.length > 0 && (
        <ol className="intent-versions">
          {rows.map((row, index) => (
            <li key={index}>
              <strong>{stateMeta(row.old_state).label} to {stateMeta(row.new_state).label}</strong>{" "}
              (v{row.snapshot_version}) by {row.actor} on {formatDate(row.changed_at)}
              {row.reason && <div>Reason: {row.reason}</div>}
              {row.new_text && row.new_text !== row.old_text && <div>New text: <LongText text={row.new_text} /></div>}
            </li>
          ))}
        </ol>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Add intent / spec dialog
// ---------------------------------------------------------------------------

const KIND_OPTIONS: Array<{ value: SubmittableKind; label: string; hint: string }> = [
  { value: "spec_file", label: ".radius/intent.yml", hint: "Paste the contents of .radius/intent.yml. Errors are reported with line numbers." },
  { value: "agent_prompt", label: "Agent prompt", hint: "The instructions that were given to the coding agent." },
  { value: "pr_body", label: "PR description", hint: "Acceptance criteria written in the pull request body." },
  { value: "issue", label: "Linked issue", hint: "The text of the issue this change closes." },
  { value: "pr_title", label: "PR title", hint: "A single-line summary of the change." },
];

function AddSourceDialog({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (kind: SubmittableKind, text: string) => Promise<BuildResult>;
}) {
  const [kind, setKind] = useState<SubmittableKind>("spec_file");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<IntentErrorInfo | null>(null);
  const [result, setResult] = useState<BuildResult | null>(null);
  const bytes = formatByteCount(text);
  const over = bytes > MAX_SOURCE_BYTES;
  const hint = KIND_OPTIONS.find((k) => k.value === kind)?.hint;
  const countId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const check = validateSourceText(text);
    if (!check.ok) {
      setError({ kind: "other", message: check.message, code: null });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await onSubmit(kind, text));
    } catch (e) {
      setError(classifyIntentError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Add intent or spec">
      {result ? (
        <div role="status">
          <p>
            {result.created
              ? `Saved. Intent is now version ${result.snapshot.version} with ${result.snapshot.criteria_count} criteria.`
              : "Saved. The criteria did not change, so no new version was created."}
          </p>
          {(result.sanitization.removed.length > 0 || result.sanitization.flagged.length > 0) && (
            <p className="intent-alert warn">
              <AlertTriangle size={14} /> Radius cleaned the text before storing it.
              {result.sanitization.removed.length > 0 && ` Removed: ${result.sanitization.removed.join(", ")}.`}
              {result.sanitization.flagged.length > 0 && ` Flagged: ${result.sanitization.flagged.join(", ")}.`}
            </p>
          )}
          <button type="button" className="button" onClick={onClose}>Done</button>
        </div>
      ) : (
        <form onSubmit={submit} className="intent-form">
          <label className="intent-field">
            <span>What are you adding?</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as SubmittableKind)}>
              {KIND_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          {hint && <p className="muted">{hint}</p>}
          <label className="intent-field">
            <span>Text</span>
            <textarea
              rows={12}
              value={text}
              onChange={(e) => setText(e.target.value)}
              aria-describedby={countId}
              aria-invalid={over}
              spellCheck={false}
              autoFocus
            />
          </label>
          <p id={countId} className={over ? "intent-count over" : "intent-count"} aria-live="polite">
            {formatKiB(bytes)} of {formatKiB(MAX_SOURCE_BYTES)}{over ? " - too long" : ""}
          </p>
          {error && <ErrorList info={error} />}
          <div className="intent-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="button" disabled={busy || over || text.trim() === ""}>
              {busy ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} Extract criteria
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Criterion row
// ---------------------------------------------------------------------------

function CriterionRow({
  criterion,
  pending,
  error,
  registerRef,
  onAction,
  onViewSource,
  onHistory,
}: {
  criterion: IntentCriterion;
  pending: boolean;
  error: string | null;
  registerRef: (id: string, el: HTMLLIElement | null) => void;
  onAction: (id: string, action: CriterionAction, text?: string) => void;
  onViewSource: (c: IntentCriterion) => void;
  onHistory: (c: IntentCriterion) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(criterion.text);
  const [draftError, setDraftError] = useState<string | null>(null);
  const editRef = useRef<HTMLTextAreaElement>(null);
  const state = stateMeta(criterion.state);
  const testability = testabilityMeta(criterion.testability);
  const method = methodLabel(criterion.origin.method);
  const actions = legalActions(criterion.state);
  const label = truncateText(criterion.text, 60).text;
  const draftLen = countCodePoints(draft);

  useEffect(() => {
    if (editing) editRef.current?.focus();
  }, [editing]);

  function startEdit() {
    setDraft(criterion.text);
    setDraftError(null);
    setEditing(true);
  }

  function saveEdit(event: FormEvent) {
    event.preventDefault();
    const check = validateCriterionText(draft, criterion.text);
    if (!check.ok) {
      setDraftError(check.message);
      return;
    }
    setEditing(false);
    onAction(criterion.id, "edit", check.text);
  }

  const buttonProps = (action: CriterionAction) => ({
    type: "button" as const,
    disabled: pending,
    "aria-label": `${action[0].toUpperCase()}${action.slice(1)} criterion: ${label}`,
  });

  return (
    <li
      ref={(el) => registerRef(criterion.id, el)}
      tabIndex={-1}
      className={`intent-row tone-${state.tone}`}
      data-state={criterion.state}
      aria-busy={pending}
    >
      <div className="intent-row-top">
        <Badge tone={state.tone} title={state.explanation}>
          {criterion.state === "needs_reconfirmation" || criterion.state === "orphaned" ? <AlertTriangle size={12} /> : null}
          {state.label}
        </Badge>
        <Badge tone={testability.tone} title={testability.tooltip}>{testability.label}</Badge>
        <span className="muted">Weight {formatPercent(criterion.weight)}</span>
        {pending && <Loader2 size={14} className="spin" aria-label="Saving" />}
      </div>

      {editing ? (
        <form onSubmit={saveEdit} className="intent-form">
          <label className="intent-field">
            <span>Criterion wording</span>
            <textarea
              ref={editRef}
              rows={3}
              value={draft}
              aria-invalid={draftLen > MAX_CRITERION_CHARS || !!draftError}
              onChange={(e) => { setDraft(e.target.value); setDraftError(null); }}
              onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setEditing(false); } }}
            />
          </label>
          <p className={draftLen > MAX_CRITERION_CHARS ? "intent-count over" : "intent-count"} aria-live="polite">
            {draftLen} / {MAX_CRITERION_CHARS}
          </p>
          {draftError && <p role="alert" className="intent-alert error">{draftError}</p>}
          <div className="intent-actions">
            <button type="button" className="button secondary" onClick={() => setEditing(false)}>Cancel</button>
            <button type="submit" className="button" disabled={draftLen > MAX_CRITERION_CHARS}>Save edit</button>
          </div>
        </form>
      ) : (
        <p className="intent-criterion-text"><LongText text={criterion.text} /></p>
      )}

      {state.tone === "warn" || state.tone === "bad" ? (
        <p className={`intent-alert ${state.tone === "bad" ? "error" : "warn"}`}>
          <AlertTriangle size={14} /> {state.explanation}
        </p>
      ) : null}
      {testability.guidance && <p className="intent-guidance"><Sparkles size={13} /> {testability.guidance}</p>}

      <p className="intent-provenance muted">
        {criterion.origin.method === "human" ? <User size={13} /> : <Bot size={13} />}{" "}
        {sourceKindLabel(criterion.origin.source_kind)} / {method.label}
        {method.verify && <Badge tone="warn" title="Proposed by a language model. A human must verify it.">LLM-proposed - verify</Badge>}
      </p>

      {criterion.testability_rationale && (
        <details className="intent-details">
          <summary>Why this testability rating</summary>
          <p><LongText text={criterion.testability_rationale} /></p>
        </details>
      )}

      {error && <p role="alert" className="intent-alert error">{error}</p>}

      <div className="intent-row-actions">
        {actions.includes("confirm") && (
          <button {...buttonProps("confirm")} className="button" onClick={() => onAction(criterion.id, "confirm")}>
            <Check size={14} /> Confirm
          </button>
        )}
        {actions.includes("edit") && !editing && (
          <button {...buttonProps("edit")} className="button secondary" onClick={startEdit}>
            <Pencil size={14} /> Edit
          </button>
        )}
        {actions.includes("reject") && (
          <button {...buttonProps("reject")} className="button secondary" onClick={() => onAction(criterion.id, "reject")}>
            <X size={14} /> Reject
          </button>
        )}
        {actions.includes("reopen") && (
          <button {...buttonProps("reopen")} className="button secondary" onClick={() => onAction(criterion.id, "reopen")}>
            <RotateCcw size={14} /> Reopen
          </button>
        )}
        <button type="button" className="intent-link-btn" aria-label={`View source for criterion: ${label}`} onClick={() => onViewSource(criterion)}>
          <FileText size={14} /> Source
        </button>
        <button type="button" className="intent-link-btn" aria-label={`History of criterion: ${label}`} onClick={() => onHistory(criterion)}>
          <History size={14} /> History
        </button>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Add criterion form
// ---------------------------------------------------------------------------

function AddCriterionForm({ onAdd, onCancel }: { onAdd: (text: string) => Promise<void>; onCancel: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const len = countCodePoints(text);
  useEffect(() => ref.current?.focus(), []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const check = validateCriterionText(text);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onAdd(check.text);
    } catch (e) {
      setError(classifyIntentError(e).message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="intent-form intent-add">
      <label className="intent-field">
        <span>New criterion</span>
        <textarea
          ref={ref}
          rows={3}
          value={text}
          placeholder="Users can reset their password with a link that expires after 1 hour"
          aria-invalid={len > MAX_CRITERION_CHARS || !!error}
          onChange={(e) => { setText(e.target.value); setError(null); }}
          onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
        />
      </label>
      <p className={len > MAX_CRITERION_CHARS ? "intent-count over" : "intent-count"} aria-live="polite">
        {len} / {MAX_CRITERION_CHARS}. It is added as confirmed.
      </p>
      {error && <p role="alert" className="intent-alert error">{error}</p>}
      <div className="intent-actions">
        <button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="button" disabled={busy || len > MAX_CRITERION_CHARS || text.trim() === ""}>
          {busy ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add criterion
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function IntentPanel({ analysisId }: { analysisId: string }) {
  const { user } = useAuth();
  const actor = actorLabel(user);

  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [snapshot, setSnapshot] = useState<IntentSnapshot | null>(null);
  const [criteria, setCriteria] = useState<IntentCriterion[]>([]);
  // The ETag is a ref (not state) so back-to-back writes always send the newest one.
  const etagRef = useRef<string | null>(null);
  const writeQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [filter, setFilter] = useState<string>("all");
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<Banner | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [viewer, setViewer] = useState<{ focus: IntentCriterion | null } | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [historyFor, setHistoryFor] = useState<IntentCriterion | null>(null);
  const rows = useRef(new Map<string, HTMLLIElement>());
  const alive = useRef(true);
  const addButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const apply = useCallback((snap: IntentSnapshot, tag: string | null) => {
    setSnapshot(snap);
    setCriteria(snap.criteria);
    etagRef.current = tag ?? snap.etag ?? null;
    setLoad({ status: "ready" });
  }, []);

  const reload = useCallback(
    async (opts: { keepBanner?: boolean } = {}) => {
      if (!opts.keepBanner) setBanner(null);
      setRowErrors({});
      try {
        const { snapshot: snap, etag: tag } = await getIntent(analysisId);
        if (alive.current) apply(snap, tag);
      } catch (e) {
        if (!alive.current) return;
        const info = classifyIntentError(e);
        if (info.kind === "not_found") {
          setSnapshot(null);
          setCriteria([]);
          setLoad({ status: "empty" });
        } else {
          setLoad({ status: "error", message: info.message });
        }
      }
    },
    [analysisId, apply],
  );

  useEffect(() => {
    setLoad({ status: "loading" });
    void reload();
  }, [reload]);

  function showError(info: IntentErrorInfo) {
    if (info.kind === "stale") setBanner({ tone: "stale", message: info.message });
    else setBanner({ tone: "error", message: info.message, lines: info.kind === "spec_invalid" ? info.lines : undefined });
  }

  const onAction = useCallback(
    (id: string, action: CriterionAction, text?: string) => {
      let before: IntentCriterion[] = [];
      setCriteria((list) => {
        before = list;
        return applyOptimistic(list, id, action, text);
      });
      setPending((p) => new Set(p).add(id));
      setRowErrors((e) => Object.fromEntries(Object.entries(e).filter(([key]) => key !== id)));
      const run = writeQueue.current.then(async () => {
        try {
          const result = await patchCriterion(
            analysisId,
            id,
            action === "edit" ? { action, text: text ?? "" } : { action },
            { ifMatch: etagRef.current, actor },
          );
          if (!alive.current) return;
          setCriteria((list) => list.map((c) => (c.id === id ? result.criterion : c)));
          etagRef.current = result.etag;
          setBanner({ tone: "notice", message: `Criterion ${stateMeta(result.criterion.state).label.toLowerCase()}.` });
        } catch (e) {
          if (!alive.current) return;
          const info = classifyIntentError(e);
          // Roll back only this criterion's optimistic change.
          const original = before.find((c) => c.id === id);
          if (original) setCriteria((list) => list.map((c) => (c.id === id ? original : c)));
          if (info.kind === "stale") showError(info);
          else setRowErrors((errs) => ({ ...errs, [id]: info.message }));
        } finally {
          if (alive.current) {
            setPending((p) => {
              const next = new Set(p);
              next.delete(id);
              return next;
            });
            // The action button may have disappeared; keep keyboard focus on the row.
            requestAnimationFrame(() => rows.current.get(id)?.focus());
          }
        }
      });
      writeQueue.current = run;
    },
    [analysisId, actor],
  );

  async function guarded<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setBanner(null);
    try {
      return await fn();
    } catch (e) {
      showError(classifyIntentError(e));
      return undefined;
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function onRebuild() {
    const result = await guarded(() => rebuildIntent(analysisId, { ifMatch: etagRef.current, actor }));
    if (!result || !alive.current) return;
    apply(result.snapshot, result.snapshot.etag);
    setBanner({
      tone: "notice",
      message: result.created ? `Rebuilt: now version ${result.snapshot.version}.` : "Rebuilt: nothing changed.",
    });
  }

  async function submitSource(kind: SubmittableKind, text: string): Promise<BuildResult> {
    // Errors propagate to the dialog so it can show line-numbered messages.
    const result = await submitIntentSource(analysisId, { kind, text }, { ifMatch: etagRef.current, actor }).catch((e) => {
      const info = classifyIntentError(e);
      if (info.kind === "stale") showError(info);
      throw e;
    });
    if (alive.current) apply(result.snapshot, result.snapshot.etag);
    return result;
  }

  async function onAddCriterion(text: string) {
    try {
      await addCriterion(analysisId, { text }, { ifMatch: etagRef.current, actor });
    } catch (e) {
      const info = classifyIntentError(e);
      if (info.kind === "stale") {
        setShowAdd(false);
        showError(info);
        return;
      }
      throw e;
    }
    setShowAdd(false);
    await reload();
    setBanner({ tone: "notice", message: "Criterion added and confirmed." });
    requestAnimationFrame(() => addButton.current?.focus());
  }

  const counts = useMemo(() => countByState(criteria), [criteria]);
  const attention = needsAttention(criteria);
  const visible = useMemo(() => {
    const order = new Map(CRITERION_STATES.map((s, i) => [s as string, i]));
    return filterByState(criteria, filter)
      .map((c, i) => ({ c, i }))
      .sort((a, b) => (order.get(a.c.state) ?? 99) - (order.get(b.c.state) ?? 99) || a.i - b.i)
      .map((x) => x.c);
  }, [criteria, filter]);
  const registerRef = useCallback((id: string, el: HTMLLIElement | null) => {
    if (el) rows.current.set(id, el);
    else rows.current.delete(id);
  }, []);

  return (
    <section className="card intent-panel" id="intent" aria-labelledby="intent-heading">
      <div className="card-heading">
        <div>
          <h2 id="intent-heading">Intent: what this change must prove</h2>
          <p>
            Criteria extracted from the PR, issues and specs. Confirm what is a real requirement; Radius only
            verifies confirmed criteria.
          </p>
        </div>
        {load.status === "ready" && snapshot && (
          <div className="intent-header-actions">
            <button type="button" className="button secondary" onClick={() => setShowAdd((v) => !v)} ref={addButton} aria-expanded={showAdd}>
              <Plus size={14} /> Add criterion
            </button>
            <button type="button" className="button secondary" onClick={() => setShowSources(true)}>
              <Upload size={14} /> Add intent / spec
            </button>
            <button type="button" className="button secondary" onClick={() => void onRebuild()} disabled={busy}>
              {busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Rebuild
            </button>
            <button type="button" className="button secondary" onClick={() => setShowHistory(true)}>
              <History size={14} /> History
            </button>
          </div>
        )}
      </div>

      <div className="intent-body">
        <div aria-live="polite" role="status">
          {banner?.tone === "notice" && <p className="intent-alert ok">{banner.message}</p>}
        </div>
        {banner && banner.tone !== "notice" && (
          <div role="alert" className={`intent-alert ${banner.tone === "stale" ? "warn" : "error"}`}>
            <p>{banner.message}</p>
            {banner.lines && <ul>{banner.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
            {banner.tone === "stale" && (
              <button type="button" className="button" onClick={() => void reload()}>
                <RefreshCw size={14} /> Reload latest
              </button>
            )}
          </div>
        )}

        {load.status === "loading" && (
          <p className="muted"><Loader2 size={16} className="spin" /> Loading intent...</p>
        )}

        {load.status === "error" && (
          <div role="alert" className="intent-alert error">
            <p>Could not load intent: {load.message}</p>
            <button type="button" className="button secondary" onClick={() => { setLoad({ status: "loading" }); void reload(); }}>
              <RefreshCw size={14} /> Try again
            </button>
          </div>
        )}

        {load.status === "empty" && (
          <div className="intent-empty">
            <strong>No intent recorded for this change yet</strong>
            <p className="muted">
              Radius needs to know what this change is supposed to do. Add an agent prompt, a PR description with
              acceptance criteria, an issue, or a <code>.radius/intent.yml</code> file, and Radius will turn it into a
              checklist you can confirm.
            </p>
            <pre className="intent-example" aria-label="Example .radius/intent.yml">{`version: 1
criteria:
  - text: "Users can reset their password with an emailed link"
  - text: "Reset links expire after 1 hour"`}</pre>
            <button type="button" className="button" onClick={() => setShowSources(true)}>
              <Upload size={14} /> Add intent / spec
            </button>
          </div>
        )}

        {load.status === "ready" && snapshot && (
          <>
            <div className="intent-meta">
              <Badge tone="info">Version {snapshot.version}</Badge>
              <span className="muted">Updated {formatDate(snapshot.created_at)}</span>
              <span className="muted">{criteria.length} criteria</span>
            </div>
            <ul className="intent-sources" aria-label="Sources">
              {snapshot.sources.length === 0 && <li className="muted">No sources.</li>}
              {snapshot.sources.map((s) => {
                const flags = describeSourceFlags(s);
                return (
                  <li key={`${s.kind}:${s.source_id}`}>
                    <Badge tone={flags.length ? "warn" : "neutral"} title={flags.join(" ")}>
                      {flags.length > 0 && <AlertTriangle size={12} />}
                      {sourceKindLabel(s.kind)}
                      {s.truncated && " (truncated)"}
                      {s.suspicious_content_removed && " (cleaned)"}
                    </Badge>
                  </li>
                );
              })}
            </ul>
            {snapshot.sources.some((s) => describeSourceFlags(s).length > 0) && (
              <ul className="intent-alert warn intent-source-flags">
                {snapshot.sources.flatMap((s) =>
                  describeSourceFlags(s).map((flag) => (
                    <li key={`${s.source_id}:${flag}`}>
                      <strong>{sourceKindLabel(s.kind)}:</strong> {flag}
                    </li>
                  )),
                )}
              </ul>
            )}

            {attention > 0 && (
              <p role="alert" className="intent-alert warn">
                <AlertTriangle size={14} /> {attention} criteri{attention === 1 ? "on needs" : "a need"} your attention
                (needs reconfirmation or orphaned).{" "}
                <button type="button" className="intent-link-btn" onClick={() => setFilter(counts.needs_reconfirmation ? "needs_reconfirmation" : "orphaned")}>
                  Show them
                </button>
              </p>
            )}

            {showAdd && <AddCriterionForm onAdd={onAddCriterion} onCancel={() => { setShowAdd(false); addButton.current?.focus(); }} />}

            <div className="intent-filters" role="group" aria-label="Filter criteria by state">
              <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
                All ({criteria.length})
              </button>
              {CRITERION_STATES.filter((s) => (counts[s] ?? 0) > 0).map((s) => (
                <button key={s} type="button" aria-pressed={filter === s} onClick={() => setFilter(s)}>
                  {stateMeta(s).label} ({counts[s]})
                </button>
              ))}
            </div>

            {criteria.length === 0 ? (
              <p className="muted">
                The sources were read but no criteria were found. Add one yourself, or add a clearer description of
                the intended behavior.
              </p>
            ) : visible.length === 0 ? (
              <p className="muted">No criteria in this state.</p>
            ) : (
              <ul className="intent-list">
                {visible.map((c) => (
                  <CriterionRow
                    key={c.id}
                    criterion={c}
                    pending={pending.has(c.id)}
                    error={rowErrors[c.id] ?? null}
                    registerRef={registerRef}
                    onAction={onAction}
                    onViewSource={(crit) => setViewer({ focus: crit })}
                    onHistory={setHistoryFor}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {showSources && <AddSourceDialog onClose={() => setShowSources(false)} onSubmit={submitSource} />}
      {viewer && (
        <SourceViewer analysisId={analysisId} criteria={criteria} focus={viewer.focus} onClose={() => setViewer(null)} />
      )}
      {showHistory && snapshot && (
        <SnapshotHistory analysisId={analysisId} current={snapshot.version} onClose={() => setShowHistory(false)} />
      )}
      {historyFor && <CriterionHistory analysisId={analysisId} criterion={historyFor} onClose={() => setHistoryFor(null)} />}
    </section>
  );
}
