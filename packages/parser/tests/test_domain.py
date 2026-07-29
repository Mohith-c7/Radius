"""Parser domain tests."""

import pytest
from radius_parser.domain import (
    ExportReference,
    FileChecksum,
    ImportReference,
    SourceLocation,
    SourcePath,
    SymbolName,
)


def test_source_path_rejects_empty_and_absolute_values() -> None:
    with pytest.raises(ValueError, match="Source path cannot be empty"):
        SourcePath("")

    with pytest.raises(ValueError, match="repository-relative"):
        SourcePath("/src/app.py")


def test_checksum_and_symbol_name_reject_empty_values() -> None:
    with pytest.raises(ValueError, match="File checksum cannot be empty"):
        FileChecksum(" ")

    with pytest.raises(ValueError, match="Symbol name cannot be empty"):
        SymbolName("")


def test_source_location_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="start line must be positive"):
        SourceLocation(start_line=0)

    with pytest.raises(ValueError, match="end line cannot precede"):
        SourceLocation(start_line=10, end_line=9)


def test_import_and_export_references_reject_empty_values() -> None:
    with pytest.raises(ValueError, match="Import source cannot be empty"):
        ImportReference(source="")

    with pytest.raises(ValueError, match="Export name cannot be empty"):
        ExportReference(name=" ")
