# Product Requirements Document (PRD)
**Project:** Radius - AI-Native Software Verification Platform  
**Phase:** 3 - Dynamic Test Intelligence, CI Optimization & Rich PR Verification  
**Status:** PROPOSED  
**Date:** September 2026  

---

## 1. Executive Summary
Phase 1 established the foundation (infrastructure, database, GitHub webhooks, API, worker, and dashboard). Phase 2 pioneered the **Semantic Code Property Graph (CPG) & AI Pruning Engine**, enabling Radius to deterministically trace symbol-level reverse call graphs across Python and TypeScript and prune false-positive blast radiuses with Gemini.

**Phase 3 connects the intelligence engine to actual execution and developer workflows:**
Instead of developers guessing which tests to run or waiting 45 minutes for full CI suites, Radius will **dynamically discover, map, and execute only the tests within the sliced blast radius**, aggregate real execution evidence into explainable confidence scores, and **publish actionable, interactive reports directly into GitHub Pull Requests (Check Runs + PR Comments)**.

---

## 2. Objectives & Key Results (OKRs)

* **Objective 1 (Targeted Test Execution):** Automatically map sliced CPG symbols to test suites and run only the relevant tests via native test runners (`pytest` for Python, `vitest`/`jest` for TypeScript).
* **Objective 2 (CI Acceleration):** Demonstrate > 60% reduction in test execution time on benchmark repositories by skipping unaffected test suites safely.
* **Objective 3 (Actionable GitHub Bot):** Publish high-visibility GitHub Check Runs and rich Markdown PR summary comments detailing confidence score, blast radius tables, skipped tests, and AI explanations.
* **Objective 4 (Persistent Graph Cache):** Persist CPG nodes and edges into PostgreSQL for incremental repository updates without reparsing the full codebase on every push.

---

## 3. Scope & Deliverables

### In Scope for Phase 3:
1. **Symbol-to-Test Mapping Engine (`packages/testing`)**:
   - Heuristic & structural mapper connecting source symbols to test files (e.g. `api.py:get_user` -> `tests/test_api.py::test_get_user`).
   - Dynamic runner integration: executes targeted test commands (`pytest tests/test_api.py` or `pnpm test tests/handler.test.ts`).
   - Parsing test runner JSON / JUnit XML output into discrete `TestResult` records (passed, failed, skipped, duration).
2. **Enhanced Evidence & Confidence Aggregator (`packages/confidence`)**:
   - Synthesizes Impact Evidence (blast radius depth, pruned symbols) with real Test Evidence (test pass rate, execution duration).
   - Dynamic Risk Classification:
     - `LOW` (Score >= 80): All sliced tests passed, blast radius contained.
     - `MEDIUM` (Score 60-79): Sliced tests passed, but high dependency depth or unverified callers.
     - `HIGH` / `CRITICAL` (Score < 60): One or more sliced tests failed or unhandled breaking changes detected.
3. **Rich GitHub PR Reporter (`packages/github`)**:
   - Visual PR Comment formatting with collapsible blast radius details, test savings metrics, and AI pruning explanations.
   - GitHub Check Run integration with deep link back to Radius dashboard (`/analyses/[id]/blast-radius`).
4. **Persistent CPG Graph Store (`packages/graph` & `packages/shared`)**:
   - PostgreSQL schema for `cpg_nodes` and `cpg_edges`.
   - Incremental graph update service: re-parse only changed files and update affected graph edges.

### Out of Scope (Deferred to Phase 4 & 5):
- Ephemeral microVM sandboxes (e.g. AWS Firecracker).
- Autonomous AI-generated test synthesis.
- Multi-organization enterprise billing (Stripe).

---

## 4. Technical Architecture & Data Flow

```
[ GitHub PR Webhook ]
        │
        ▼
[ Worker: Git Clone & Checkout ]
        │
        ▼
[ Phase 2: CPG Slicing & AI Pruner ] ──► Extracts Affected Symbols & Files
        │
        ▼
[ Phase 3: Test Mapping Engine ] ─────► Maps Sliced Symbols to Relevant Tests
        │
        ▼
[ Dynamic Test Runner ] ──────────────► Executes ONLY Selected Tests (pytest/vitest)
        │
        ▼
[ Confidence Aggregator ] ────────────► Combines Impact + Test Evidence into Score
        │
        ▼
[ GitHub PR Publisher ] ──────────────► Updates Check Run & Posts Rich PR Comment
```

---

## 5. Success Metrics
* **Precision:** 0 false-negative skips (no breaking change goes unverified).
* **Speed:** Test selection and execution overhead < 5 seconds + test runtime.
* **Developer Feedback:** Clear, explainable PR comment providing immediate merge confidence.
