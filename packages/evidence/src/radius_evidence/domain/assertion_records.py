"""LK-04 assertion records (plain dicts) to ``AssertionFeatures`` (EV-01 normalizer).

Consumes the ``to_dict()`` shape of ``radius_testing.assertions`` ``AssertionSet``
without importing it. Each record's raw strength features are folded into the
frozen contract kind (``AssertKind``) so EV-06 stays the exact design formula:

======================  =====================================================
LK-04 situation          contract kind (score from the a_static table)
======================  =====================================================
``dead``                 ``tautology`` (0.00), note ``dead``
``circular``             ``tautology`` (0.00), note ``circular``
``swallowed``            ``tautology`` (0.00), note ``swallowed`` (can never fail)
``mock_only``/mock_call  ``mock_called`` (0.20)
equality                 ``value_equality`` (1.00)
approx                   ``approx_equality`` (0.90)
exception + match        ``exception_type_message`` (0.90)
exception specific       ``exception_type`` (0.80)
exception broad/other    ``truthiness`` (0.25)
membership/regex/quant.  ``membership`` (0.35)
comparison               ``comparison_bound`` (0.35)
length                   ``length_check`` (0.30)
snapshot                 ``snapshot`` (0.30)
truthiness/identity/disj ``truthiness`` (0.25)
none_check               ``none_check`` (0.25)
type_check               ``type_check`` (0.20)
unknown_assert / other   ``other`` (0.00)
======================  =====================================================

``mock_only``, ``circular``, ``dead``, ``swallowed``, ``in_loop`` and ``property_based`` are
explicit boolean fields of ``AssertionFact`` (contract 2); only ``snapshot`` and helper use
remain note tokens. All of them are reason codes in EV-06 and never change the score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from radius_evidence.domain.enums import AssertKind
from radius_evidence.domain.model import AssertionFact, AssertionFeatures, Reason

_KIND_MAP: dict[str, AssertKind] = {
    "equality": AssertKind.VALUE_EQUALITY,
    "approx": AssertKind.APPROX_EQUALITY,
    "membership": AssertKind.MEMBERSHIP,
    "regex": AssertKind.MEMBERSHIP,
    "quantified": AssertKind.MEMBERSHIP,
    "comparison": AssertKind.COMPARISON_BOUND,
    "length": AssertKind.LENGTH_CHECK,
    "snapshot": AssertKind.SNAPSHOT,
    "truthiness": AssertKind.TRUTHINESS,
    "identity": AssertKind.TRUTHINESS,
    "disjunction": AssertKind.TRUTHINESS,
    "none_check": AssertKind.NONE_CHECK,
    "type_check": AssertKind.TYPE_CHECK,
    "mock_call": AssertKind.MOCK_CALLED,
    "unknown_assert": AssertKind.OTHER,
}

MAX_ASSERTIONS_PER_TEST = 500


@dataclass(frozen=True, slots=True)
class AssertionConversion:
    features: tuple[AssertionFeatures, ...]
    rejected: tuple[Reason, ...] = ()


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def fact_kind(
    record_kind: str, strength: Mapping[str, Any]
) -> tuple[AssertKind, tuple[str, ...]]:
    """Contract kind and note tokens for one LK-04 record."""

    notes: list[str] = []
    for flag in ("in_loop", "property_based"):
        if strength.get(flag):
            notes.append(flag)
    if _int(strength.get("helper_depth")) > 0:
        notes.append("helper")
    if record_kind == "snapshot":
        notes.append("snapshot")

    for flag in ("dead", "circular", "swallowed"):
        if strength.get(flag):
            return AssertKind.TAUTOLOGY, (flag, *notes)
    if strength.get("mock_only"):
        return AssertKind.MOCK_CALLED, ("mock_only", *notes)

    if record_kind in ("exception", "warning"):
        spec = str(strength.get("exception_specificity") or "none")
        if spec == "specific_match" or (
            spec == "specific" and strength.get("exception_match")
        ):
            return AssertKind.EXCEPTION_TYPE_MESSAGE, tuple(notes)
        if spec in ("specific", "none") and record_kind == "warning":
            return AssertKind.EXCEPTION_TYPE, tuple(notes)
        if spec == "specific":
            return AssertKind.EXCEPTION_TYPE, tuple(notes)
        return AssertKind.TRUTHINESS, tuple(notes)  # broad / unknown exception type
    return _KIND_MAP.get(record_kind, AssertKind.OTHER), tuple(notes)


def _fact(record: Mapping[str, Any]) -> AssertionFact | None:
    kind_raw = record.get("kind")
    if not isinstance(kind_raw, str):
        return None
    strength = _map(record.get("strength_features"))
    kind, notes = fact_kind(kind_raw, strength)
    # Contract 2: explicit boolean flags replace the former note tokens. Only the
    # tokens without a flag (``helper``, ``snapshot``) stay in ``note``.
    flags = {
        name: bool(strength.get(name))
        for name in ("mock_only", "circular", "dead", "swallowed", "in_loop", "property_based")
    }
    notes = tuple(n for n in notes if n not in flags)
    location = _map(record.get("location"))
    refs = _map(record.get("subject")).get("refs")
    symbol_ids: list[str] = []
    if isinstance(refs, list):
        for ref in refs:
            ids = _map(ref).get("symbol_ids")
            if isinstance(ids, list):
                symbol_ids.extend(s for s in ids if isinstance(s, str))
    computed = _int(strength.get("distinct_subject_symbols")) > 0 or bool(symbol_ids)
    return AssertionFact(
        kind=kind,
        line=_int(location.get("line")),
        target_symbol_ids=tuple(sorted(set(symbol_ids))),
        compares_computed_value=computed,
        note=" ".join(notes) or None,
        **flags,
    )


def _called_refs(records: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    out: set[str] = set()
    for rec in records:
        refs = _map(rec.get("subject")).get("refs")
        if isinstance(refs, list):
            for ref in refs:
                name = _map(ref).get("qualified") or _map(ref).get("name")
                if isinstance(name, str) and name:
                    out.add(name)
    return tuple(sorted(out))


def features_from_assertion_set(
    data: Mapping[str, Any],
    *,
    name_terms: Mapping[str, tuple[str, ...]] | None = None,
    literal_terms: Mapping[str, tuple[str, ...]] | None = None,
) -> AssertionConversion:
    """Convert an LK-04 ``AssertionSet.to_dict()`` into one ``AssertionFeatures`` per test.

    Malformed records are skipped and reported, never raised. Output is sorted by
    ``test_id``. ``name_terms``/``literal_terms`` (VS-04 inputs) may be supplied per test.
    """

    rejected: list[Reason] = []
    if not isinstance(data, Mapping):
        return AssertionConversion(
            (), (Reason("malformed_assertion_set", "not a mapping"),)
        )

    by_test: dict[str, list[Mapping[str, Any]]] = {}
    raw_assertions = data.get("assertions")
    if raw_assertions is not None and not isinstance(raw_assertions, list):
        rejected.append(Reason("malformed_assertion_set", "assertions is not a list"))
    for rec in raw_assertions if isinstance(raw_assertions, list) else []:
        test_id = _map(rec).get("test_id")
        if not isinstance(rec, Mapping) or not isinstance(test_id, str) or not test_id:
            rejected.append(Reason("malformed_assertion_record", "missing test_id"))
            continue
        by_test.setdefault(test_id, []).append(rec)

    summaries: dict[str, Mapping[str, Any]] = {}
    raw_tests = data.get("tests")
    for summary in raw_tests if isinstance(raw_tests, list) else []:
        tid = _map(summary).get("test_id")
        if isinstance(tid, str) and tid:
            summaries[tid] = summary
        else:
            rejected.append(Reason("malformed_test_summary", "missing test_id"))

    names = name_terms or {}
    literals = literal_terms or {}
    out: list[AssertionFeatures] = []
    for test_id in sorted(set(by_test) | set(summaries)):
        records = by_test.get(test_id, [])
        if len(records) > MAX_ASSERTIONS_PER_TEST:
            rejected.append(
                Reason(
                    "too_many_assertions",
                    f"truncated to {MAX_ASSERTIONS_PER_TEST}",
                    test_id,
                )
            )
            records = records[:MAX_ASSERTIONS_PER_TEST]
        facts: list[AssertionFact] = []
        for rec in records:
            fact = _fact(rec)
            if fact is None:
                rejected.append(
                    Reason("malformed_assertion_record", "missing kind", test_id)
                )
            else:
                facts.append(fact)
        facts.sort(key=lambda f: (f.line, f.kind.value))
        summary = summaries.get(test_id, {})
        locs = [_map(_map(r).get("location")) for r in records]
        lines = [_int(loc.get("line")) for loc in locs if loc]
        ends = [_int(loc.get("end_line")) for loc in locs if loc]
        line_start = _int(summary.get("line"), min(lines) if lines else 0)
        line_end = max([line_start, *ends])
        path = summary.get("path") if isinstance(summary.get("path"), str) else None
        path = (
            path
            or (_map(locs[0]).get("path") if locs else None)
            or test_id.split("::", 1)[0]
        )
        case_count = summary.get("case_count")
        out.append(
            AssertionFeatures(
                test_id=test_id,
                path=str(path),
                line_start=line_start,
                line_end=line_end,
                assertions=tuple(facts),
                n_assertions=len(facts),
                expects_exception=any(
                    _map(r).get("kind") in ("exception", "warning") for r in records
                ),
                is_parametrized=bool(summary.get("parametrized")),
                n_param_cases=case_count if isinstance(case_count, int) else None,
                has_skip_marker=bool(summary.get("has_skip_marker")),
                name_terms=tuple(names.get(test_id, ())),
                literal_terms=tuple(literals.get(test_id, ())),
                called_symbol_refs=_called_refs(records),
            )
        )
    return AssertionConversion(tuple(out), tuple(rejected))
