"""IEG node, edge and graph types, invariants and queries (design 3.4, LK-05).

The builder lives in ``radius_evidence.application.ieg_builder``. Everything here
is pure standard library.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from radius_evidence.domain.enums import EdgeKind, NodeKind
from radius_evidence.domain.model import Reason
from radius_evidence.domain.serialization import Serializable, sha256_hex
from radius_evidence.domain.versions import IEG_VERSION


@dataclass(frozen=True, slots=True)
class IegNode(Serializable):
    """``node_id``: crit:<id> | sym:<symbol_id> | tst:<test_id> | evd:<id> | tfd:<id>."""

    node_id: str
    kind: NodeKind
    ref: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IegEdge(Serializable):
    """``edge_id`` = "e_" + sha256(kind|src|dst|method)[:16]; ``weight`` in [0, 1]."""

    edge_id: str
    kind: EdgeKind
    src: str
    dst: str
    weight: float
    method: str  # combined|explicit|static|naming|dynamic|lexical_test_relevance|...
    reasons: tuple[Reason, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Ieg(Serializable):
    analysis_id: str
    head_sha: str
    nodes: tuple[IegNode, ...]
    edges: tuple[IegEdge, ...]
    inputs_digest: str
    algo_version: str = IEG_VERSION


# --------------------------------------------------------------------------- ids

NODE_PREFIX: dict[NodeKind, str] = {
    NodeKind.CRITERION: "crit:",
    NodeKind.SYMBOL: "sym:",
    NodeKind.TEST: "tst:",
    NodeKind.EVIDENCE: "evd:",
    NodeKind.FINDING: "tfd:",
}

#: Allowed (source kind, destination kind) pairs per edge kind (design 3.4).
#: ``PRODUCED`` also connects a tamper finding to the evidence item it produced.
ALLOWED_ENDPOINTS: dict[EdgeKind, frozenset[tuple[NodeKind, NodeKind]]] = {
    EdgeKind.IMPLEMENTED_BY: frozenset({(NodeKind.CRITERION, NodeKind.SYMBOL)}),
    EdgeKind.EXERCISED_BY: frozenset({(NodeKind.SYMBOL, NodeKind.TEST)}),
    EdgeKind.ADDRESSED_BY: frozenset({(NodeKind.CRITERION, NodeKind.TEST)}),
    EdgeKind.PRODUCED: frozenset(
        {(NodeKind.TEST, NodeKind.EVIDENCE), (NodeKind.FINDING, NodeKind.EVIDENCE)}
    ),
    EdgeKind.AFFECTS: frozenset(
        {(NodeKind.FINDING, NodeKind.TEST), (NodeKind.FINDING, NodeKind.SYMBOL)}
    ),
}


def node_id(kind: NodeKind, ref: str) -> str:
    """Stable node id: ``crit:<id>``, ``sym:<symbol_id>``, ``tst:<test_id>`` ..."""

    return NODE_PREFIX[kind] + ref


def edge_id(kind: EdgeKind, src: str, dst: str, method: str) -> str:
    """``"e_" + sha256(kind|src|dst|method)[:16]``."""

    return "e_" + sha256_hex(f"{kind.value}|{src}|{dst}|{method}")[:16]


# ---------------------------------------------------------------- invariants


def validate_ieg(ieg: Ieg) -> tuple[str, ...]:
    """Return every violated graph invariant (empty tuple when the graph is sound).

    Checked: unique node and edge ids, node id matches kind and ref, no edge with
    a missing endpoint, endpoint kinds allowed for the edge kind, weights finite
    and in [0, 1], edge id matches its content, output sorted.
    """

    problems: list[str] = []
    nodes: dict[str, IegNode] = {}
    for n in ieg.nodes:
        if n.node_id in nodes:
            problems.append(f"duplicate node id {n.node_id}")
        nodes[n.node_id] = n
        if n.node_id != node_id(n.kind, n.ref):
            problems.append(f"node id {n.node_id} does not match kind/ref")
    seen: set[str] = set()
    for e in ieg.edges:
        if e.edge_id in seen:
            problems.append(f"duplicate edge id {e.edge_id}")
        seen.add(e.edge_id)
        if e.edge_id != edge_id(e.kind, e.src, e.dst, e.method):
            problems.append(f"edge id {e.edge_id} does not match its content")
        src, dst = nodes.get(e.src), nodes.get(e.dst)
        if src is None or dst is None:
            problems.append(f"edge {e.edge_id} has a missing endpoint")
        elif (src.kind, dst.kind) not in ALLOWED_ENDPOINTS[e.kind]:
            problems.append(
                f"edge {e.edge_id} kind {e.kind.value} cannot connect "
                f"{src.kind.value} to {dst.kind.value}"
            )
        if not (isfinite(e.weight) and 0.0 <= e.weight <= 1.0):
            problems.append(f"edge {e.edge_id} weight {e.weight!r} outside [0, 1]")
    if [n.node_id for n in ieg.nodes] != sorted(nodes):
        problems.append("nodes are not sorted by node_id")
    keys = [(e.kind.value, e.src, e.dst, e.method) for e in ieg.edges]
    if keys != sorted(keys):
        problems.append("edges are not sorted")
    return tuple(problems)


# -------------------------------------------------------------------- queries


@dataclass(frozen=True, slots=True)
class IegPath(Serializable):
    """One ``criterion -> symbol -> test`` path with its three weights.

    ``w_cs`` is the IMPLEMENTED_BY weight, ``w_st`` the EXERCISED_BY weight and
    ``r_ct`` the ADDRESSED_BY weight of (criterion, test), 0.0 when that edge is
    absent (design 3.5: absent means the test is not evidence for the criterion).
    """

    criterion_id: str
    symbol_id: str
    test_id: str
    w_cs: float
    w_st: float
    r_ct: float
    edge_ids: tuple[str, ...]


class IegIndex:
    """Read-only adjacency index over an :class:`Ieg`; build once, query many times."""

    def __init__(self, ieg: Ieg) -> None:
        self.ieg = ieg
        self._nodes: dict[str, IegNode] = {n.node_id: n for n in ieg.nodes}
        self._out: dict[tuple[str, EdgeKind], list[IegEdge]] = {}
        self._in: dict[tuple[str, EdgeKind], list[IegEdge]] = {}
        for e in ieg.edges:
            self._out.setdefault((e.src, e.kind), []).append(e)
            self._in.setdefault((e.dst, e.kind), []).append(e)

    def node(self, nid: str) -> IegNode | None:
        return self._nodes.get(nid)

    def out_edges(self, nid: str, kind: EdgeKind) -> tuple[IegEdge, ...]:
        return tuple(self._out.get((nid, kind), ()))

    def in_edges(self, nid: str, kind: EdgeKind) -> tuple[IegEdge, ...]:
        return tuple(self._in.get((nid, kind), ()))

    def nodes_of_kind(self, kind: NodeKind) -> tuple[IegNode, ...]:
        return tuple(n for n in self.ieg.nodes if n.kind is kind)

    def paths(self, criterion_id: str) -> tuple[IegPath, ...]:
        """Every ``criterion -> symbol -> test`` path.

        Parallel edges (different methods) between the same two nodes collapse to
        the one with the highest weight (ties: lowest edge id), so one
        (criterion, symbol, test) triple yields exactly one path. Sorted by
        symbol id then test id.
        """

        cid = node_id(NodeKind.CRITERION, criterion_id)
        addressed = _best_by_dst(self._out.get((cid, EdgeKind.ADDRESSED_BY), ()))
        impl = _best_by_dst(self._out.get((cid, EdgeKind.IMPLEMENTED_BY), ()))
        out: list[IegPath] = []
        for sym_edge in impl.values():
            tests = _best_by_dst(self._out.get((sym_edge.dst, EdgeKind.EXERCISED_BY), ()))
            for test_edge in tests.values():
                rel = addressed.get(test_edge.dst)
                ids = (sym_edge.edge_id, test_edge.edge_id) + ((rel.edge_id,) if rel else ())
                out.append(
                    IegPath(
                        criterion_id=criterion_id,
                        symbol_id=self._ref(sym_edge.dst),
                        test_id=self._ref(test_edge.dst),
                        w_cs=sym_edge.weight,
                        w_st=test_edge.weight,
                        r_ct=rel.weight if rel else 0.0,
                        edge_ids=ids,
                    )
                )
        return tuple(sorted(out, key=lambda p: (p.symbol_id, p.test_id)))

    def addressed_tests(self, criterion_id: str) -> tuple[str, ...]:
        """Test ids with an ADDRESSED_BY edge from the criterion (sorted)."""

        cid = node_id(NodeKind.CRITERION, criterion_id)
        return tuple(
            sorted(self._ref(e.dst) for e in self._out.get((cid, EdgeKind.ADDRESSED_BY), ()))
        )

    def tests_for_criterion(self, criterion_id: str) -> tuple[str, ...]:
        """Every test reachable from the criterion via a symbol or a direct edge."""

        found = {p.test_id for p in self.paths(criterion_id)}
        found.update(self.addressed_tests(criterion_id))
        return tuple(sorted(found))

    def findings_for_test(self, test_id: str) -> tuple[str, ...]:
        """Tamper finding ids with an AFFECTS edge to the test (sorted)."""

        tid = node_id(NodeKind.TEST, test_id)
        return tuple(
            sorted(self._ref(e.src) for e in self._in.get((tid, EdgeKind.AFFECTS), ()))
        )

    def findings_for_symbol(self, symbol_id: str) -> tuple[str, ...]:
        sid = node_id(NodeKind.SYMBOL, symbol_id)
        return tuple(
            sorted(self._ref(e.src) for e in self._in.get((sid, EdgeKind.AFFECTS), ()))
        )

    def evidence_for_test(self, test_id: str) -> tuple[str, ...]:
        """Evidence ids produced by the test (sorted)."""

        tid = node_id(NodeKind.TEST, test_id)
        return tuple(
            sorted(self._ref(e.dst) for e in self._out.get((tid, EdgeKind.PRODUCED), ()))
        )

    def reachable_evidence(self, criterion_id: str) -> tuple[str, ...]:
        """All evidence ids reachable from the criterion through its tests."""

        found: set[str] = set()
        for test_id in self.tests_for_criterion(criterion_id):
            found.update(self.evidence_for_test(test_id))
        return tuple(sorted(found))

    def criteria_for_symbol(self, symbol_id: str) -> tuple[str, ...]:
        sid = node_id(NodeKind.SYMBOL, symbol_id)
        return tuple(
            sorted(self._ref(e.src) for e in self._in.get((sid, EdgeKind.IMPLEMENTED_BY), ()))
        )

    def unlinked_criteria(self) -> tuple[str, ...]:
        """Criteria with no IMPLEMENTED_BY and no ADDRESSED_BY edge (sorted)."""

        out = [
            n.ref
            for n in self.nodes_of_kind(NodeKind.CRITERION)
            if not self._out.get((n.node_id, EdgeKind.IMPLEMENTED_BY))
            and not self._out.get((n.node_id, EdgeKind.ADDRESSED_BY))
        ]
        return tuple(sorted(out))

    def _ref(self, nid: str) -> str:
        node = self._nodes.get(nid)
        return node.ref if node is not None else nid.split(":", 1)[-1]


def _best_by_dst(edges: Iterable[IegEdge]) -> dict[str, IegEdge]:
    best: dict[str, IegEdge] = {}
    for e in edges:
        cur = best.get(e.dst)
        if cur is None or (-e.weight, e.edge_id) < (-cur.weight, cur.edge_id):
            best[e.dst] = e
    return best
