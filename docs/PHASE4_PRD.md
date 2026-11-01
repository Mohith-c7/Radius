# Phase 4 Product Requirements Document (PRD)

**Project:** Radius - AI-Native Software Verification Platform  
**Phase:** 4 - Frontend Dashboard Intelligence & Visual Verification  
**Author:** Mohith-c7 / Team  
**Status:** Approved for Execution  
**Target Completion:** Sprints 4.1 – 4.4  

---

## 1. Executive Summary
With the backend verification engine (Phase 1), Semantic CPG + Gemini AI pruner (Phase 2), and Predictive Test Selection + CI Ingestion pipeline (Phase 3) fully operational, Phase 4 elevates the **Next.js Dashboard (`apps/dashboard`)** into an intelligent, visually stunning command center for engineers.

Developers will be able to:
1. **Visualize Predictive Test Savings:** View CI time savings gauges (`⚡ 80% Time Saved`), explore selected vs skipped tests, and copy CLI execution snippets (`pytest $(curl ...)`).
2. **Inspect CI Test Run Evidence:** Ingest and view parsed JUnit XML test reports, inspect failing assertions/stack traces, and observe dynamic confidence score adjustments in real-time.
3. **Explore Interactive Blast Radius & CPG Slices:** Graphically navigate changed files, impacted callers, pruned benign nodes, and targeted test suites.
4. **Understand AI Impact Decisions:** Read Gemini 2.0 Flash reasoning cards explaining why benign callers were safely excluded from breaking changes.

---

## 2. User Personas & Core Workflows

### Persona 1: Feature Developer
- Opens the Pull Request analysis page.
- Immediately sees the **Confidence Score** and **CI Time Saved**.
- Copies the one-click CLI command to run only the impacted tests locally before pushing (`pytest $(curl -s "http://localhost:8000/api/v1/analyses/{id}/tests?format=cli")`).

### Persona 2: Tech Lead / Reviewer
- Inspects the **Blast Radius Graph** to see all transitively impacted symbols across modules.
- Reviews **AI Pruning Insights** to verify why certain callers were classified as benign.
- Inspects any failed CI tests directly within the dashboard with formatted tracebacks.

---

## 3. Detailed Feature Requirements

### 3.1 Predictive Test Selection & CLI Hub
- **Time Saved Gauge & Metrics:** Show `selected_count`, `skipped_count`, `total_count`, and `time_saved_percent` with visual progress indicators.
- **Copyable CLI Commands:** One-click copy tabs for:
  - **Pytest:** `pytest $(curl -s "{api}/analyses/{id}/tests?format=cli")`
  - **Vitest:** `vitest run $(curl -s "{api}/analyses/{id}/tests?format=cli")`
  - **Jest:** `jest $(curl -s "{api}/analyses/{id}/tests?format=cli")`
- **Selected vs Skipped Tables:** Filterable lists displaying test file paths, frameworks, and selection rationale (`AFFECTED_FILE`, `IMPORT_DEPENDENCY`, etc.).

### 3.2 CI Test Results Ingestion & Failure Trace Viewer
- **CI Test Summary Card:** Displays total, passed, failed, skipped, duration (ms/sec), and status badge (`PASSED` / `FAILED`).
- **Interactive Report Ingestion:** A UI upload button/dropzone allowing developers to upload a `junit.xml` or JSON report directly from the dashboard, triggering immediate confidence recalculation.
- **Failure Stack Trace Accordion:** Formatted, syntax-highlighted failure output for failing tests.

### 3.3 Interactive Sliced CPG Graph Visualizer
- **Interactive Visual Graph:** Render nodes (Files, Functions/Methods, Tests) and directed edges (`CALLS`, `DEPENDS_ON`, `TESTS`).
- **Color Coding & Status:**
  - 🟠 **Directly Modified:** Files and symbols altered in git diff hunks.
  - 🔵 **Caller Slice:** Sliced callers reachable from changed symbols.
  - 🟢 **AI Pruned:** Benign callers pruned from test matrix.
  - 🟣 **Targeted Tests:** Tests mapped to affected symbols.
- **Node Detail Drawer / Tooltip:** Hover or click on a node to view its file path, line numbers, and symbol identifier.

### 3.4 AI Impact Pruning Insights
- **Gemini Reasoning Cards:** Display impact evaluation rationale for analyzed caller-callee pairs.
- Explains why a caller was determined benign (e.g. untouched parameters, internal documentation change) or breaking.

---

## 4. Technical Architecture
- **Framework:** Next.js 14+ (App Router), React 18+, TypeScript.
- **Styling:** CSS Modules / CSS Variables with dark modern theme.
- **State & Data Fetching:** `radiusFetch` client with typed envelopes and automatic error boundaries.
- **Graph Visualization:** Clean, dependency-light SVG / Canvas interactive rendering (or Lightweight Canvas / SVG layout) avoiding heavy unmaintained NPM packages.

---

## 5. Success Metrics
- 100% TypeScript type-safety across all dashboard components (`npm run typecheck`).
- 0 ESLint errors across the dashboard (`pnpm run lint`).
- Flawless API communication with all Phase 1–3 endpoints.
