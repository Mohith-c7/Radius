"""Application-layer entry point: :func:`analyze_tampering`."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import replace

from radius_analysis.symbol_changes.diff_files import parse_unified_diff
from radius_analysis.symbol_changes.model import SymbolChangeSet
from radius_analysis.symbol_changes.snapshots import (
    DiffReversedSnapshot,
    SnapshotReader,
)
from radius_analysis.tamper.config import TamperConfig
from radius_analysis.tamper.context import PackageRegistry, TamperContext
from radius_analysis.tamper.model import (
    CATALOG_VERSION,
    Finding,
    TamperReport,
    WaivedFinding,
    make_finding_id,
)
from radius_analysis.tamper.registry import RuleRegistry, default_registry


class StaticPackageRegistry:
    """Offline :class:`PackageRegistry` backed by a fixed set (tests, air-gapped mirrors)."""

    def __init__(self, known: set[str] | frozenset[str]) -> None:
        self._known = {k.lower().replace("_", "-") for k in known}

    def exists(self, name: str) -> bool | None:
        return name.lower().replace("_", "-") in self._known


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Make ids unique: identical findings in one symbol get an occurrence index."""
    seen: Counter[str] = Counter()
    out = []
    for f in sorted(findings, key=lambda x: x.sort_key()):
        n = seen[f.finding_id]
        seen[f.finding_id] += 1
        if n:
            f = replace(f, finding_id=make_finding_id(
                f.rule_id, f.check, f.path, f.symbol or f.test_id, f.old_snippet, f.new_snippet, n,
            ))
        out.append(f)
    return out


def analyze_tampering(
    changeset: SymbolChangeSet,
    repo_base: SnapshotReader | None,
    repo_head: SnapshotReader,
    config: TamperConfig | None = None,
    *,
    diff_text: str | None = None,
    registry: RuleRegistry | None = None,
    package_registry: PackageRegistry | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> TamperReport:
    """Run the enabled tamper rules over one change set. Deterministic; never raises.

    ``repo_base`` may be ``None`` when ``diff_text`` is given (the base is rebuilt from the
    head snapshot and the diff, as in LK-01); otherwise base-dependent rules degrade.
    """
    config = config or TamperConfig()
    registry = registry or default_registry()
    started = clock()
    if repo_base is None and diff_text:
        try:
            repo_base = DiffReversedSnapshot(repo_head, parse_unified_diff(diff_text))
        except Exception:
            repo_base = None
    try:
        ctx = TamperContext.build(
            changeset, repo_base, repo_head, config, diff_text=diff_text,
            registry=package_registry, clock=clock,
        )
    except Exception as exc:  # the engine promises not to raise
        return TamperReport(
            config_digest=config.digest(), notes=(f"context_error:{type(exc).__name__}",),
        )

    languages = {v.language for v in ctx.files.values()}
    findings: list[Finding] = []
    ran: list[str] = []
    errors: list[str] = []
    truncated = False
    for rule in registry.enabled(config):
        if "*" not in rule.languages and not (rule.languages & languages):
            continue
        if clock() - started > config.params.time_budget_seconds:
            truncated = True
            ctx.notes.append("rule_time_budget_exceeded")
            break
        try:
            findings.extend(rule.evaluate(ctx))
            ran.append(rule.id)
        except Exception as exc:  # one broken rule must not hide the others
            errors.append(f"{rule.id}:{type(exc).__name__}")

    findings = _dedupe(findings)
    kept: list[Finding] = []
    waived: list[WaivedFinding] = []
    for f in findings:
        for i, w in enumerate(config.waivers):
            if w.matches(f.finding_id, f.rule_id, f.check, f.path):
                waived.append(WaivedFinding(f, w.reason, i))
                break
        else:
            kept.append(f)
    if len(kept) > config.params.max_findings:
        kept = sorted(kept, key=lambda f: (-f.severity, f.sort_key()))[: config.params.max_findings]
        kept.sort(key=lambda f: f.sort_key())
        truncated = True
        ctx.notes.append("max_findings_exceeded")
    return TamperReport(
        catalog_version=CATALOG_VERSION,
        findings=tuple(kept),
        waived=tuple(waived),
        unanalyzable=tuple(sorted(ctx.unanalyzable, key=lambda u: (u.path, u.side, u.reason))),
        rules_run=tuple(ran),
        rule_errors=tuple(errors),
        truncated=truncated or changeset.truncated,
        notes=tuple(sorted(set(ctx.notes))),
        config_digest=config.digest(),
    )
