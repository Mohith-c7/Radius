"""Pure result model of the tamper rule engine (EV-02).

Frozen dataclasses with a deterministic ``to_dict`` so reports can be stored
later (EV-01 / LK-05), hashed and compared across runs. No I/O lives here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

from radius_analysis.symbol_changes.model import LineRange

CATALOG_VERSION = "tamper-rules-v1"
MAX_SNIPPET_CHARS = 400


class Severity(IntEnum):
    """Ordered so that ``max()`` picks the worst. Values are config, not research results."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def parse(cls, value: str | Severity) -> Severity:
        if isinstance(value, Severity):
            return value
        try:
            return cls[str(value).strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown severity: {value!r}") from exc

    @property
    def label(self) -> str:
        return self.name.lower()


class Family(StrEnum):
    ASSERTION_WEAKENING = "assertion_weakening"
    TEST_DISABLING = "test_disabling"
    TAUTOLOGY = "tautology"
    EXCEPTION_SWALLOWING = "exception_swallowing"
    MOCK_ABUSE = "mock_abuse"
    FIXTURE_TAMPERING = "fixture_tampering"
    CONFIG_WEAKENING = "config_weakening"
    SUPPRESSION = "suppression"
    EXPECTED_VALUE_CHANGE = "expected_value_change"
    DEPENDENCY = "dependency"
    CODE_QUALITY = "code_quality"


_WS = re.compile(r"\s+")


def normalize_snippet(text: str | None) -> str:
    """Whitespace-insensitive form used for ids (formatting must not change ids)."""
    return _WS.sub(" ", text or "").strip()


def clip(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip("\n")
    return text if len(text) <= MAX_SNIPPET_CHARS else text[: MAX_SNIPPET_CHARS - 3] + "..."


def make_finding_id(
    rule_id: str, check: str, path: str, symbol: str | None, old: str | None, new: str | None,
    occurrence: int = 0,
) -> str:
    """Stable id: independent of line numbers and whitespace, so waivers survive rebases."""
    raw = "\x1f".join(
        [CATALOG_VERSION, rule_id, check, path, symbol or "", normalize_snippet(old),
         normalize_snippet(new), str(occurrence)]
    )
    return "tf_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Finding:
    """One explainable tamper finding."""

    finding_id: str
    rule_id: str
    check: str
    family: str
    severity: Severity
    confidence: float
    path: str
    reason: str
    symbol: str | None = None
    test_id: str | None = None
    old_range: LineRange | None = None
    new_range: LineRange | None = None
    old_snippet: str | None = None
    new_snippet: str | None = None
    catalog_version: str = CATALOG_VERSION
    evidence: tuple[str, ...] = ()

    @property
    def waiver_key(self) -> str:
        """The key a waiver uses to refer to this finding."""
        return self.finding_id

    def sort_key(self) -> tuple[Any, ...]:
        rng = self.new_range or self.old_range
        return (self.path, rng.start if rng else 0, self.rule_id, self.check, self.finding_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "check": self.check,
            "family": self.family,
            "severity": self.severity.label,
            "confidence": self.confidence,
            "path": self.path,
            "symbol": self.symbol,
            "test_id": self.test_id,
            "old_range": self.old_range.to_dict() if self.old_range else None,
            "new_range": self.new_range.to_dict() if self.new_range else None,
            "old_snippet": self.old_snippet,
            "new_snippet": self.new_snippet,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "catalog_version": self.catalog_version,
            "waiver_key": self.waiver_key,
        }


@dataclass(frozen=True, slots=True)
class WaivedFinding:
    finding: Finding
    reason: str
    waiver_index: int

    def to_dict(self) -> dict[str, Any]:
        return {**self.finding.to_dict(), "waived": True, "waiver_reason": self.reason,
                "waiver_index": self.waiver_index}


@dataclass(frozen=True, slots=True)
class Unanalyzable:
    """A file (or one side of it) the engine could not analyse; never raises."""

    path: str
    side: str  # base | head | both
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "side": self.side, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class TamperReport:
    catalog_version: str = CATALOG_VERSION
    findings: tuple[Finding, ...] = ()
    waived: tuple[WaivedFinding, ...] = ()
    unanalyzable: tuple[Unanalyzable, ...] = ()
    rules_run: tuple[str, ...] = ()
    rule_errors: tuple[str, ...] = ()
    truncated: bool = False
    notes: tuple[str, ...] = ()
    config_digest: str = ""

    @property
    def max_severity(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)

    @property
    def counts(self) -> dict[str, Any]:
        by_rule: dict[str, int] = {}
        by_sev: dict[str, int] = {}
        for f in self.findings:
            by_rule[f.rule_id] = by_rule.get(f.rule_id, 0) + 1
            by_sev[f.severity.label] = by_sev.get(f.severity.label, 0) + 1
        return {
            "findings": len(self.findings),
            "waived": len(self.waived),
            "unanalyzable": len(self.unanalyzable),
            "by_rule": dict(sorted(by_rule.items())),
            "by_severity": dict(sorted(by_sev.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "config_digest": self.config_digest,
            "truncated": self.truncated,
            "notes": list(self.notes),
            "counts": self.counts,
            "rules_run": list(self.rules_run),
            "rule_errors": list(self.rule_errors),
            "findings": [f.to_dict() for f in self.findings],
            "waived": [w.to_dict() for w in self.waived],
            "unanalyzable": [u.to_dict() for u in self.unanalyzable],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


@dataclass(slots=True)
class CheckSpec:
    """Documentation and default severity of one rule check (variant)."""

    severity: Severity
    description: str


@dataclass(slots=True)
class RuleDoc:
    title: str
    rationale: str
    example_before: str
    example_after: str
    limitations: str
    maps_to: str = ""  # DESIGN.md catalog id this rule implements (or "extension")
