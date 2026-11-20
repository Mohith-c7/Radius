"use client";

// Advisory AI review panel (DEC-042). Shows the AI merge-readiness review stored for an
// analysis: what changes, main risks, tests that matter, missing evidence, next steps.
// It is clearly labelled AI-generated and advisory and never shows or changes a verdict.
// Renders nothing when no review exists (feature off, no provider, not generated).
//
// SECURITY: all review text is LLM output derived from untrusted PR content. It is
// rendered ONLY as React text nodes: no dangerouslySetInnerHTML, no markdown, no links.

import { AlertTriangle, Bot, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { getAiReview } from "../lib/ai-review";
import {
  AI_SECTIONS,
  classifyAiReviewError,
  unavailableText,
  type AiReview,
} from "../lib/ai-review-model";
import "./ai-review-panel.css";

type Load =
  | { status: "loading" }
  | { status: "absent" }
  | { status: "error"; message: string }
  | { status: "ready"; review: AiReview };

export function AiReviewPanel({ analysisId }: { analysisId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [reloading, setReloading] = useState(false);
  const latest = useRef(0);
  const headingId = useId();

  const refresh = useCallback(async () => {
    const ticket = ++latest.current;
    setReloading(true);
    try {
      const review = await getAiReview(analysisId);
      if (ticket === latest.current) setLoad({ status: "ready", review });
    } catch (error) {
      if (ticket !== latest.current) return;
      const info = classifyAiReviewError(error);
      setLoad(info.kind === "absent" ? { status: "absent" } : { status: "error", message: info.message });
    } finally {
      if (ticket === latest.current) setReloading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    setLoad({ status: "loading" });
    void refresh();
    return () => {
      latest.current += 1;
    };
  }, [refresh]);

  if (load.status === "absent" || load.status === "loading") return null;

  return (
    <section id="ai-review" className="card air-panel" aria-labelledby={headingId}>
      <div className="card-heading">
        <div>
          <h2 id={headingId}>
            <Bot size={18} aria-hidden="true" /> AI review <span className="air-badge">advisory</span>
          </h2>
          <p>AI-generated explanation of this pull request. It is not the Radius verdict.</p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => void refresh()}
          disabled={reloading}
          aria-label="Reload AI review"
        >
          {reloading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
          Reload
        </button>
      </div>
      <div className="air-body">
        {load.status === "error" ? (
          <p className="air-state error" role="alert">
            <AlertTriangle size={14} aria-hidden="true" /> {load.message}
          </p>
        ) : (
          <ReviewBody review={load.review} />
        )}
      </div>
    </section>
  );
}

function ReviewBody({ review }: { review: AiReview }) {
  return (
    <>
      <p className="air-label">{review.label}</p>
      {review.status === "unavailable" ? (
        <p className="air-state">{unavailableText(review.reasonCode)}</p>
      ) : (
        <>
          <p className="air-summary">{review.summary}</p>
          {AI_SECTIONS.map(({ key, title }) =>
            review.sections[key].length ? (
              <div key={key} className="air-section">
                <h3>{title}</h3>
                <ul>
                  {review.sections[key].map((item, index) => (
                    <li key={index}>
                      <span>{item.text}</span>
                      {item.files.length ? (
                        <span className="air-files">
                          {item.files.map((file) => (
                            <code key={file}>{file}</code>
                          ))}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
          {review.injectionFlagged ? (
            <p className="air-state warn">
              <AlertTriangle size={14} aria-hidden="true" /> Radius flagged text in this pull request that looks like
              instructions to an AI; it was treated as data.
            </p>
          ) : null}
        </>
      )}
      <p className="air-meta">
        {review.model ? `Model ${review.model}` : "Model unknown"}
        {review.generatedAt ? ` · ${review.generatedAt}` : ""}
        {review.diffTruncated ? " · diff excerpts were truncated" : ""}
      </p>
    </>
  );
}
