export type AnalysisStatus = "Verified" | "Needs attention" | "Running";

export const repositories: Array<{ id: string; name: string; language: string; branch: string; updated: string; confidence: number; status: "Healthy" | "Attention"; pullRequests: number }> = [
  { id: "radius-api", name: "radius/api", language: "Python", branch: "main", updated: "8 min ago", confidence: 94, status: "Healthy", pullRequests: 4 },
  { id: "radius-web", name: "radius/web", language: "TypeScript", branch: "main", updated: "42 min ago", confidence: 87, status: "Healthy", pullRequests: 2 },
  { id: "billing", name: "radius/billing", language: "TypeScript", branch: "main", updated: "2 hr ago", confidence: 72, status: "Attention", pullRequests: 3 }
];

export const analyses = [
  { id: "an-482", pullRequest: "#482 Add OAuth token rotation", repository: "radius/api", branch: "feat/token-rotation", status: "Verified" as AnalysisStatus, confidence: 94, files: 12, tests: "42 / 42", time: "8 min ago", duration: "2m 14s" },
  { id: "an-481", pullRequest: "#481 Refine dashboard filters", repository: "radius/web", branch: "feat/filter-controls", status: "Verified" as AnalysisStatus, confidence: 87, files: 8, tests: "28 / 28", time: "42 min ago", duration: "1m 07s" },
  { id: "an-480", pullRequest: "#480 Rework invoice calculation", repository: "radius/billing", branch: "fix/invoice-taxes", status: "Needs attention" as AnalysisStatus, confidence: 72, files: 18, tests: "38 / 41", time: "2 hr ago", duration: "3m 48s" },
  { id: "an-479", pullRequest: "#479 Improve audit events", repository: "radius/api", branch: "feat/audit-events", status: "Running" as AnalysisStatus, confidence: 0, files: 6, tests: "Running", time: "3 hr ago", duration: "—" }
];

export const confidenceEvidence = [
  { label: "Targeted test suite", detail: "42 relevant tests passed", score: "+38" },
  { label: "Dependency impact", detail: "12 affected files across 3 modules", score: "+24" },
  { label: "Change isolation", detail: "No public API contracts changed", score: "+18" },
  { label: "Coverage evidence", detail: "91% coverage on affected paths", score: "+14" }
];
