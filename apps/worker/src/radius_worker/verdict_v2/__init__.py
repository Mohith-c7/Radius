"""Verdict v2 worker adapters (composition root; flag RADIUS_FEATURE_VERDICT_V2).

Docstring only (no barrel imports). The worker is the only place that may import
every producer domain and adapt it to the plain DTOs of
``radius_evidence.domain.inputs``. v1 modules (``orchestrator``) are not edited.
See VERDICT_V2_SLICE.md 5."""
