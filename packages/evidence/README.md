# Radius Evidence Package

Typed contracts and (later) pure functions that turn validated outcomes into per-criterion support for the **Verdict v2 alpha**. Design: [`docs/research/design/VERDICT_V2_SLICE.md`](../../docs/research/design/VERDICT_V2_SLICE.md); decisions: DEC-027.

Status: **VS-00 contract scaffold plus the scoring core** (EV-08 `quality.py`, VD-01 `support.py`, VD-02 `states.py`). The other algorithms are owned by later tasks (see the ownership map in design section 2.3).

## Layout

| Path | Owner | Content |
| --- | --- | --- |
| `domain/enums.py`, `domain/model.py`, `domain/config.py`, `domain/inputs.py`, `domain/versions.py`, `domain/serialization.py` | VS-00 (contract) | Frozen after VS-00; changing a field name or default needs a contract-change PR approved by the architect. |
| `domain/ieg.py` | LK-05 | IEG node / edge / graph types (builder and queries to come). |
| `domain/quality.py` | EV-08 | `EvidenceQuality` (alias `QualityBreakdown`), `ChainRef`, link mapping, the `q(e, c)` combiner, `evidence_quality_row`. |
| `domain/support.py` | VD-01 | `SupportResult`, `compute_support`, `support_reasons`. |
| `domain/states.py` | VD-02 | `CriterionStateResult`, `UimResult`, `evaluate_criterion`, `compute_uim`, `intent_coverage`. |
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
