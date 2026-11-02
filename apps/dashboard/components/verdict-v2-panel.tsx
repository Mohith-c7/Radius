"use client";

// Verdict v2 panel (VS-10): the per-criterion verdict of a pull request, the
// justification tree, and the evidence behind each criterion.
//
// SECURITY: criterion text, test ids, tamper reasons and snippets are
// untrusted. They are rendered ONLY as React text nodes (no
// dangerouslySetInnerHTML, no markdown, no links built from them), as in
// components/intent-panel.tsx.
//
// HONESTY: v2 alpha judges assertion strength read from test code. It has no
// mutation testing and no calibration, so the panel always says "static
// assertion strength only" and "uncalibrated" and never shows a v2 score.
//
// ACCESSIBILITY: native table, buttons (aria-expanded) and details elements;
// every state is conveyed by an icon AND text, never by colour alone.

import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock,
  Loader2,
  MinusCircle,
  RefreshCw,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";

import { getVerdictV2 } from "../lib/verdict-v2";
import {
  classifyVerdictError,
  evidenceSummary,
  flagLabel,
  formatPercent,
  formatScore,
  headerTags,
  headline,
  itemStatusLabel,
  justificationTree,
  massBar,
  outcomeMeta,
  qualityFactors,
  severityTone,
  shortSha,
  stateMeta,
  summaryCounts,
  supportBar,
  v1Label,
  verdictMeta,
  type Criterion,
  type EvidenceItem,
  type IconName,
  type Tone,
  type VerdictV2,
} from "../lib/verdict-v2-model";
import "./verdict-v2-panel.css";

const ICONS: Record<IconName, typeof CheckCircle2> = {
  check: CheckCircle2,
  alert: AlertTriangle,
  help: CircleHelp,
  x: XCircle,
  minus: MinusCircle,
  shield: ShieldAlert,
  clock: Clock,
  ban: Ban,
};

function Chip({ tone, icon, children }: { tone: Tone; icon?: IconName; children: ReactNode }) {
  const Icon = icon ? ICONS[icon] : null;
  return (
    <span className={`vv2-chip ${tone}`}>
      {Icon ? <Icon size={13} aria-hidden="true" /> : null}
      <span>{children}</span>
    </span>
  );
}

type Load =
  | { status: "loading" }
  | { status: "disabled" }
  | { status: "not_computed" }
  | { status: "error"; message: string }
  | { status: "ready"; verdict: VerdictV2 };

