"""IEG node, edge and graph types (design 3.4). Builder and queries: LK-05."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from radius_evidence.domain.enums import EdgeKind, NodeKind
from radius_evidence.domain.model import Reason
from radius_evidence.domain.serialization import Serializable
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
