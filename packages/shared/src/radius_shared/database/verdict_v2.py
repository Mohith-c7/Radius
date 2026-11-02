"""Verdict v2 persistence models (VS-00 registration stub).

Intentionally defines no table yet. VD-03 adds ``VerdictV2Row`` (table
``verdict_v2``, migration 20261102_0013) and VS-07 adds ``VerdictV2RequestRow``
(table ``verdict_v2_requests``, migration 20261102_0014) in this module. The
module is already imported by ``radius_shared.database`` and by Alembic's
``env.py``, so those tasks never edit either file. See VERDICT_V2_SLICE.md 4.2.
"""
