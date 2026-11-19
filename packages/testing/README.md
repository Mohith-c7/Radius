# Radius Testing Package

Owns test discovery, test selection and run planning, test execution (`DisabledTestRunner` by default; the hardened container `sandbox_runner.py` when `WORKER_TEST_EXECUTION_MODE=sandbox`; `subprocess_runner.py` for local development only), CI result ingestion (JUnit XML / JSON parsing and matching to selected tests), test history and flakiness.

Sub-packages: `assertions/` (assertion extraction, EV-06 input), `linking/` (symbol-to-test linkers, LK-03, including coverage-context links; see its README) and `mutation/` (mutation evidence, DEC-035/036). Coverage report storage lives in `radius_confidence`.

AI-generated tests are intentionally out of scope for Phase 1.
