"""Shared helpers for the tamper (EV-02) tests; loaded by path, not as a package."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from radius_analysis.symbol_changes import (
    DictSnapshot,
    ExtractionOptions,
    extract_symbol_changes,
)
from radius_analysis.symbol_changes.testing import make_diff
from radius_analysis.tamper import (
    StaticPackageRegistry,
    TamperConfig,
    TamperReport,
    analyze_tampering,
)

CASES_DIR = Path(__file__).parent / "tamper_cases"


def load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(CASES_DIR.glob("cases_*.py")):
        spec = importlib.util.spec_from_file_location(f"tamper_cases_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases.extend(module.CASES)
    return cases


def analyze(
    base: dict[str, str],
    head: dict[str, str],
    config: TamperConfig | dict | None = None,
    *,
    registry: list[str] | None = None,
    with_diff: bool = True,
) -> TamperReport:
    diff = make_diff(base, head)
    changes = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff, ExtractionOptions())
    if isinstance(config, dict):
        config = TamperConfig.from_dict(config)
    return analyze_tampering(
        changes, DictSnapshot(base), DictSnapshot(head), config,
        diff_text=diff if with_diff else None,
        package_registry=StaticPackageRegistry(set(registry)) if registry is not None else None,
    )


def keys(report: TamperReport) -> list[str]:
    return sorted(f"{f.rule_id}:{f.check}" for f in report.findings)
