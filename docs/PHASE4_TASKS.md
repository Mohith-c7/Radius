# Phase 4: Detailed Execution Tasks

**Project:** Radius - AI-Native Software Verification Platform  
**Phase:** 4 - Frontend Dashboard Intelligence & Visual Verification  

---

## Sprint 4.1: Predictive Test Selection & CLI Hub UI
- [ ] **1.1 Enriched TypeScript Models (`apps/dashboard/lib/api.ts`)**:
  - Update `TestSelection` type with `skipped_count`, `total_count`, `time_saved_percent`, `cli_args`, and `skipped_tests`.
  - Add API function `getTestSelection(analysisId: UUID)`.
- [ ] **1.2 Test Selection Hub Component (`apps/dashboard/components/`)**:
  - Implement `TestSelectionHub`:
    - Visual savings gauge: `⚡ {time_saved_percent}% Time Saved`.
    - Selected tests table with reason tags (`AFFECTED_FILE`, etc.).
    - Collapsible skipped tests drawer showing bypassed test cases.
    - One-click copy tabs for `pytest`, `vitest`, and `jest` CLI commands.
- [ ] **1.3 Integrate into Analysis Details View**:
  - Mount `TestSelectionHub` under the `#tests` tab in `AnalysisDetailData`.

---

## Sprint 4.2: CI Test Results Ingestion & Failure Trace Explorer
- [ ] **2.1 CI Ingestion Client Methods (`apps/dashboard/lib/api.ts`)**:
  - Add `TestRunResult` type: `id`, `analysis_id`, `status`, `total_tests`, `passed`, `failed`, `skipped`, `duration_ms`, `coverage_percent`, `output`.
  - Add `getTestRunResult(analysisId: UUID): Promise<TestRunResult | null>`.
  - Add `uploadTestResults(analysisId: UUID, fileContent: string, isXml: boolean): Promise<TestRunResult>`.
- [ ] **2.2 CI Ingestion & Failure Trace Component**:
  - Implement `CiResultsCard`:
    - Displays test run status badge (`PASSED` / `FAILED`), counts, and execution duration.
    - Upload / paste modal for JUnit XML or JSON test reports.
    - Stack trace viewer with formatted error blocks for failed tests.
- [ ] **2.3 Integrate into Analysis Details View**:
  - Mount `CiResultsCard` in `AnalysisDetailData` and auto-refresh confidence scores upon upload.

---

## Sprint 4.3: Interactive Blast Radius & CPG Slicer Visualizer
- [ ] **3.1 Graph Data Transformation (`apps/dashboard/lib/graph-layout.ts`)**:
  - Transform `GraphSnapshot` nodes and edges into a layered DAG layout (Files ➔ Functions ➔ Callers ➔ Tests).
  - Assign status styles: Modified (Amber), Impacted Callers (Cyan), Benign Pruned (Emerald/Muted), Tests (Violet).
- [ ] **3.2 Interactive Sliced Graph Visualizer Component**:
  - Build `InteractiveGraphViewer` (SVG-based):
    - Pan, zoom, and fit-to-view controls.
    - Node click / hover inspector showing symbol name, file path, line range, and status.
    - Edge labels for `CALLS`, `DEPENDS_ON`, `TESTS`.
- [ ] **3.3 Mount in Analysis Views**:
  - Update `apps/dashboard/app/analyses/[analysisId]/blast-radius/page.tsx` and `app/graph/page.tsx`.

---

## Sprint 4.4: AI Pruning Insights & Quality Verification
- [ ] **4.1 AI Pruning Explanations Component**:
  - Implement `AiPruningInsightsCard` displaying Gemini 2.0 Flash evaluation rationale.
  - Explain why callers were pruned (benign AST changes) vs kept (breaking contract).
- [ ] **4.2 Monorepo Build & Lint Verification**:
  - Run `pnpm run lint` across `apps/dashboard`.
  - Run `turbo run build` to verify Next.js production build passes with 0 type errors.
  - Verify all 215 backend tests continue to pass 100% green.
