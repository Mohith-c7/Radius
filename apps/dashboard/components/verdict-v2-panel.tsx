"use client";

// Verdict v2 panel mount point (VS-00 skeleton; VS-10 owns the implementation).
//
// Renders nothing until VS-10: the API route answers 404 `disabled` while
// RADIUS_FEATURE_VERDICT_V2 is off, and a 404 must hide the panel.
//
// SECURITY (applies to VS-10): criterion text, test ids and snippets are
// untrusted. Render them ONLY as React text nodes (no dangerouslySetInnerHTML,
// no markdown), as in components/intent-panel.tsx.

export function VerdictV2Panel(props: { analysisId: string }) {
  void props.analysisId;
  return null;
}
