# Radius Evidence Package

Typed contracts and (later) pure functions that turn validated outcomes into per-criterion support for the **Verdict v2 alpha**. Design: [`docs/research/design/VERDICT_V2_SLICE.md`](../../docs/research/design/VERDICT_V2_SLICE.md); decisions: DEC-027.

Status: VS-00 contracts plus the first feature wave (EV-01, EV-06, EV-07, EV-03-lite). `q(e)` (EV-08), the IEG, `S(c)` and states are owned by other tasks (design section 2.3).

## Layout

| Path | Owner | Content |
| --- | --- | --- |
| `domain/enums.py`, `domain/model.py`, `domain/config.py`, `domain/inputs.py`, `domain/versions.py`, `domain/serialization.py` | VS-00 (contract) | Frozen after VS-00; changing a field name or default needs a contract-change PR approved by the architect. |
| `domain/ieg.py` | LK-05 | IEG node / edge / graph types (builder and queries to come). |
| `domain/quality.py` | EV-08 | `EvidenceQuality` (alias `QualityBreakdown`), `ChainRef`. |
| `domain/support.py` | VD-01 | `SupportResult`. |
| `domain/states.py` | VD-02 | `CriterionStateResult`, `UimResult`. |
| `domain/strength.py` | EV-06 | `a_static` and `explain_a_static` (reason codes). |
| `domain/freshness.py` | EV-07 | Head-SHA binding, blob-level staleness, optional decay hook (off). |
| `domain/independence.py` | EV-03-lite | Independence factor and agent-trailer detector. |
| `domain/factories.py`, `domain/assertion_records.py`, `application/normalize.py` | EV-01 | Evidence item factories, test-id joiner, LK-04 dict conversion, batch normalizer. |
| `application/` | LK-05, VS-03 | `ieg_builder`, pure Stage B `pipeline`. |
| `infrastructure/` | Beta | SQL projection repositories. |

## Rules

- `domain` and `application` import only the standard library and this package. No `radius_shared`, no SQLAlchemy, no producer package. Enforced by `.importlinter` (run `lint-imports --config packages/evidence/.importlinter`) and `tests/test_architecture.py`.
- `__init__.py` files are docstring-only; import by full module path (`radius_evidence.domain.model`).
- Every dataclass is `frozen=True, slots=True` and extends `Serializable`: `to_dict` / `from_dict` / `to_json` / `from_json`, sorted keys, floats rounded to 6 decimals, tuples as lists, unknown keys ignored on read. No clocks inside the domain.
- `EvidenceItem` rejects a `head_sha` that is not 40 lowercase hex characters (SHA-binding guarantee).
- The configuration is one object, `VerdictV2Config`, with the `alpha-static` defaults (`cap_static` 0.6, `tau_support` 0.5, ...). `digest()` is a SHA-256 of its canonical JSON. The defaults are hypotheses, not results.

## Features (EV-01, EV-03-lite, EV-06, EV-07)

Pure functions over the frozen contracts. Details and weights: [`docs/evidence/assertion-strength.md`](../../docs/evidence/assertion-strength.md).

- **`a_static`** (`domain/strength.py`): `max` over assertion facts of the kind table in `QualityConfig.assertion_scores` (value equality 1.0 ... tautology 0). `explain_a_static` returns reason codes per fact. `cap_static` is applied by EV-08, not here.
- **Freshness** (`domain/freshness.py`): `f = 1` at the current head SHA, else `0` (`stale_sha`; `unbound` for a missing or malformed SHA). Optional decay hook, default off: `unchanged_factor ** commits_behind` when no covered file blob changed, else 0. `partition_by_freshness` keeps ignored items for audit.
- **Independence** (`domain/independence.py`): pre-existing unchanged test 1.0; changed in the PR: human 1.0, agent trailer 0.6, unknown 0.8. `detect_agent_trailers` matches the configured patterns case-insensitively.
- **Normalizers**: `domain/factories.py` (`from_case`, `from_test`, `from_aggregate`, `from_finding`, `case_to_test_id`, `make_evidence_id`), `domain/assertion_records.py` (LK-04 `AssertionSet.to_dict()` to `AssertionFeatures`, no import of `radius_testing`), `application/normalize.py` (`normalize_evidence(StageBInput, collected_at=...)`). Malformed items are rejected and reported, never partially accepted; ids are `ev_` + sha256 prefix and stable.

## Tests

`python -m pytest packages/evidence/tests`. They validate the example payload against `docs/research/design/verdict_v2.schema.json` with a small stdlib validator (no new dependency) and check the fixture expectations against the 8 F-14 fixtures.
