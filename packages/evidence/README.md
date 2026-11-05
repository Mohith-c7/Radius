# Radius Evidence Package

Typed contracts and (later) pure functions that turn validated outcomes into per-criterion support for the **Verdict v2 alpha**. Design: [`docs/research/design/VERDICT_V2_SLICE.md`](../../docs/research/design/VERDICT_V2_SLICE.md); decisions: DEC-027.

Status: VS-00 contracts, the scoring core (EV-08 `quality.py`, VD-01 `support.py`, VD-02 `states.py`), the IEG builder (LK-05) and the first feature wave (EV-01, EV-06, EV-07, EV-03-lite). Algorithm ownership: design section 2.3.

## Layout

| Path | Owner | Content |
| --- | --- | --- |
| `domain/enums.py`, `domain/model.py`, `domain/config.py`, `domain/inputs.py`, `domain/versions.py`, `domain/serialization.py` | VS-00 (contract) | Frozen after VS-00; changing a field name or default needs a contract-change PR approved by the architect. |
| `domain/ieg.py`, `application/ieg_builder.py` | LK-05 | IEG types, `validate_ieg`, `IegIndex` queries, and the pure builder. |
| `domain/quality.py` | EV-08 | `EvidenceQuality` (alias `QualityBreakdown`), `ChainRef`, link mapping, the `q(e, c)` combiner, `evidence_quality_row`. |
| `domain/support.py` | VD-01 | `SupportResult`, `compute_support`, `support_reasons`. |
| `domain/states.py` | VD-02 | `CriterionStateResult`, `UimResult`, `evaluate_criterion`, `compute_uim`, `intent_coverage`. |
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

## IEG builder (LK-05)

`radius_evidence.application.ieg_builder.build_ieg(...)` builds the Intent-Evidence Graph for one (analysis, head SHA) from plain DTOs: criteria, changed symbols, criterion->symbol, symbol->test and criterion->test edges, assertion records, tamper findings, case outcomes and (optionally) evidence items. `build_ieg_from_stage_a(stage_a, cases=..., evidence=...)` takes a `StageAInput`. `build_ieg_with_report` also returns an `IegBuildReport` (dropped or merged edges, notes, unlinked criteria, criteria with no usable test).

- Ids: `crit:<id>`, `sym:<symbol_id>`, `tst:<test_id>`, `evd:<evidence_id>`, `tfd:<finding_id>`; edge ids `e_` + sha256(kind|src|dst|method)[:16]. Nodes and edges are sorted; output is byte-identical for equal inputs in any order. `inputs_digest` hashes the normalized inputs and ignores `collected_at`.
- Policy: an edge naming an unknown criterion or symbol is dropped and reported, never repaired; non-finite weights are dropped, out-of-range weights clamped; duplicate edges merge (max weight, union of reasons); evidence from another analysis or head SHA is rejected (no cross-analysis edges); test nodes are created on demand. A tamper finding with no resolvable target keeps its node (it is a penalty and must not vanish). Finding snippets are not copied into the graph.
- Symbol->test edge methods derive from the LK-03 link kind: `static` (calls, imports, fixtures), `naming`, `dynamic`.
- `IegIndex(ieg).paths(criterion_id)` returns every criterion -> symbol -> test path with `w_cs`, `w_st` and `r_ct` (0 when no ADDRESSED_BY edge: a symbol-level test link alone is not evidence for the criterion). Other queries: `addressed_tests`, `tests_for_criterion`, `reachable_evidence`, `findings_for_test`, `criteria_for_symbol`, `unlinked_criteria`.
- Persistence: alpha scope is in-memory plus JSON (`Ieg.to_json` / `Ieg.from_json`, stored inside the `verdict_v2` bundle). The normalized `ieg_nodes` / `ieg_edges` tables (migration 0017) are Beta, assigned to a later VS-B0 task.

`python -m pytest packages/evidence/tests`. They validate the example payload against `docs/research/design/verdict_v2.schema.json` with a small stdlib validator (no new dependency) and check the fixture expectations against the 8 F-14 fixtures. `test_scoring_fixtures.py` reproduces the design's gold-mode `S(c)`, states, UIM and intent coverage for all 8 fixtures.

