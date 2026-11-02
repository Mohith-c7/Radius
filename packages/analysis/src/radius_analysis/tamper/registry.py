"""Rule registry and the shipped catalog ``tamper-rules-v1``."""

from __future__ import annotations

import re
from collections.abc import Iterable

from radius_analysis.tamper.config import TamperConfig
from radius_analysis.tamper.model import CATALOG_VERSION
from radius_analysis.tamper.rules.assertions import (
    AssertionRemoved,
    AssertionWeakened,
    ExpectedValueChanged,
    Tautology,
)
from radius_analysis.tamper.rules.base import TamperRule
from radius_analysis.tamper.rules.code_quality import (
    DebugArtifactRule,
    SecurityDowngradeRule,
    StubbedImplementationRule,
    SuppressionRule,
)
from radius_analysis.tamper.rules.config_weakening import (
    CiWeakeningRule,
    CoverageSuppressionRule,
    RetryRule,
)
from radius_analysis.tamper.rules.dependencies import DependencyRule
from radius_analysis.tamper.rules.disabling import DeletedTestRule, SkippedTestRule
from radius_analysis.tamper.rules.exceptions import ExceptionSwallowRule
from radius_analysis.tamper.rules.fixtures import FixtureTamperRule
from radius_analysis.tamper.rules.mocks import MockedSutRule

_ID = re.compile(r"^T\d{3}$")


class RuleRegistry:
    """Holds rules by id; enabling and severity live in :class:`TamperConfig`."""

    def __init__(self, rules: Iterable[TamperRule] = ()) -> None:
        self._rules: dict[str, TamperRule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: TamperRule) -> None:
        if not _ID.match(rule.id):
            raise ValueError(f"invalid rule id {rule.id!r} (expected T###)")
        if rule.id in self._rules:
            raise ValueError(f"duplicate rule id {rule.id}")
        if not rule.checks:
            raise ValueError(f"rule {rule.id} declares no checks")
        self._rules[rule.id] = rule

    def get(self, rule_id: str) -> TamperRule:
        return self._rules[rule_id]

    def ids(self) -> frozenset[str]:
        return frozenset(self._rules)

    def all(self) -> list[TamperRule]:
        return [self._rules[k] for k in sorted(self._rules)]

    def enabled(self, config: TamperConfig) -> list[TamperRule]:
        return [r for r in self.all() if config.is_enabled(r.id)]

    @property
    def catalog_version(self) -> str:
        return CATALOG_VERSION


def default_registry() -> RuleRegistry:
    """A fresh registry with every v1 rule."""
    return RuleRegistry(
        [
            DeletedTestRule(),
            SkippedTestRule(),
            AssertionRemoved(),
            AssertionWeakened(),
            Tautology(),
            ExpectedValueChanged(),
            ExceptionSwallowRule(),
            MockedSutRule(),
            CoverageSuppressionRule(),
            CiWeakeningRule(),
            RetryRule(),
            DependencyRule(),
            SuppressionRule(),
            StubbedImplementationRule(),
            SecurityDowngradeRule(),
            DebugArtifactRule(),
            FixtureTamperRule(),
        ]
    )


def catalog_markdown(registry: RuleRegistry | None = None) -> str:
    """The rule table used by ``docs/evidence/TAMPER_RULES.md`` (kept in sync by a test)."""
    registry = registry or default_registry()
    lines = [
        "| Id | Family | Title | Checks (default severity) | Maps to |",
        "|---|---|---|---|---|",
    ]
    for r in registry.all():
        checks = ", ".join(f"`{k}` ({v.severity.label})" for k, v in r.checks.items())
        lines.append(f"| {r.id} | {r.family} | {r.doc.title} | {checks} | {r.doc.maps_to} |")
    return "\n".join(lines) + "\n"
