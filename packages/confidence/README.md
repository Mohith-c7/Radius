# Radius Confidence Package

Owns evidence aggregation, deterministic confidence scoring, risk classification, recommendations, and confidence report generation.

Every confidence output must be explainable and evidence-backed.

The 0-100 `confidence_score` is an uncalibrated heuristic built from fixed penalties, not a probability. Reports carry `score_kind` (`ScoreKind`, currently `heuristic_uncalibrated`); `CURRENT_SCORE_KIND` in `radius_confidence.domain.enums` is the single place to change once calibration (CA-*) ships behind the VD-07 flag.

## Calibration toolkit (groundwork, not wired)

`radius_confidence.calibration` is a stdlib-only library of calibration metrics, isotonic and Platt fitting, intervals, abstention thresholds and minimum-N guards, plus the `Calibrator` hook interface. Nothing in the verdict imports it (import-linter contract in `.importlinter`); the score stays uncalibrated. See [`docs/research/evaluation/CALIBRATION_TOOLKIT.md`](../../docs/research/evaluation/CALIBRATION_TOOLKIT.md).

## Verdict v2 rules (VD-03)

`radius_confidence.verdict_v2` turns per-criterion results and analysis facts into the PR-level verdict of the Verdict v2 alpha. It is pure and deterministic (no clock, no I/O) and imports only the standard library and `radius_evidence.domain`; v1 modules never import it.

- `domain/rules.py`: `AnalysisFacts` (CI state, tamper findings, degraded flags, behavioral symbol count, flaky ids) and `evaluate_rules(criteria, uim, facts, config)`, which evaluates all 12 rules R1a to R4 in order and records each with its inputs. The first rule that fires decides. Every threshold comes from `VerdictV2Config.rules` / `.support`; no rule id or severity is hard-coded for tamper (R1c and R3a read severity labels from the findings).
- `domain/tree.py`: `build_justification` (schema `verdict-v2-justification-1`) and `check_justification`, which verifies that all rules appear once in order, `decided_by` is the first fired rule, and every `refs` id exists in the bundle.
- `application/service.py`: `compute_verdict_v2(...)` returns a `VerdictV2`; `build_criterion_verdict(criterion, support, state)` joins VD-01/VD-02 outputs. `pending` is true only when R2p decides (no CI result yet).
- Reasons: one `Reason` per fired rule, deciding rule first; `Reason.ref` carries the rule id (the serving layer maps it to `rule_id`).

Rule table, comment format and limits for users: [`docs/verdict-v2.md`](../../docs/verdict-v2.md). Design: `docs/research/design/VERDICT_V2_SLICE.md` section 3.9. Tests: `tests/test_verdict_v2_rules.py` (each rule alone, priority, boundaries, tree invariants) and `tests/test_verdict_v2_fixtures.py` (the 8 F-14 fixtures from `verdict_v2.fixture_expectations.json`, gold and auto numbers).
