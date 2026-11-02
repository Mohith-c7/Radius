"""Tamper rule engine (EV-02): deterministic detection of changes that weaken verification.

Public surface: :func:`analyze_tampering`, :class:`TamperConfig`, :class:`TamperReport`,
:class:`Finding`, :class:`Severity`, the rule registry and the catalog version.
"""

from radius_analysis.tamper.config import (
    Params,
    TamperConfig,
    TamperConfigError,
    Waiver,
)
from radius_analysis.tamper.model import (
    CATALOG_VERSION,
    Family,
    Finding,
    Severity,
    TamperReport,
    Unanalyzable,
    WaivedFinding,
)
from radius_analysis.tamper.registry import (
    RuleRegistry,
    catalog_markdown,
    default_registry,
)
from radius_analysis.tamper.rules.base import BaseRule, TamperRule
from radius_analysis.tamper.service import StaticPackageRegistry, analyze_tampering

__all__ = [
    "CATALOG_VERSION",
    "BaseRule",
    "Family",
    "Finding",
    "Params",
    "RuleRegistry",
    "Severity",
    "StaticPackageRegistry",
    "TamperConfig",
    "TamperConfigError",
    "TamperReport",
    "TamperRule",
    "Unanalyzable",
    "Waiver",
    "WaivedFinding",
    "analyze_tampering",
    "catalog_markdown",
    "default_registry",
]
