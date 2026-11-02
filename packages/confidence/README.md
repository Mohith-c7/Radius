# Radius Confidence Package

Owns evidence aggregation, deterministic confidence scoring, risk classification, recommendations, and confidence report generation.

Every confidence output must be explainable and evidence-backed.

The 0-100 `confidence_score` is an uncalibrated heuristic built from fixed penalties, not a probability. Reports carry `score_kind` (`ScoreKind`, currently `heuristic_uncalibrated`); `CURRENT_SCORE_KIND` in `radius_confidence.domain.enums` is the single place to change once calibration (CA-*) ships behind the VD-07 flag.
