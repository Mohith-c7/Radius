"""Freshness binding and staleness (EV-07, design 3.5 ``f`` and fresh-1).

Alpha rule: ``f = 1`` when the evidence is bound to the current head SHA, else
``f = 0`` (reason ``stale_sha``; ``unbound`` when the binding is missing or not a
40-hex SHA). An optional decay hook (default OFF, policy-gated) gives evidence from
an earlier commit a partial factor when *none* of the files it covers (the test file
and the files of the symbols it exercises) changed between the commits:
``f = unchanged_factor ** commits_behind``. If any covered file changed, ``f = 0``.
Staleness is therefore monotone: more changed files or more commits behind never
raise ``f``.

Blob hashes use the git blob object id so adapters can take them from ``git ls-tree``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from radius_evidence.domain.model import EvidenceItem, FreshnessInfo, Reason

_SHA40 = re.compile(r"^[0-9a-f]{40}$")

REASON_CURRENT = "current_head"
REASON_STALE = "stale_sha"
REASON_UNBOUND = "unbound"
#: Only produced when the decay hook is enabled (documented extension of the reason set).
REASON_STALE_UNCHANGED = "stale_sha_unchanged_covered"


@dataclass(frozen=True, slots=True)
class FreshnessConfig:
    decay_enabled: bool = False
    unchanged_factor: float = 0.8  # per commit behind, when no covered file changed


@dataclass(frozen=True, slots=True)
class StalenessReport:
    info: FreshnessInfo
    changed_paths: tuple[str, ...] = ()
    unchanged_paths: tuple[str, ...] = ()
    reasons: tuple[Reason, ...] = ()


def blob_hash(content: bytes | str) -> str:
    """Git blob object id of ``content`` (sha1 over a ``blob <n>`` header plus bytes)."""

    data = content.encode("utf-8") if isinstance(content, str) else content
    header = b"blob " + str(len(data)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324


def is_valid_sha(value: str | None) -> bool:
    return bool(value) and bool(_SHA40.match(value or ""))


def bind_freshness(bound_sha: str | None, current_sha: str) -> FreshnessInfo:
    """Alpha freshness: 1.0 at the current head SHA, else 0.0."""

    bound = bound_sha or ""
    if not is_valid_sha(bound):
        return FreshnessInfo(bound, current_sha, 0.0, REASON_UNBOUND)
    if bound == current_sha:
        return FreshnessInfo(bound, current_sha, 1.0, REASON_CURRENT)
    return FreshnessInfo(bound, current_sha, 0.0, REASON_STALE)


def changed_covered_paths(
    covered_paths: Iterable[str],
    bound_blobs: Mapping[str, str],
    current_blobs: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split covered paths into (changed, unchanged); a missing blob counts as changed."""

    changed: list[str] = []
    unchanged: list[str] = []
    for path in sorted(set(covered_paths)):
        old, new = bound_blobs.get(path), current_blobs.get(path)
        if old is None or new is None or old != new:
            changed.append(path)
        else:
            unchanged.append(path)
    return tuple(changed), tuple(unchanged)


def assess_staleness(
    bound_sha: str | None,
    current_sha: str,
    *,
    covered_paths: Iterable[str] = (),
    bound_blobs: Mapping[str, str] | None = None,
    current_blobs: Mapping[str, str] | None = None,
    commits_behind: int = 1,
    config: FreshnessConfig | None = None,
) -> StalenessReport:
    """Freshness with blob-level detail. The default config reproduces ``bind_freshness``."""

    cfg = config or FreshnessConfig()
    base = bind_freshness(bound_sha, current_sha)
    if base.reason != REASON_STALE:
        return StalenessReport(base)

    changed, unchanged = changed_covered_paths(
        covered_paths, bound_blobs or {}, current_blobs or {}
    )
    reasons = tuple(
        Reason("covered_file_changed", "changed after the evidence was bound", p)
        for p in changed
    )
    if not cfg.decay_enabled or changed or not unchanged:
        return StalenessReport(base, changed, unchanged, reasons)

    behind = max(1, commits_behind)
    factor = max(0.0, min(1.0, cfg.unchanged_factor)) ** behind
    info = FreshnessInfo(
        base.bound_sha, current_sha, round(factor, 6), REASON_STALE_UNCHANGED
    )
    return StalenessReport(
        info,
        changed,
        unchanged,
        (Reason("covered_files_unchanged", f"decayed over {behind} commit(s)"),),
    )


def apply_freshness(
    item: EvidenceItem, current_sha: str, **kwargs: object
) -> EvidenceItem:
    """Return ``item`` re-bound against ``current_sha`` (the item itself is immutable)."""

    report = assess_staleness(item.head_sha, current_sha, **kwargs)  # type: ignore[arg-type]
    return dataclasses.replace(item, freshness=report.info)


def partition_by_freshness(
    items: Iterable[EvidenceItem],
) -> tuple[tuple[EvidenceItem, ...], tuple[EvidenceItem, ...]]:
    """(usable, ignored): ``ignored`` has ``f == 0`` and is kept for audit."""

    usable: list[EvidenceItem] = []
    ignored: list[EvidenceItem] = []
    for item in items:
        (usable if item.freshness.f > 0.0 else ignored).append(item)
    return tuple(usable), tuple(ignored)
