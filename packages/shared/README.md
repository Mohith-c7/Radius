# Radius Shared Package

Owns reusable configuration (`config.py`), logging, errors, redaction, the SQLAlchemy models and session (`database/`, including the API key tables), the response envelope DTOs, observability (metrics, tracing), the LLM input/output guard (`llm_guard/`) and the Verdict v2 flag, payload builder, repository and wording shared by the API and the worker. It has no event or auth-flow code (sign-in lives in `apps/api`).

Only truly reusable code belongs here.
