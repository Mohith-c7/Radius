"""Rule interface for the tamper engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc

if TYPE_CHECKING:
    from radius_analysis.tamper.context import TamperContext


@runtime_checkable
class TamperRule(Protocol):
    """A deterministic rule: ``evaluate(context)`` returns findings, never raises on bad input."""

    id: str
    family: Family
    languages: frozenset[str]
    checks: Mapping[str, CheckSpec]
    doc: RuleDoc

    def evaluate(self, context: TamperContext) -> list[Finding]: ...


class BaseRule:
    """Convenience base: subclasses set the class attributes and implement ``evaluate``."""

    id: ClassVar[str]
    family: ClassVar[Family]
    languages: ClassVar[frozenset[str]] = frozenset({"python"})
    checks: ClassVar[Mapping[str, CheckSpec]]
    doc: ClassVar[RuleDoc]

    def evaluate(self, context: TamperContext) -> list[Finding]:  # pragma: no cover
        raise NotImplementedError
