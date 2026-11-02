"""Pure IEG builder (design 3.4, LK-05).

``build_ieg`` turns plain Stage A data (criteria, changed symbols, the three kinds
of links, assertion records, tamper findings, case outcomes, evidence items) into
an :class:`~radius_evidence.domain.ieg.Ieg` with stable ids. It is deterministic:
the output does not depend on input order, and equal inputs give byte-identical
JSON. It never raises on dirty producer data: edges that would break an invariant
are dropped and listed in the :class:`IegBuildReport` returned by
:func:`build_ieg_with_report`.

Policy (decisions of this module):

* Symbols and criteria are only taken from the explicit inputs. An edge that
  names an unknown criterion or symbol is dropped (reported), never repaired.
* Test nodes are created on demand from any source that names a test
  (symbol->test links, criterion->test edges, assertions, changed tests, tamper
  findings, evidence). Case outcomes only annotate existing test nodes.
* Duplicate edges (same kind, endpoints and method) merge: maximum weight, union
  of reasons. Conflicting duplicate nodes keep the lexicographically smallest
  canonical form.
* The graph is layered (criterion -> symbol -> test -> evidence, finding -> test
  or symbol or evidence) so it is acyclic by construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from typing import Any

from radius_evidence.domain.enums import EdgeKind, EvidenceKind, NodeKind, Outcome
from radius_evidence.domain.ieg import (
    Ieg,
    IegEdge,
    IegNode,
    edge_id,
    node_id,
)
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    StageAInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import AssertionFeatures, EvidenceItem, Reason
from radius_evidence.domain.serialization import (
    Serializable,
    canonical_json,
    encode,
    sha256_hex,
)
from radius_evidence.domain.versions import IEG_VERSION

#: Worst outcome wins when several cases map to one test (parametrized tests).
_OUTCOME_SEVERITY: dict[Outcome, int] = {
    Outcome.ERROR: 5,
    Outcome.FAILED: 4,
    Outcome.FLAKY: 3,
    Outcome.SKIPPED: 2,
    Outcome.NOT_RUN: 1,
    Outcome.PASSED: 0,
}

_LINK_KIND_METHOD = {
    "dynamic_coverage": "dynamic",
    "name_convention": "naming",
}
_STATIC_KINDS = frozenset(
    {"direct_call", "indirect_call", "import_reference", "fixture_dependency"}
)


@dataclass(frozen=True, slots=True)
class IegBuildReport(Serializable):
    """What the builder dropped, merged or found missing; never affects the graph."""

    notes: tuple[Reason, ...] = ()
    unlinked_criteria: tuple[str, ...] = ()  # no implemented_by and no addressed_by edge
    #: no test that is both relevant (addressed_by) and linked through an implementing symbol
    untested_criteria: tuple[str, ...] = ()
    dropped_edges: int = 0
    merged_edges: int = 0


def build_ieg_from_stage_a(
    stage_a: StageAInput,
    *,
    cases: Sequence[CaseOutcomeInput] = (),
    evidence: Sequence[EvidenceItem] = (),
) -> Ieg:
    """Build the IEG from a persisted :class:`StageAInput` plus optional outcomes."""

    return build_ieg(
        analysis_id=stage_a.analysis_id,
        head_sha=stage_a.head_sha,
        criteria=stage_a.criteria,
        symbols=stage_a.symbols,
        criterion_symbol=stage_a.criterion_symbol,
        symbol_test=stage_a.symbol_test,
        criterion_test=stage_a.criterion_test,
        assertions=stage_a.assertions,
        tamper=stage_a.tamper,
        changed_test_ids=stage_a.changed_test_ids,
        cases=cases,
        evidence=evidence,
    )


def build_ieg(**kwargs: Any) -> Ieg:
    """Like :func:`build_ieg_with_report` but returns only the graph."""

    return build_ieg_with_report(**kwargs)[0]


def build_ieg_with_report(
    *,
    analysis_id: str,
    head_sha: str,
    criteria: Iterable[CriterionInput] = (),
    symbols: Iterable[SymbolInput] = (),
    criterion_symbol: Iterable[CriterionSymbolEdgeInput] = (),
    symbol_test: Iterable[SymbolTestEdgeInput] = (),
    criterion_test: Iterable[CriterionTestEdgeInput] = (),
    assertions: Iterable[AssertionFeatures] = (),
    tamper: Iterable[TamperFindingInput] = (),
    changed_test_ids: Iterable[str] = (),
    cases: Iterable[CaseOutcomeInput] = (),
    evidence: Iterable[EvidenceItem] = (),
) -> tuple[Ieg, IegBuildReport]:
    """Build the graph for one (analysis, head SHA)."""

    b = _Builder(analysis_id, head_sha)
    criteria_t = tuple(criteria)
    symbols_t = tuple(symbols)
    cs_t = tuple(criterion_symbol)
    st_t = tuple(symbol_test)
    ct_t = tuple(criterion_test)
    as_t = tuple(assertions)
    tf_t = tuple(tamper)
    changed_t = tuple(changed_test_ids)
    cases_t = tuple(cases)
    ev_t = tuple(evidence)

    b.add_criteria(criteria_t)
    b.add_symbols(symbols_t)
    b.collect_assertions(as_t)
    b.collect_changed(changed_t)
    b.collect_cases(cases_t)
    b.add_criterion_symbol(cs_t)
    b.add_symbol_test(st_t)
    b.add_criterion_test(ct_t)
    b.add_tamper(tf_t)
    b.add_evidence(ev_t)
    ieg = b.finish(
        _inputs_digest(
            analysis_id, head_sha, criteria_t, symbols_t, cs_t, st_t, ct_t, as_t, tf_t,
            changed_t, cases_t, ev_t,
        )
    )
    return ieg, b.report(ieg)


# ------------------------------------------------------------------ internals


class _Builder:
    def __init__(self, analysis_id: str, head_sha: str) -> None:
        self.analysis_id = analysis_id
        self.head_sha = head_sha
        self.nodes: dict[str, IegNode] = {}
        self.edges: dict[str, IegEdge] = {}
        self.notes: list[Reason] = []
        self.dropped = 0
        self.merged = 0
        self._assertions: dict[str, AssertionFeatures] = {}
        self._changed: set[str] = set()
        self._outcomes: dict[str, Outcome] = {}
        self._test_ids: set[str] = set()

    # -- helpers

    def note(self, code: str, detail: str, ref: str | None = None) -> None:
        self.notes.append(Reason(code=code, detail=detail, ref=ref))

    def drop(self, code: str, detail: str, ref: str | None = None) -> None:
        self.dropped += 1
        self.note(code, detail, ref)

    def put_node(self, kind: NodeKind, ref: str, attrs: dict[str, Any]) -> None:
        nid = node_id(kind, ref)
        node = IegNode(node_id=nid, kind=kind, ref=ref, attrs=encode(attrs))
        cur = self.nodes.get(nid)
        if cur is None:
            self.nodes[nid] = node
        elif cur != node:
            self.note("duplicate_node_conflict", f"conflicting duplicates of {nid}", nid)
            if canonical_json(node) < canonical_json(cur):
                self.nodes[nid] = node

    def weight(self, value: float, ref: str) -> float | None:
        try:
            w = float(value)
        except (TypeError, ValueError):
            w = float("nan")
        if not isfinite(w):
            self.drop("invalid_weight", f"non-finite weight {value!r}", ref)
            return None
        if w < 0.0 or w > 1.0:
            self.note("weight_clamped", f"weight {w} clamped to [0, 1]", ref)
            w = min(1.0, max(0.0, w))
        return round(w, 6)

    def put_edge(
        self,
        kind: EdgeKind,
        src: str,
        dst: str,
        weight: float,
        method: str,
        reasons: Sequence[Reason] = (),
        attrs: dict[str, Any] | None = None,
    ) -> None:
        eid = edge_id(kind, src, dst, method)
        new = IegEdge(
            edge_id=eid,
            kind=kind,
            src=src,
            dst=dst,
            weight=weight,
            method=method,
            reasons=tuple(sorted(set(reasons), key=_reason_key)),
            attrs=encode(attrs or {}),
        )
        cur = self.edges.get(eid)
        if cur is None:
            self.edges[eid] = new
            return
        self.merged += 1
        self.note("duplicate_edge_merged", f"merged duplicate {kind.value} edge", eid)
        # Keep the attrs of the stronger (then canonically smaller) duplicate; union reasons.
        winner = min((cur, new), key=lambda e: (-e.weight, canonical_json(e.attrs)))
        reasons_all = tuple(sorted(set(cur.reasons) | set(new.reasons), key=_reason_key))
        self.edges[eid] = replace(winner, weight=max(cur.weight, new.weight), reasons=reasons_all)

    def ensure_test(self, test_id: str) -> str:
        self._test_ids.add(test_id)
        return node_id(NodeKind.TEST, test_id)

    # -- inputs

    def add_criteria(self, criteria: Iterable[CriterionInput]) -> None:
        for c in criteria:
            self.put_node(
                NodeKind.CRITERION,
                c.criterion_id,
                {
                    "weight": c.weight,
                    "testability": c.testability,
                    "lifecycle": c.lifecycle,
                    "hints_paths": sorted(c.hints_paths),
                    "hints_tests": sorted(c.hints_tests),
                },
            )

    def add_symbols(self, symbols: Iterable[SymbolInput]) -> None:
        for s in symbols:
            self.put_node(
                NodeKind.SYMBOL,
                s.symbol_id,
                {
                    "path": s.path,
                    "qualified_name": s.qualified_name,
                    "symbol_kind": s.kind,
                    "language": s.language,
                    "change_kind": s.change_kind,
                    "is_behavioral": s.is_behavioral,
                    "is_test": s.is_test,
                    "is_pseudo": s.is_pseudo,
                },
            )

    def collect_assertions(self, assertions: Iterable[AssertionFeatures]) -> None:
        for a in assertions:
            cur = self._assertions.get(a.test_id)
            if cur is not None and cur != a:
                self.note("duplicate_assertion_record", "kept the canonically smaller", a.test_id)
                if canonical_json(a) >= canonical_json(cur):
                    continue
            self._assertions[a.test_id] = a
            self._test_ids.add(a.test_id)

    def collect_changed(self, changed: Iterable[str]) -> None:
        for t in changed:
            self._changed.add(t)
            self._test_ids.add(t)

    def collect_cases(self, cases: Iterable[CaseOutcomeInput]) -> None:
        for c in cases:
            if c.test_id is None:
                self.note("case_unmatched", "case has no resolved test id", c.raw_name)
                continue
            cur = self._outcomes.get(c.test_id)
            if cur is None or _OUTCOME_SEVERITY[c.outcome] > _OUTCOME_SEVERITY[cur]:
                self._outcomes[c.test_id] = c.outcome

    def add_criterion_symbol(self, links: Iterable[CriterionSymbolEdgeInput]) -> None:
        for e in links:
            src, dst = node_id(NodeKind.CRITERION, e.criterion_id), node_id(NodeKind.SYMBOL, e.symbol_id)
            ref = f"{e.criterion_id}->{e.symbol_id}"
            if src not in self.nodes:
                self.drop("unknown_criterion", "criterion->symbol link names an unknown criterion", ref)
                continue
            if dst not in self.nodes:
                self.drop("unknown_symbol", "criterion->symbol link names an unknown symbol", ref)
                continue
            w = self.weight(e.score, ref)
            if w is None:
                continue
            self.put_edge(
                EdgeKind.IMPLEMENTED_BY,
                src,
                dst,
                w,
                "combined",
                e.reasons,
                {"rank": e.rank, "by_linker": dict(e.by_linker)},
            )

    def add_symbol_test(self, links: Iterable[SymbolTestEdgeInput]) -> None:
        for e in links:
            src = node_id(NodeKind.SYMBOL, e.symbol_id)
            ref = f"{e.symbol_id}->{e.test_id}"
            if src not in self.nodes:
                self.drop("unknown_symbol", "symbol->test link names an unknown symbol", ref)
                continue
            w = self.weight(e.score, ref)
            if w is None:
                continue
            dst = self.ensure_test(e.test_id)
            self.put_edge(
                EdgeKind.EXERCISED_BY,
                src,
                dst,
                w,
                _link_method(e.kind),
                (),
                {"kind": e.kind, "depth": e.depth},
            )

    def add_criterion_test(self, links: Iterable[CriterionTestEdgeInput]) -> None:
        for e in links:
            src = node_id(NodeKind.CRITERION, e.criterion_id)
            ref = f"{e.criterion_id}->{e.test_id}"
            if src not in self.nodes:
                self.drop("unknown_criterion", "criterion->test link names an unknown criterion", ref)
                continue
            w = self.weight(e.weight, ref)
            if w is None:
                continue
            dst = self.ensure_test(e.test_id)
            attrs: dict[str, Any] = {}
            if e.bm25_raw is not None:
                attrs["bm25_raw"] = e.bm25_raw
            self.put_edge(EdgeKind.ADDRESSED_BY, src, dst, w, e.method, (), attrs)

    def add_tamper(self, findings: Iterable[TamperFindingInput]) -> None:
        for f in findings:
            fid = node_id(NodeKind.FINDING, f.finding_id)
            conf = self.weight(f.confidence, f.finding_id)
            if conf is None:
                # A finding is a penalty; losing it would favour the PR. Keep it at full weight.
                self.dropped -= 1
                self.note("finding_confidence_defaulted", "invalid confidence treated as 1.0", f.finding_id)
                conf = 1.0
            self.put_node(
                NodeKind.FINDING,
                f.finding_id,
                {
                    "rule_id": f.rule_id,
                    "check": f.check,
                    "severity": f.severity,
                    "confidence": conf,
                    "path": f.path,
                    "reason": f.reason,
                },
            )
            attrs = {"severity": f.severity, "rule_id": f.rule_id}
            attached = False
            if f.test_id:
                self.put_edge(
                    EdgeKind.AFFECTS, fid, self.ensure_test(f.test_id), conf, "tamper_rule", (), attrs
                )
                attached = True
            if f.symbol:
                sid = node_id(NodeKind.SYMBOL, f.symbol)
                if sid in self.nodes:
                    self.put_edge(EdgeKind.AFFECTS, fid, sid, conf, "tamper_rule", (), attrs)
                    attached = True
                else:
                    self.drop("unknown_symbol", "tamper finding names an unknown symbol", f.finding_id)
            if not attached:
                self.note("finding_unattached", "tamper finding affects no known node", f.finding_id)

    def add_evidence(self, items: Iterable[EvidenceItem]) -> None:
        for item in items:
            if item.analysis_id != self.analysis_id or item.head_sha != self.head_sha:
                self.drop(
                    "evidence_other_analysis",
                    "evidence item belongs to another analysis or head SHA",
                    item.evidence_id,
                )
                continue
            if item.kind is EvidenceKind.TAMPER_FINDING:
                owner = node_id(NodeKind.FINDING, item.subject_id)
                if owner not in self.nodes:
                    self.drop("evidence_subject_missing", "no tamper finding node", item.evidence_id)
                    continue
            else:
                owner = self.ensure_test(item.subject_id)
            self.put_node(
                NodeKind.EVIDENCE,
                item.evidence_id,
                {
                    "kind": item.kind,
                    "source": item.source,
                    "subject_id": item.subject_id,
                    "outcome": item.outcome,
                    "severity": item.severity,
                    "rule_id": item.rule_id,
                    "flaky": item.flaky.flagged,
                    "freshness": item.freshness.f,
                    "independence": item.independence.factor,
                },
            )
            self.put_edge(
                EdgeKind.PRODUCED,
                owner,
                node_id(NodeKind.EVIDENCE, item.evidence_id),
                1.0,
                item.source.value,
            )

    # -- output

    def _test_nodes(self) -> None:
        for tid in self._test_ids:
            features = self._assertions.get(tid)
            outcome = self._outcomes.get(tid)
            attrs: dict[str, Any] = {
                "path": features.path if features else tid.split("::", 1)[0],
                "changed_in_pr": tid in self._changed,
                "outcome": outcome,
            }
            if features:
                attrs.update(
                    n_assertions=features.n_assertions,
                    expects_exception=features.expects_exception,
                    is_parametrized=features.is_parametrized,
                    has_skip_marker=features.has_skip_marker,
                )
            self.put_node(NodeKind.TEST, tid, attrs)

    def finish(self, digest: str) -> Ieg:
        self._test_nodes()
        edges = sorted(self.edges.values(), key=lambda e: (e.kind.value, e.src, e.dst, e.method))
        return Ieg(
            analysis_id=self.analysis_id,
            head_sha=self.head_sha,
            nodes=tuple(self.nodes[k] for k in sorted(self.nodes)),
            edges=tuple(edges),
            inputs_digest=digest,
            algo_version=IEG_VERSION,
        )

    def report(self, ieg: Ieg) -> IegBuildReport:
        has_edge: dict[str, set[EdgeKind]] = {}
        sym_tests: dict[str, set[str]] = {}
        implemented: dict[str, set[str]] = {}
        addressed: dict[str, set[str]] = {}
        for e in ieg.edges:
            has_edge.setdefault(e.src, set()).add(e.kind)
            if e.kind is EdgeKind.EXERCISED_BY:
                sym_tests.setdefault(e.src, set()).add(e.dst)
            elif e.kind is EdgeKind.IMPLEMENTED_BY:
                implemented.setdefault(e.src, set()).add(e.dst)
            elif e.kind is EdgeKind.ADDRESSED_BY:
                addressed.setdefault(e.src, set()).add(e.dst)
        unlinked: list[str] = []
        untested: list[str] = []
        for n in ieg.nodes:
            if n.kind is not NodeKind.CRITERION:
                continue
            if not has_edge.get(n.node_id, set()) & {EdgeKind.IMPLEMENTED_BY, EdgeKind.ADDRESSED_BY}:
                unlinked.append(n.ref)
            # A usable test needs the whole chain: a relevance edge to a test that
            # also exercises one of the criterion's symbols (design 3.5, F4).
            via_symbols: set[str] = set()
            for sid in implemented.get(n.node_id, ()):
                via_symbols |= sym_tests.get(sid, set())
            if not addressed.get(n.node_id, set()) & via_symbols:
                untested.append(n.ref)
        notes = tuple(sorted(set(self.notes), key=_reason_key))
        return IegBuildReport(
            notes=notes,
            unlinked_criteria=tuple(unlinked),
            untested_criteria=tuple(untested),
            dropped_edges=self.dropped,
            merged_edges=self.merged,
        )


def _link_method(kind: str) -> str:
    if kind in _LINK_KIND_METHOD:
        return _LINK_KIND_METHOD[kind]
    if kind in _STATIC_KINDS:
        return "static"
    return "combined"


def _reason_key(r: Reason) -> tuple[str, str, str]:
    return (r.code, r.detail, r.ref or "")


def _inputs_digest(analysis_id: str, head_sha: str, *groups: Sequence[Any]) -> str:
    """SHA-256 over the normalized inputs; order independent; ignores ``collected_at``."""

    parts: list[list[str]] = []
    for group in groups:
        items = [replace(g, collected_at="") if isinstance(g, EvidenceItem) else g for g in group]
        parts.append(sorted(canonical_json(i) for i in items))
    return sha256_hex(canonical_json({"analysis_id": analysis_id, "head_sha": head_sha, "inputs": parts}))