## Scoring formulas

Verbatim from design sections 3.5 and 3.9 (profile `alpha-static`: `cap_static` 0.6, `tau_support` 0.5, `tau_weak` 0.2, `rho` 0.7, `s_cap` 0.9, `strong_min` 0.5). Every parameter is read from `VerdictV2Config`.

### Evidence quality `q(e, c)` (EV-08, `quality.py`)

```
l_cs     = 0                        if w(IMPLEMENTED_BY) < link_min_cs      (0.20)
         = min(1, w / link_sat_cs)  otherwise                               (link_sat_cs 0.40)
l_st     = w(EXERCISED_BY)          if w >= min_test_link else 0            (0.50)
r_ct     = w(ADDRESSED_BY)          (0 = edge absent)
l(c,e)   = l_cs * l_st * r_ct
d_eff    = min(cap_static, a_static)
flaky_f  = 0 if flagged by rerun; else 1 - min(flaky_discount_max, score) if a score is known; else 1
tamper_p = 1 - PROD_k (1 - penalty(severity_k))     penalty: critical/high 1.0, medium 0.5, low 0.2, info 0
q(e, c)  = d_eff * i * f * flaky_f * (1 - tamper_p)
term     = lambda_kind * q * l      (0 unless status == "counted")
```

An item is counted when its outcome is PASSED, `r_ct`, `l_st`, `l_cs` and `q` are all positive.

### Support `S(c)` (VD-01, `support.py`)

```
group(e)   = the symbol id on the best path of e
sorted within a group by term desc (ties: evidence_id); k = 0-based rank
contrib(e) = term(e) * rho^k
S_raw(c)   = 1 - PROD_{e in E(c)} (1 - contrib(e))
S(c)       = min(S_raw(c), s_cap)
```

Hand-checkable (cap_static 0.6, i 0.8, l_st 0.9, l_cs = r = 1): one strong test `0.6*0.8*0.9 = 0.432`; two in one group `1 - 0.568*(1 - 0.432*0.7) = 0.604`; three 0.688; four 0.734; one truthiness test 0.180, two 0.283.

### Per-criterion state (VD-02, `states.py`, first match wins)

```
1  lifecycle rejected/orphaned, or testability subjective_or_vague / untestable_external -> excluded
2  an attached item has outcome FAILED or ERROR                       -> contradicted
3  testability non_functional_measurable                              -> unevidenced (+ needs_typed_evidence)
4  S >= tau_support and a counted item with a_static >= strong_min    -> proven
5  S >= tau_support and no strong item                                -> weak (+ no_strong_assertion)
6  tau_weak <= S < tau_support                                        -> weak
7  otherwise                                                          -> unevidenced (+ no_linked_test if E(c) is empty and no ADDRESSED_BY edge)
```

Flags: `tampered`, `flaky_evidence`, `stale_evidence`, `low_link_confidence` (proven with best `l_cs < link_review_min`), `unconfirmed` (lifecycle `proposed`), `pending_results`, `static_only` (always), `no_strong_assertion`, `needs_typed_evidence`, `no_linked_test`.

### UIM and intent coverage

```
C*  = criteria whose state is not "excluded"
UIM = SUM_{c in C*} w_c * [c unproven] / SUM_{c in C*} w_c           (0.0 when C* is empty)

B = changed symbols with is_behavioral and not is_test and not (is_pseudo and kind == "file")
covered(s) = exists a non-excluded criterion with an IMPLEMENTED_BY edge to s with weight >= link_min_cs
             OR s is in the same file as a covered non-pseudo symbol
intent_coverage = |{s in B : covered(s)}| / |B|                      (1.0 when B is empty)
```

`[c unproven]` is `S(c) < tau_support` in the design; the implementation uses `state != proven`, which differs only when `S >= tau_support` without a strong item or when the criterion is contradicted. Details and the decisions taken where the design leaves room: `docs/evidence/scoring.md`.
