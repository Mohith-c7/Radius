# Phase 3: Detailed Execution Tasks

**Project:** Radius - AI-Native Software Verification Platform  
**Phase:** 3 - Predictive Test Selection, CI Ingestion & Rich PR Verification  

---

## Sprint 3.1: Precision Test Selection & Sliced Symbol Mapping
- [ ] **1.1 Symbol-to-Test Mapping Engine (`packages/testing`)**:
  - Implement `CpgTestMapper` in `packages/testing/src/radius_testing/infrastructure/`:
    - Given affected symbols/files from CPG slicing, discover all candidate test files.
    - Match using convention heuristics (`api.py` -> `tests/test_api.py`, `service.ts` -> `service.test.ts`, `tests/unit/test_*.py`).
    - Parse test file imports to detect direct testing of affected modules.
- [ ] **1.2 Test Optimization Metrics Calculation**:
  - Compute `total_tests_discovered`, `selected_tests_count`, `skipped_tests_count`, and `time_saved_percent` (e.g. `(skipped / total) * 100`).
- [ ] **1.3 Test Selection API Endpoint (`apps/api`)**:
  - Update `apps/api/src/radius_api/routes/tests.py`:
    - Return `selected_tests`, `skipped_tests`, and formatted CLI strings (e.g. `"tests/test_api.py tests/test_db.py"`).
- [ ] **1.4 Unit & Integration Tests**:
  - Add tests in `packages/testing/tests/test_cpg_test_mapper.py` and `apps/api/tests/test_test_selection.py`.

---

## Sprint 3.2: CI Test Results Ingestion & Dynamic Confidence Engine
- [ ] **2.1 JUnit XML & JSON Test Result Parser (`packages/testing`)**:
  - Implement `JUnitReportParser` in `packages/testing/src/radius_testing/infrastructure/`:
    - Parses standard `<testsuite>` and `<testcase>` XML elements (from pytest `--junitxml`, Jest, Vitest).
    - Extracts `passed`, `failed`, `skipped`, `errors`, and execution `duration_seconds`.
- [ ] **2.2 Results Ingestion API Endpoint (`apps/api`)**:
  - Add `POST /api/v1/analyses/{analysis_id}/tests/results`:
    - Accepts XML payload (`application/xml` or `text/xml`) and JSON payload (`application/json`).
    - Validates organization permission.
    - Stores `TestRunResult` in database.
- [ ] **2.3 Dynamic Confidence Aggregation (`packages/confidence`)**:
  - Update `ConfidenceApplicationService` to re-score when test results are ingested:
    - 100% pass: score boosted to 90–100% (LOW risk).
    - Any failure: score dropped to < 40% (HIGH/CRITICAL risk) with failure summary in recommendations.
- [ ] **2.4 Unit & Integration Tests**:
  - Add tests in `packages/testing/tests/test_junit_parser.py` and `apps/api/tests/test_test_results_ingestion.py`.

---

## Sprint 3.3: Rich GitHub PR Comment Bot & Check Runs
- [ ] **3.1 Visual PR Markdown Template (`packages/github`)**:
  - Update `_markdown_report` in `packages/github/src/radius_github/publisher.py`:
    - **Confidence Score Badge:** Visual status with risk level (e.g. `🟢 94/100 (LOW RISK)` or `🔴 35/100 (CRITICAL RISK)`).
    - **CI Savings Summary:** Selected vs skipped test count and time savings (e.g. `⚡ 82% Tests Skipped: 4 run, 18 skipped`).
    - **Blast Radius Details:** Collapsible markdown table of changed files and impacted symbols.
    - **AI Pruning Explanations:** Clean display of Gemini's rationale for pruned benign changes.
    - **Deep Link:** Direct link to Radius Dashboard.
- [ ] **3.2 Check Run Lifecycle Management (`packages/github`)**:
  - Update `GitHubAnalysisPublisher` to support creating initial `in_progress` Check Run on webhook receipt, and updating to `success` / `failure` / `neutral` on analysis completion.
- [ ] **3.3 End-to-End Verification**:
  - Add comprehensive unit tests in `packages/github/tests/test_rich_publisher.py`.
  - Execute full monorepo test suite across all 11 packages and apps.