export function VerdictV2Panel({ analysisId }: { analysisId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [reloading, setReloading] = useState(false);
  const latest = useRef(0);
  const headingId = useId();

  const refresh = useCallback(async () => {
    const ticket = ++latest.current;
    setReloading(true);
    try {
      const { verdict } = await getVerdictV2(analysisId);
      if (ticket === latest.current) setLoad({ status: "ready", verdict });
    } catch (error) {
      if (ticket !== latest.current) return;
      const info = classifyVerdictError(error);
      if (info.kind === "disabled") setLoad({ status: "disabled" });
      else if (info.kind === "not_computed") setLoad({ status: "not_computed" });
      else setLoad({ status: "error", message: info.message });
    } finally {
      if (ticket === latest.current) setReloading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    setLoad({ status: "loading" });
    void refresh();
    return () => {
      latest.current += 1; // ignore a response that arrives after unmount / id change
    };
  }, [refresh]);

  // Flag off (404 disabled): the feature does not exist for this deployment.
  if (load.status === "disabled") return null;

  return (
    <section id="verdict" className="card vv2-panel" aria-labelledby={headingId}>
      <div className="card-heading">
        <div>
          <h2 id={headingId}>Verdict (v2 alpha)</h2>
          <p>Per-criterion evidence behind this pull request. {"Static assertion strength only."}</p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => void refresh()}
          disabled={reloading}
          aria-label="Reload verdict"
        >
          {reloading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
          Reload
        </button>
      </div>
      <div className="vv2-body" aria-live="polite" aria-busy={load.status === "loading"}>
        {load.status === "loading" ? (
          <p className="vv2-state" role="status">
            <Loader2 size={16} className="spin" aria-hidden="true" /> Loading the verdict...
          </p>
        ) : null}
        {load.status === "not_computed" ? (
          <p className="vv2-state" role="status">
            <CircleHelp size={16} aria-hidden="true" /> No v2 verdict has been computed for this
            analysis yet. It appears after the analysis finishes and an intent is available.
          </p>
        ) : null}
        {load.status === "error" ? (
          <div className="vv2-state error" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>Could not load the verdict: {load.message}</span>
          </div>
        ) : null}
        {load.status === "ready" ? <VerdictView verdict={load.verdict} /> : null}
      </div>
    </section>
  );
}

function VerdictView({ verdict }: { verdict: VerdictV2 }) {
  const meta = verdictMeta(verdict.verdict, verdict.pending, verdict.status);
  const VerdictIcon = ICONS[meta.icon];
  const available = verdict.status === "ok";
  return (
    <>
      <header className="vv2-head">
        <p className={`vv2-verdict ${meta.tone}`}>
          <VerdictIcon size={20} aria-hidden="true" />
          <strong>{meta.label}</strong>
        </p>
        <p className="vv2-why">{headline(verdict)}</p>
        <ul className="vv2-tags" aria-label="About this verdict">
          {headerTags(verdict).map((tag) => (
            <li key={tag.key}>
              <Chip tone={tag.tone}>{tag.label}</Chip>
            </li>
          ))}
        </ul>
      </header>

      {available ? (
        <>
          <SummaryStrip verdict={verdict} />
          <CriteriaTable verdict={verdict} />
          <TamperSection verdict={verdict} />
          <ListSection
            title="Changed code with no stated criterion"
            items={verdict.unlinked_symbols}
            empty="Every behavioural change is covered by a criterion."
          />
          <NextActions verdict={verdict} />
          <JustificationSection verdict={verdict} />
          {verdict.v1 ? (
            <details className="vv2-details">
              <summary>Legacy v1 result (file-level selection, heuristic score)</summary>
              <p>{v1Label(verdict.v1)}</p>
              <p className="vv2-muted">
                The v1 score is a heuristic and not a probability. v2 shows no score.
              </p>
            </details>
          ) : null}
        </>
      ) : null}

      <footer className="vv2-provenance">
        <dl>
          <div><dt>Algorithm</dt><dd>{verdict.algo_version || "-"}</dd></div>
          <div><dt>Profile</dt><dd>{verdict.profile || "-"}</dd></div>
          <div><dt>Revision</dt><dd>{verdict.revision}</dd></div>
          <div><dt>Commit</dt><dd>{shortSha(verdict.head_sha) || "-"}</dd></div>
          <div><dt>Mode</dt><dd>{verdict.mode || "-"}</dd></div>
          <div><dt>Computed</dt><dd>{verdict.computed_at ?? "-"}</dd></div>
          <div><dt>Config digest</dt><dd className="vv2-mono">{verdict.justification?.config_digest || "-"}</dd></div>
          <div><dt>Inputs digest</dt><dd className="vv2-mono">{verdict.justification?.inputs_digest || "-"}</dd></div>
        </dl>
      </footer>
    </>
  );
}

function SummaryStrip({ verdict }: { verdict: VerdictV2 }) {
  const bars = massBar(verdict.summary, verdict.uimMax, verdict.minIntentCoverage);
  return (
    <div className="vv2-summary">
      <ul className="vv2-counts" aria-label="Criteria by state">
        {summaryCounts(verdict.summary).map(({ state, count, meta }) => (
          <li key={state}>
            <Chip tone={meta.tone} icon={meta.icon}>
              {count} {meta.label.toLowerCase()}
            </Chip>
          </li>
        ))}
      </ul>
      <div className="vv2-meters">
        <label className="vv2-meter">
          <span>
            Unproven intent mass {formatScore(verdict.summary.uim)}
            {bars.uimMaxPercent !== null ? ` (limit ${(bars.uimMaxPercent / 100).toFixed(2)})` : ""}
            {bars.uimOverLimit ? ": over the limit" : ""}
          </span>
          <meter min={0} max={1} value={verdict.summary.uim} />
        </label>
        <label className="vv2-meter">
          <span>
            Intent coverage {formatPercent(verdict.summary.intent_coverage)}
            {bars.minCoveragePercent !== null ? ` (minimum ${bars.minCoveragePercent}%)` : ""}
          </span>
          <meter min={0} max={1} value={verdict.summary.intent_coverage} />
        </label>
      </div>
    </div>
  );
}

function CriteriaTable({ verdict }: { verdict: VerdictV2 }) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  if (verdict.criteria.length === 0) {
    return (
      <p className="vv2-state" role="status">
        <CircleHelp size={16} aria-hidden="true" /> No criteria were evaluated. Add or confirm
        acceptance criteria in the intent panel above.
      </p>
    );
  }
  return (
    <div className="table-wrap">
      <table className="vv2-table">
        <caption>
          Criteria. Support must reach the threshold {formatScore(verdict.tauSupport)} to count as
          proven.
        </caption>
        <thead>
          <tr>
            <th scope="col"><span className="vv2-sr">Details</span></th>
            <th scope="col">Criterion</th>
            <th scope="col">State</th>
            <th scope="col">Support</th>
            <th scope="col">Evidence</th>
            <th scope="col">Flags</th>
          </tr>
        </thead>
        <tbody>
          {verdict.criteria.map((criterion, index) => (
            <CriterionRows
              key={`${criterion.criterion_id}-${index}`}
              criterion={criterion}
              tau={verdict.tauSupport}
              expanded={open.has(criterion.criterion_id)}
              onToggle={() => toggle(criterion.criterion_id)}
            />
          ))}
        </tbody>
      </table>
      {verdict.criteriaTruncated ? (
        <p className="vv2-muted">Only the first criteria are shown.</p>
      ) : null}
    </div>
  );
}

function CriterionRows({
  criterion,
  tau,
  expanded,
  onToggle,
}: {
  criterion: Criterion;
  tau: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const detailsId = useId();
  const meta = stateMeta(criterion.state);
  const bar = supportBar(criterion, tau);
  const summary = evidenceSummary(criterion);
  const Chevron = expanded ? ChevronDown : ChevronRight;
  return (
    <>
      <tr data-state={criterion.state}>
        <td>
          <button
            type="button"
            className="vv2-toggle"
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={onToggle}
            aria-label={`${expanded ? "Hide" : "Show"} evidence for this criterion`}
          >
            <Chevron size={16} aria-hidden="true" />
          </button>
        </td>
        <th scope="row" className="vv2-criterion">{criterion.text || "(no text)"}</th>
        <td>
          <Chip tone={meta.tone} icon={meta.icon}>{meta.label}</Chip>
        </td>
        <td>
          <div className="vv2-bar" aria-hidden="true">
            <span className={`vv2-fill ${meta.tone}`} style={{ width: `${bar.percent}%` }} />
            <span className="vv2-marker" style={{ left: `${bar.tauPercent}%` }} />
          </div>
          <span className="vv2-small">{bar.text}</span>
        </td>
        <td className="vv2-small">{summary.text}</td>
        <td>
          {criterion.flags.length === 0 ? (
            <span className="vv2-muted">-</span>
          ) : (
            <ul className="vv2-flags">
              {criterion.flags.map((flag) => (
                <li key={flag}>
                  <Chip tone={flag === "tampered" ? "bad" : "neutral"}>{flagLabel(flag)}</Chip>
                </li>
              ))}
            </ul>
          )}
        </td>
      </tr>
      {expanded ? (
        <tr id={detailsId} className="vv2-expanded">
          <td />
          <td colSpan={5}>
            <CriterionDetails criterion={criterion} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function CriterionDetails({ criterion }: { criterion: Criterion }) {
  const meta = stateMeta(criterion.state);
  return (
    <div className="vv2-detail">
      <p className="vv2-muted">{meta.description}</p>
      {criterion.reasons.length > 0 ? (
        <ul className="vv2-reasons">
          {criterion.reasons.map((reason, index) => (
            <li key={`${reason.code}-${index}`}>{reason.detail || reason.code}</li>
          ))}
        </ul>
      ) : null}
      {criterion.best_link ? (
        <p className="vv2-small">
          Best link: criterion to symbol {formatScore(criterion.best_link.l_cs)}, symbol to test{" "}
          {formatScore(criterion.best_link.l_st)}, criterion to test{" "}
          {formatScore(criterion.best_link.r_ct)}. Symbol:{" "}
          <code className="vv2-mono">{criterion.best_link.symbol_id}</code>
        </p>
      ) : null}
      {criterion.items.length === 0 ? (
        <p className="vv2-small">No test is linked to this criterion.</p>
      ) : (
        <ul className="vv2-items" aria-label="Evidence">
          {criterion.items.map((item, index) => (
            <EvidenceRow key={`${item.evidence_id}-${index}`} item={item} />
          ))}
        </ul>
      )}
      {criterion.itemsTruncated ? <p className="vv2-muted">Only the first tests are shown.</p> : null}
    </div>
  );
}

function EvidenceRow({ item }: { item: EvidenceItem }) {
  const outcome = outcomeMeta(item.outcome);
  return (
    <li className="vv2-item">
      <p className="vv2-item-head">
        <code className="vv2-mono">{item.test_id || "(unknown test)"}</code>
        <Chip tone={outcome.tone} icon={outcome.icon}>{outcome.label}</Chip>
        <span className="vv2-small">{itemStatusLabel(item.status)}</span>
      </p>
      <dl className="vv2-factors">
        {qualityFactors(item).map((factor) => (
          <div key={factor.key}>
            <dt>{factor.label}</dt>
            <dd>
              <meter min={0} max={1} value={factor.value} aria-label={factor.label} />
              <span>
                {factor.value.toFixed(2)} <span className="vv2-muted">{factor.note}</span>
              </span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="vv2-small">
        Test quality {formatScore(item.q)} times link strength {formatScore(item.l)} gives
        contribution {formatScore(item.term)}.
      </p>
    </li>
  );
}

function TamperSection({ verdict }: { verdict: VerdictV2 }) {
  if (verdict.tamper_findings.length === 0) return null;
  return (
    <section aria-label="Tamper findings" className="vv2-section">
      <h3>Tamper findings ({verdict.tamper_findings.length})</h3>
      <ul className="vv2-list">
        {verdict.tamper_findings.map((finding, index) => (
          <li key={`${finding.finding_id}-${index}`}>
            <p className="vv2-item-head">
              <Chip tone={severityTone(finding.severity)} icon="shield">
                {finding.severity || "unknown"}
              </Chip>
              <strong>{finding.rule_id}</strong>
              <code className="vv2-mono">{finding.path}</code>
            </p>
            <p>{finding.reason}</p>
            {finding.old_snippet !== null || finding.new_snippet !== null ? (
              <details className="vv2-details">
                <summary>Before and after</summary>
                {finding.old_snippet !== null ? (
                  <>
                    <p className="vv2-small">Before</p>
                    <pre className="vv2-pre">{finding.old_snippet}</pre>
                  </>
                ) : null}
                {finding.new_snippet !== null ? (
                  <>
                    <p className="vv2-small">After</p>
                    <pre className="vv2-pre">{finding.new_snippet}</pre>
                  </>
                ) : null}
              </details>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ListSection({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <details className="vv2-details">
      <summary>
        {title} ({items.length})
      </summary>
      {items.length === 0 ? (
        <p className="vv2-muted">{empty}</p>
      ) : (
        <ul className="vv2-list">
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>
              <code className="vv2-mono">{item}</code>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function NextActions({ verdict }: { verdict: VerdictV2 }) {
  if (verdict.next_actions.length === 0) return null;
  return (
    <section aria-label="What to do next" className="vv2-section">
      <h3>What to do next</h3>
      <ol className="vv2-list">
        {verdict.next_actions.map((action, index) => (
          <li key={`${action.code}-${index}`}>{action.text}</li>
        ))}
      </ol>
    </section>
  );
}

function JustificationSection({ verdict }: { verdict: VerdictV2 }) {
  if (!verdict.justification) return null;
  const tree = justificationTree(verdict.justification);
  return (
    <details className="vv2-details">
      <summary>
        Why this verdict: {tree.firedCount} of {tree.rules.length} rules fired
      </summary>
      <p className="vv2-small">
        Decided by rule <strong>{tree.decidedBy || "-"}</strong>. Rules are checked in order and the
        first rule that fires decides.
      </p>
      <ol className="vv2-rules">
        {tree.rules.map((rule) => (
          <li key={rule.id} className={rule.decisive ? "decisive" : undefined}>
            <details>
              <summary>
                <span className="vv2-rule-id">{rule.id}</span> {rule.label}{" "}
                <Chip tone={rule.fired ? "warn" : "neutral"}>
                  {rule.fired ? (rule.decisive ? "fired, decided" : "fired") : "not fired"}
                </Chip>
              </summary>
              {rule.inputs.length > 0 ? (
                <dl className="vv2-inputs">
                  {rule.inputs.map((input) => (
                    <div key={input.key}>
                      <dt>{input.key}</dt>
                      <dd className="vv2-mono">{input.text}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="vv2-muted">No inputs recorded.</p>
              )}
              {rule.refs.map((ref) => (
                <p key={ref.key} className="vv2-small">
                  {ref.key}: <span className="vv2-mono">{ref.ids.join(", ")}</span>
                </p>
              ))}
            </details>
          </li>
        ))}
      </ol>
      {verdict.justification.thresholds.length > 0 ? (
        <>
          <p className="vv2-small">Thresholds</p>
          <dl className="vv2-inputs">
            {verdict.justification.thresholds.map((t) => (
              <div key={t.key}>
                <dt>{t.key}</dt>
                <dd className="vv2-mono">{t.text}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
    </details>
  );
}
