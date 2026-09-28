# Phase 3: Detailed Execution Tasks

**Project:** Radius - AI-Native Software Verification Platform  
**Phase:** 3 - Dynamic Test Intelligence, CI Optimization & Rich PR Verification  

---

## Sprint 3.1: Dynamic Test Mapping & Targeted Runner Harness
- [ ] **1.1 Symbol-to-Test Mapper (`packages/testing`)**:
  - Implement heuristic and convention-based test mapping (`api.py` -> `test_api.py`, `service.ts` -> `service.test.ts`).
  - Implement AST-based test mapping: discover test functions in test files that call or import modified symbols.
- [ ] **1.2 Dynamic Test Command Planner (`packages/testing`)**:
  - Generate targeted runner commands for Python (`pytest -q <file1> <file2>`) and TypeScript (`pnpm vitest run <file1> <file2>`).
  - Enforce timeouts and non-zero exit code error handling.
- [ ] **1.3 Test Output Parser (`packages/testing`)**:
  - Parse runner output to extract passed, failed, skipped, and execution duration into `TestExecutionSummary`.
- [ ] **1.4 Worker Pipeline Integration (`apps/worker`)**:
  - Wire targeted runner into `Phase1AnalysisOrchestrator`: run only the mapped tests within the cloned repo sandbox.
  - Pass live `TestEvidence` to `ConfidenceApplicationService`.
- [ ] **1.5 Unit & Integration Testing**:
  - Add tests in `packages/testing/tests/` and `apps/worker/tests/` verifying targeted execution and output parsing.

---

## Sprint 3.2: Rich GitHub Check Run & PR Comment Bot
- [ ] **2.1 Visual PR Markdown Template (`packages/github`)**:
  - Format rich PR comment featuring:
    - **Confidence Score Badge:** Visual indicator with risk level (e.g. `🟢 92/100 (LOW RISK)`).
    - **CI Savings Summary:** Selected tests vs skipped tests (e.g. `⚡ 78% CI Time Saved: 3 tests run, 14 skipped`).
    - **Blast Radius Collapsible Table:** Impacted files, changed symbols, and dependency depth.
    - **AI Semantic Pruning Details:** Explainable reasons why benign changes were safely excluded.
    - **Direct Dashboard Link:** Clickable deep-link to the Radius analysis view.
- [ ] **2.2 Check Run Lifecycle Management (`packages/github`)**:
  - Publish `queued` / `in_progress` Check Run as soon as analysis job starts.
  - Update Check Run to `success`, `neutral`, or `failure` upon completion.
- [ ] **2.3 Unit & Publisher Verification**:
  - Add unit tests in `packages/github/tests/` verifying Markdown formatting and Check Run payload generation.

---

## Sprint 3.3: Incremental CPG Persistence & Performance
- [ ] **3.1 Database Schema for CPG (`packages/shared`)**:
  - Add SQLAlchemy models for `CPGNode` and `CPGEdge` linked to `Repository` and `Analysis`.
- [ ] **3.2 Incremental Graph Update Routine (`packages/graph`)**:
  - Build incremental parser service: given changed files, remove stale nodes/edges for those files and re-index only the modified files.
- [ ] **3.3 End-to-End Monorepo Validation**:
  - Run full test suite across all 11 packages and apps.
  - Verify performance metrics and zero regressions.
