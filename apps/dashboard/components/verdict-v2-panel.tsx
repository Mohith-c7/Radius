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
import { followRefresh, onIntentChanged, type RefreshState } from "../lib/verdict-refresh";
import {
  authorHintCount,
  classifyVerdictError,
  disclaimerText,
  hasPolicySection,
  legendText,
  policyModeLabel,
  settingLine,
  stateLabel,
  waiverCodeLabel,
  waivedFindings,
  provenanceLabel,
  criterionBasisText,
  evidenceSummary,
  flagLabel,
  formatPercent,
  formatScore,
  headerTags,
  headline,
  itemStatusLabel,
  mutationGaps,
  mutationRunNote,
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
  | { status: "ready"; verdict: VerdictV2; refresh: RefreshState };

export function VerdictV2Panel({
  analysisId,
  onVerdict,
}: {
  analysisId: string;
  /** Reports the current result (null when off / not computed / failed / unavailable) so the page header can agree with this panel. */
  onVerdict?: (verdict: VerdictV2 | null) => void;
}) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [reloading, setReloading] = useState(false);
  const latest = useRef(0);
  const headingId = useId();

  const refresh = useCallback(async () => {
    const ticket = ++latest.current;
    setReloading(true);
    try {
      const { verdict, refresh } = await getVerdictV2(analysisId);
      if (ticket === latest.current) setLoad({ status: "ready", verdict, refresh });
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

  // A criterion was confirmed, edited or rejected: the worker recomputes the verdict a few
  // seconds later (DEC-033). Follow it with a bounded poll (about 30 s, widening delays).
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(
    () =>
      onIntentChanged(analysisId, () => {
        const ticket = ++latest.current;
        const current = loadRef.current;
        const baseline = current.status === "ready" ? current.verdict.revision : 0;
        if (current.status === "ready") {
          setLoad({ ...current, refresh: { pending: true, failed: false } });
        }
        setReloading(true);
        void followRefresh({
          baseline,
          load: () => getVerdictV2(analysisId),
          sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
          cancelled: () => ticket !== latest.current,
          onSnapshot: ({ verdict, refresh: state }) => {
            if (ticket === latest.current) setLoad({ status: "ready", verdict, refresh: state });
          },
        }).finally(() => {
          if (ticket === latest.current) setReloading(false);
        });
      }),
    [analysisId],
  );

  useEffect(() => {
    setLoad({ status: "loading" });
    void refresh();
    return () => {
      latest.current += 1; // ignore a response that arrives after unmount / id change
    };
  }, [refresh]);

  const onVerdictRef = useRef(onVerdict);
  onVerdictRef.current = onVerdict;
  useEffect(() => {
    if (load.status === "loading") return;
    onVerdictRef.current?.(load.status === "ready" ? load.verdict : null);
  }, [load]);

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
        {load.status === "ready" && load.refresh.pending ? (
          <p className="vv2-state" role="status">
            <Loader2 size={16} className={load.refresh.failed ? undefined : "spin"} aria-hidden="true" />{" "}
            {load.refresh.failed
              ? "The verdict below is out of date: updating it after your change failed and will be retried. Use Reload to check again."
              : "The verdict below is out of date: it is being recomputed after your change. It updates in a few seconds."}
          </p>
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
        <p className="vv2-disclaimer" role="note">
          <strong>
            {verdict.summary.evidence_basis === "static_and_mutation"
              ? "Alpha - static + sampled mutation evidence - uncalibrated."
              : "Alpha - static evidence only - uncalibrated."}
          </strong>{" "}
          {disclaimerText(verdict)}
        </p>
        <p className={`vv2-verdict ${meta.tone}`}>
          <VerdictIcon size={20} aria-hidden="true" />
          <strong>{verdict.presentation?.verdict_label || meta.label}</strong>
        </p>
        <p className="vv2-why">{headline(verdict)}</p>
        {verdict.presentation?.summary_text ? (
          <p className="vv2-why">{verdict.presentation.summary_text}</p>
        ) : null}
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
          {mutationRunNote(verdict) ? (
            <p className="vv2-small" role="note" data-testid="mutation-note">
              {mutationRunNote(verdict)}
            </p>
          ) : null}
          {authorHintCount(verdict) > 0 ? (
            <p className="vv2-state" role="status">
              <AlertTriangle size={16} aria-hidden="true" /> {authorHintCount(verdict)}{" "}
              {authorHintCount(verdict) === 1 ? "criterion relies" : "criteria rely"} on
              author-supplied test hints. Their link strength is capped; confirm the criteria in
              the intent panel to lift the cap.
            </p>
          ) : null}
          <CriteriaTable verdict={verdict} />
          <TamperSection verdict={verdict} />
          <ListSection
            title="Changed code with no stated criterion"
            items={verdict.unlinked_symbols}
            empty="Every behavioural change is covered by a criterion."
          />
          <NextActions verdict={verdict} />
          <PolicySection verdict={verdict} />
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
              {count} {stateLabel(verdict, state).toLowerCase()}
            </Chip>
          </li>
        ))}
      </ul>
      <div className="vv2-meters">
        <label className="vv2-meter">
          <span>
            Unsupported intent mass {formatScore(verdict.summary.uim)}
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
          supported. Legend: {legendText(verdict)}.
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
              label={stateLabel(verdict, criterion.state)}
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
  label,
  tau,
  expanded,
  onToggle,
}: {
  criterion: Criterion;
  label: string;
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
          <Chip tone={meta.tone} icon={meta.icon}>{label}</Chip>
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
      {criterion.mutation ? (
        <p className="vv2-small" data-testid="evidence-basis">{criterionBasisText(criterion)}</p>
      ) : null}
      <p className="vv2-small">
        Criterion source: {provenanceLabel(criterion.provenance)}
        {criterion.hints.length > 0
          ? `. Hints: ${criterion.hints
              .map((h) => `${h.kind} ${h.value} (${provenanceLabel(h.provenance)})`)
              .join("; ")}`
          : ""}
      </p>
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
      {mutationGaps(criterion).length > 0 ? (
        <div className="vv2-gaps">
          <p className="vv2-small">
            Gaps found by mutation: seeded faults that no linked test caught. This is a sample, and
            some may be harmless equivalents.
          </p>
          <ul className="vv2-reasons" aria-label="Gaps found by mutation">
            {mutationGaps(criterion).map((gap, index) => (
              <li key={`${gap}-${index}`}>
                <code className="vv2-mono">{gap}</code>
              </li>
            ))}
          </ul>
          {criterion.mutation?.survivorsTruncated ? (
            <p className="vv2-muted">Only the first gaps are shown.</p>
          ) : null}
        </div>
      ) : null}
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
              {finding.waived ? (
                <Chip tone="neutral" icon="minus">WAIVED</Chip>
              ) : null}
              <strong>{finding.rule_id}</strong>
              <code className="vv2-mono">{finding.path}</code>
            </p>
            <p>{finding.reason}</p>
            {finding.waived && finding.waiver ? (
              <p className="vv2-small">
                Waiver {finding.waiver.id || "(no id)"} by {finding.waiver.owner || "unknown owner"},
                expires {finding.waiver.expires || "unknown"}. Reason: {finding.waiver.reason}
              </p>
            ) : null}
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

function PolicySection({ verdict }: { verdict: VerdictV2 }) {
  if (!hasPolicySection(verdict)) return null;
  const { policy, waivers } = verdict;
  const waived = waivedFindings(verdict);
  return (
    <section aria-label="Policy and waivers" className="vv2-section vv2-policy">
      <h3>Policy and waivers</h3>
      <p className="vv2-muted">
        Read from the base branch of the pull request, never from the PR itself.
      </p>
      {policy ? (
        <details className="vv2-details" open>
          <summary>Policy (.radius/policy.yml)</summary>
          <p className="vv2-why">
            <Chip tone={policy.mode === "blocking" ? "warn" : "info"} icon="shield">
              {policy.mode ?? "no mode"}
            </Chip>{" "}
            {policyModeLabel(policy)}
          </p>
          <p className="vv2-small">
            Source: {policy.sourceRef ? `base ${policy.sourceRef.slice(0, 12)}` : "base branch"};
            head policy: {policy.headPolicy}.
          </p>
          <PolicyList title="Applied settings" items={policy.settings.map(settingLine)} />
          <PolicyList
            title="Ignored (head policy may only tighten)"
            items={policy.ignoredHead.map(settingLine)}
          />
          <PolicyList
            title="Unmet requirements"
            items={policy.unmet.map(
              (r) =>
                `${r.target || "changed code"}: ${r.state} (needs ${r.min_state}) under ${r.paths.join(", ") || "?"}` +
                (r.line !== null ? ` (policy line ${r.line})` : ""),
            )}
          />
          <PolicyList title="Excluded paths" items={policy.excludePaths} />
          <PolicyList title="Tamper severity changes recorded" items={policy.acknowledgements} />
          <PolicyList title="Tamper severity changes refused" items={policy.refused} />
          <PolicyList title="Policy errors" items={policy.errors} />
          <PolicyList title="Policy warnings" items={policy.warnings} />
        </details>
      ) : null}
      {waivers || waived.length > 0 ? (
        <details className="vv2-details" open>
          <summary>
            Waivers ({waived.length} finding{waived.length === 1 ? "" : "s"} waived
            {waivers ? `, ${waivers.ignored.length} ignored` : ""})
          </summary>
          {waived.length > 0 ? (
            <ul className="vv2-list" aria-label="Waived findings">
              {waived.map((f, index) => (
                <li key={`${f.finding_id}-${index}`}>
                  <Chip tone="neutral" icon="minus">WAIVED</Chip> {f.rule_id} on{" "}
                  <code className="vv2-mono">{f.path}</code>
                  {f.waiver
                    ? `: waiver ${f.waiver.id || "?"}, owner ${f.waiver.owner || "?"}, expires ${f.waiver.expires || "?"}. Reason: ${f.waiver.reason}`
                    : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {waivers ? (
            <>
              <PolicyList
                title="Applied waivers"
                items={waivers.applied.map(
                  (w) =>
                    `${w.id || "?"} (${w.kind || "?"} ${w.target}): owner ${w.owner || "?"}, expires ${w.expires || "?"}. Reason: ${w.reason}`,
                )}
              />
              <PolicyList
                title="Ignored waivers (never silently dropped)"
                items={waivers.ignored.map(
                  (w) =>
                    `${w.id || "(no id)"}: ${waiverCodeLabel(w.code)}${w.message ? ` - ${w.message}` : ""}${w.line !== null ? ` (line ${w.line})` : ""}`,
                )}
              />
              {waivers.status !== "ok" ? (
                <p className="vv2-small">Waivers file status: {waivers.status}.</p>
              ) : null}
              <p className="vv2-small">
                Evaluated on {waivers.evaluatedOn || "unknown date"}
                {waivers.auditDigest ? `, audit digest ${waivers.auditDigest}` : ""}.
              </p>
            </>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}

function PolicyList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <p className="vv2-small"><strong>{title}</strong></p>
      <ul className="vv2-list">
        {items.map((text, index) => (
          <li key={`${index}-${text.slice(0, 20)}`}>{text}</li>
        ))}
      </ul>
    </>
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
