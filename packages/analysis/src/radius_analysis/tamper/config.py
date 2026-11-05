"""Tamper-engine configuration: rule switches, severity overrides, params, waivers.

Severities shipped as defaults are the *assumed* values the F-14 fixtures carry
(``assumed_severity``); they stay configuration until the EV-02 owner decision
fixes them (see the README).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from radius_analysis.tamper.model import CATALOG_VERSION, Severity


class TamperConfigError(ValueError):
    """The configuration is malformed."""


@dataclass(frozen=True, slots=True)
class Waiver:
    """Accepts a finding by stable ``finding_id`` or by ``rule`` + ``path`` glob."""

    reason: str
    finding_id: str | None = None
    rule: str | None = None
    path: str | None = None
    approved_by: str | None = None

    def matches(self, finding_id: str, rule_id: str, check: str, path: str) -> bool:
        if self.finding_id is not None:
            return self.finding_id == finding_id
        if self.rule is None or self.rule not in (rule_id, f"{rule_id}:{check}"):
            return False
        return self.path is None or fnmatch.fnmatchcase(path, self.path)


@dataclass(frozen=True, slots=True)
class Params:
    min_added_suppressions: int = 1
    max_findings: int = 500
    max_files: int = 2000
    max_file_bytes: int = 1_000_000
    time_budget_seconds: float = 30.0
    typosquat_max_distance: int = 1
    use_registry: bool = False  # only effective when a registry port is injected

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Params:
        unknown = sorted(set(data) - set(cls.__dataclass_fields__))
        if unknown:
            raise TamperConfigError(f"unknown params: {unknown}")
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class TamperConfig:
    catalog_version: str = CATALOG_VERSION
    disabled_rules: frozenset[str] = frozenset()
    enabled_rules: frozenset[str] | None = None  # None = every rule not disabled
    severity_overrides: Mapping[str, Severity] = field(default_factory=dict)
    params: Params = field(default_factory=Params)
    waivers: tuple[Waiver, ...] = ()

    def is_enabled(self, rule_id: str) -> bool:
        if rule_id in self.disabled_rules:
            return False
        return self.enabled_rules is None or rule_id in self.enabled_rules

    def severity_for(self, rule_id: str, check: str, default: Severity) -> Severity:
        """Most specific override wins: ``T012:check``, then ``T012``, then the default."""
        return self.severity_overrides.get(
            f"{rule_id}:{check}", self.severity_overrides.get(rule_id, default)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "disabled_rules": sorted(self.disabled_rules),
            "enabled_rules": None if self.enabled_rules is None else sorted(self.enabled_rules),
            "severity_overrides": {k: v.label for k, v in sorted(self.severity_overrides.items())},
            "params": {k: getattr(self.params, k) for k in Params.__dataclass_fields__},
            "waivers": [
                {k: getattr(w, k) for k in Waiver.__dataclass_fields__ if getattr(w, k) is not None}
                for w in self.waivers
            ],
        }

    def digest(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, known_rules: frozenset[str] | None = None
    ) -> TamperConfig:
        """Parse the JSON shape documented in the README; raises :class:`TamperConfigError`."""
        if not isinstance(data, Mapping):
            raise TamperConfigError("config must be a JSON object")
        version = data.get("catalog_version", CATALOG_VERSION)
        if version != CATALOG_VERSION:
            raise TamperConfigError(f"unsupported catalog_version {version!r}")
        disabled: set[str] = set(data.get("disable", []))
        enabled_only = data.get("enable_only")
        overrides: dict[str, Severity] = {}
        for key, spec in (data.get("rules") or {}).items():
            if not isinstance(spec, Mapping):
                raise TamperConfigError(f"rules[{key!r}] must be an object")
            if spec.get("enabled") is False:
                disabled.add(key)
            if "severity" in spec:
                try:
                    overrides[key] = Severity.parse(spec["severity"])
                except ValueError as exc:
                    raise TamperConfigError(str(exc)) from exc
        if known_rules is not None:
            names = disabled | set(enabled_only or []) | {k.split(":")[0] for k in overrides}
            unknown = sorted(n for n in names if n not in known_rules)
            if unknown:
                raise TamperConfigError(f"unknown rule ids: {unknown}")
        waivers = []
        for i, w in enumerate(data.get("waivers", [])):
            if not isinstance(w, Mapping) or not w.get("reason"):
                raise TamperConfigError(f"waivers[{i}] needs a non-empty reason")
            if not (w.get("finding_id") or w.get("rule")):
                raise TamperConfigError(f"waivers[{i}] needs finding_id or rule")
            waivers.append(
                Waiver(
                    reason=str(w["reason"]),
                    finding_id=w.get("finding_id"),
                    rule=w.get("rule"),
                    path=w.get("path"),
                    approved_by=w.get("approved_by"),
                )
            )
        return cls(
            catalog_version=version,
            disabled_rules=frozenset(disabled),
            enabled_rules=None if enabled_only is None else frozenset(enabled_only),
            severity_overrides=overrides,
            params=Params.from_dict(data.get("params") or {}),
            waivers=tuple(waivers),
        )

    @classmethod
    def from_json_file(
        cls, path: Path | str, *, known_rules: frozenset[str] | None = None
    ) -> TamperConfig:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TamperConfigError(f"cannot read tamper config {path}: {exc}") from exc
        return cls.from_dict(data, known_rules=known_rules)
