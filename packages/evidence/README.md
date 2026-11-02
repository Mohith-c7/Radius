# Radius Evidence Package

Typed contracts and (later) pure functions that turn validated outcomes into per-criterion support for the **Verdict v2 alpha**. Design: [`docs/research/design/VERDICT_V2_SLICE.md`](../../docs/research/design/VERDICT_V2_SLICE.md); decisions: DEC-027.

Status: **VS-00 contract scaffold**. This package currently holds only dataclasses, enums, configuration defaults and serialization. The algorithms are owned by later tasks (see the ownership map in design section 2.3).

## Layout

| Path | Owner | Content |
| --- | --- | --- |
| `domain/enums.py`, `domain/model.py`, `domain/config.py`, `domain/inputs.py`, `domain/versions.py`, `domain/serialization.py` | VS-00 (contract) | Frozen after VS-00; changing a field name or default needs a contract-change PR approved by the architect. |
| `domain/ieg.py` | LK-05 | IEG node / edge / graph types (builder and queries to come). |
| `domain/quality.py` | EV-08 | `EvidenceQuality` (alias `QualityBreakdown`), `ChainRef`. |
| `domain/support.py` | VD-01 | `SupportResult`. |
| `domain/states.py` | VD-02 | `CriterionStateResult`, `UimResult`. |
| `domain/strength.py`, `freshness.py`, `independence.py` | EV-06, EV-07, EV-03 | Not created yet. |
| `application/` | LK-05, VS-03 | `ieg_builder`, pure Stage B `pipeline`. |
| `infrastructure/` | Beta | SQL projection repositories. |

## Rules

- `domain` and `application` import only the standard library and this package. No `radius_shared`, no SQLAlchemy, no producer package. Enforced by `.importlinter` (run `lint-imports --config packages/evidence/.importlinter`) and `tests/test_architecture.py`.
- `__init__.py` files are docstring-only; import by full module path (`radius_evidence.domain.model`).
- Every dataclass is `frozen=True, slots=True` and extends `Serializable`: `to_dict` / `from_dict` / `to_json` / `from_json`, sorted keys, floats rounded to 6 decimals, tuples as lists, unknown keys ignored on read. No clocks inside the domain.
- `EvidenceItem` rejects a `head_sha` that is not 40 lowercase hex characters (SHA-binding guarantee).
- The configuration is one object, `VerdictV2Config`, with the `alpha-static` defaults (`cap_static` 0.6, `tau_support` 0.5, ...). `digest()` is a SHA-256 of its canonical JSON. The defaults are hypotheses, not results.

## Tests

`python -m pytest packages/evidence/tests`. They validate the example payload against `docs/research/design/verdict_v2.schema.json` with a small stdlib validator (no new dependency) and check the fixture expectations against the 8 F-14 fixtures.
