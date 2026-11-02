"""Symbol-to-test linking (LK-03): static, naming and dynamic-coverage linkers.

The semantic (embedding) linker is deferred. See ``README.md`` in this directory.
"""

from radius_testing.linking.combine import combine_links, combined_score
from radius_testing.linking.coveragedb import (
    CoverageData,
    CoverageDataError,
    read_coverage_bytes,
    read_coverage_file,
)
from radius_testing.linking.dynamic import (
    FEATURE_FLAG,
    DynamicCoverageLinker,
    DynamicResult,
    SandboxRequiredError,
    UnsafeTestPathError,
    coverage_contexts_enabled,
    links_from_coverage,
)
from radius_testing.linking.model import (
    LinkComponent,
    LinkKind,
    LinkSet,
    LinkTarget,
    SymbolTestLink,
    normalize_test_id,
)
from radius_testing.linking.naming import NamingLinker
from radius_testing.linking.static import StaticLinker

__all__ = [
    "FEATURE_FLAG",
    "CoverageData",
    "CoverageDataError",
    "DynamicCoverageLinker",
    "DynamicResult",
    "LinkComponent",
    "LinkKind",
    "LinkSet",
    "LinkTarget",
    "NamingLinker",
    "SandboxRequiredError",
    "StaticLinker",
    "SymbolTestLink",
    "UnsafeTestPathError",
    "combine_links",
    "combined_score",
    "coverage_contexts_enabled",
    "links_from_coverage",
    "normalize_test_id",
    "read_coverage_bytes",
    "read_coverage_file",
]
