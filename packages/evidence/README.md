# Radius Evidence Package

Typed contracts and (later) pure functions that turn validated outcomes into per-criterion support for the **Verdict v2 alpha**. Design: [`docs/research/design/VERDICT_V2_SLICE.md`](../../docs/research/design/VERDICT_V2_SLICE.md); decisions: DEC-027.

Status: **VS-00 contract scaffold**. This package currently holds only dataclasses, enums, configuration defaults and serialization. The algorithms are owned by later tasks (see the ownership map in design section 2.3).

## Layout

| Path | Owner | Content |
| --- | --- | --- |
| `domain/enums.py`, `domain/model.py`, `domain/config.py`, `domain/inputs.py`, `domain/versions.py`, `domain/serialization.py` | VS-00 (contract) | Frozen after VS-00; changing a field name or default needs a contract-change PR approved by the architect. |
| `domain/ieg.py`, `application/ieg_builder.py` | LK-05 | IEG types, `validate_ieg`, `IegIndex` queries, and the pure builder. |
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

## IEG builder (LK-05)

`radius_evidence.application.ieg_builder.build_ieg(...)` builds the Intent-Evidence Graph for one (analysis, head SHA) from plain DTOs: criteria, changed symbols, criterion->symbol, symbol->test and criterion->test edges, assertion records, tamper findings, case outcomes and (optionally) evidence items. `build_ieg_from_stage_a(stage_a, cases=..., evidence=...)` takes a `StageAInput`. `build_ieg_with_report` also returns an `IegBuildReport` (dropped or merged edges, notes, unlinked criteria, criteria with no usable test).

- Ids: `crit:<id>`, `sym:<symbol_id>`, `tst:<test_id>`, `evd:<evidence_id>`, `tfd:<finding_id>`; edge ids `e_` + sha256(kind|src|dst|method)[:16]. Nodes and edges are sorted; output is byte-identical for equal inputs in any order. `inputs_digest` hashes the normalized inputs and ignores `collected_at`.
- Policy: an edge naming an unknown criterion or symbol is dropped and reported, never repaired; non-finite weights are dropped, out-of-range weights clamped; duplicate edges merge (max weight, union of reasons); evidence from another analysis or head SHA is rejected (no cross-analysis edges); test nodes are created on demand. A tamper finding with no resolvable target keeps its node (it is a penalty and must not vanish). Finding snippets are not copied into the graph.
- Symbol->test edge methods derive from the LK-03 link kind: `static` (calls, imports, fixtures), `naming`, `dynamic`.
- `IegIndex(ieg).paths(criterion_id)` returns every criterion -> symbol -> test path with `w_cs`, `w_st` and `r_ct` (0 when no ADDRESSED_BY edge: a symbol-level test link alone is not evidence for the criterion). Other queries: `addressed_tests`, `tests_for_criterion`, `reachable_evidence`, `findings_for_test`, `criteria_for_symbol`, `unlinked_criteria`.
- Persistence: alpha scope is in-memory plus JSON (`Ieg.to_json` / `Ieg.from_json`, stored inside the `verdict_v2` bundle). The normalized `ieg_nodes` / `ieg_edges` tables (migration 0017) are Beta, assigned to a later VS-B0 task.
