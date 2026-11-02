"""Tree-sitter backed language parsers for Go, Java, and Rust."""

from __future__ import annotations

from radius_parser.core import ParserEngine
from radius_parser.domain.entities import (
    ExportReference,
    ImportReference,
    ParsedSourceFile,
    SourceFile,
    Symbol,
)
from radius_parser.domain.enums import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.domain.value_objects import SourceLocation, SymbolName
from radius_parser.extractors.go import GoExtractor
from radius_parser.extractors.java import JavaExtractor
from radius_parser.extractors.rust import RustExtractor


class GoLanguageParser:
    """Extract symbols, imports, and exports from Go source files."""

    supported_language = SourceLanguage.GO
    experimental = True  # no import-to-file resolution; see DEC-017

    def __init__(self, engine: ParserEngine | None = None) -> None:
        self._engine = engine or ParserEngine()
        self._extractor = GoExtractor()

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        source = self._read_source(source_file)
        tree = self._engine.parse_go(source)
        file_path = source_file.path.value

        extracted_symbols = self._extractor.extract_symbols(
            tree.root_node, file_path, source
        )
        extracted_imports = self._extractor.extract_imports(
            tree.root_node, file_path, source
        )

        domain_symbols: list[Symbol] = []
        for s in extracted_symbols:
            stype = (
                SymbolType.STRUCT
                if s.type == "struct"
                else SymbolType.INTERFACE
                if s.type == "interface"
                else SymbolType.METHOD
                if s.type == "method"
                else SymbolType.FUNCTION
            )
            # In Go, capital first letter is exported/public
            base_name = s.name.split(".")[-1]
            vis = (
                SymbolVisibility.PUBLIC
                if base_name and base_name[0].isupper()
                else SymbolVisibility.PRIVATE
            )
            domain_symbols.append(
                Symbol(
                    name=SymbolName(s.name),
                    symbol_type=stype,
                    visibility=vis,
                    location=SourceLocation(start_line=s.start_line, end_line=s.end_line),
                )
            )

        imports = tuple(
            ImportReference(
                source=imp.module_path,
                location=SourceLocation(start_line=1),
            )
            for imp in extracted_imports
        )

        exports = tuple(
            ExportReference(
                name=s.name.value,
                location=s.location,
            )
            for s in domain_symbols
            if s.visibility == SymbolVisibility.PUBLIC
        )

        return ParsedSourceFile(
            source_file=source_file,
            symbols=tuple(domain_symbols),
            imports=imports,
            exports=exports,
        )

    @staticmethod
    def _read_source(source_file: SourceFile) -> str:
        if source_file.absolute_path is None:
            return ""
        return source_file.absolute_path.read_text(encoding="utf-8")


class JavaLanguageParser:
    """Extract symbols, imports, and exports from Java source files."""

    supported_language = SourceLanguage.JAVA
    experimental = True  # no import-to-file resolution; see DEC-017

    def __init__(self, engine: ParserEngine | None = None) -> None:
        self._engine = engine or ParserEngine()
        self._extractor = JavaExtractor()

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        source = self._read_source(source_file)
        tree = self._engine.parse_java(source)
        file_path = source_file.path.value

        extracted_symbols = self._extractor.extract_symbols(
            tree.root_node, file_path, source
        )
        extracted_imports = self._extractor.extract_imports(
            tree.root_node, file_path, source
        )

        domain_symbols: list[Symbol] = []
        for s in extracted_symbols:
            stype = (
                SymbolType.INTERFACE
                if s.type == "interface"
                else SymbolType.METHOD
                if s.type == "method"
                else SymbolType.CLASS
            )
            # Default Java visibility to public for top-level classes
            domain_symbols.append(
                Symbol(
                    name=SymbolName(s.name),
                    symbol_type=stype,
                    visibility=SymbolVisibility.PUBLIC,
                    location=SourceLocation(start_line=s.start_line, end_line=s.end_line),
                )
            )

        imports = tuple(
            ImportReference(
                source=imp.module_path,
                location=SourceLocation(start_line=1),
            )
            for imp in extracted_imports
        )

        exports = tuple(
            ExportReference(
                name=s.name.value,
                location=s.location,
            )
            for s in domain_symbols
            if s.visibility == SymbolVisibility.PUBLIC
        )

        return ParsedSourceFile(
            source_file=source_file,
            symbols=tuple(domain_symbols),
            imports=imports,
            exports=exports,
        )

    @staticmethod
    def _read_source(source_file: SourceFile) -> str:
        if source_file.absolute_path is None:
            return ""
        return source_file.absolute_path.read_text(encoding="utf-8")


class RustLanguageParser:
    """Extract symbols, imports, and exports from Rust source files."""

    supported_language = SourceLanguage.RUST
    experimental = True  # no import-to-file resolution; see DEC-017

    def __init__(self, engine: ParserEngine | None = None) -> None:
        self._engine = engine or ParserEngine()
        self._extractor = RustExtractor()

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        source = self._read_source(source_file)
        tree = self._engine.parse_rust(source)
        file_path = source_file.path.value

        extracted_symbols = self._extractor.extract_symbols(
            tree.root_node, file_path, source
        )
        extracted_imports = self._extractor.extract_imports(
            tree.root_node, file_path, source
        )

        domain_symbols: list[Symbol] = []
        for s in extracted_symbols:
            stype = (
                SymbolType.STRUCT
                if s.type == "struct"
                else SymbolType.ENUM
                if s.type == "enum"
                else SymbolType.TRAIT
                if s.type == "trait"
                else SymbolType.METHOD
                if s.type == "method"
                else SymbolType.FUNCTION
            )
            # Check pub keyword in source
            is_pub = "pub " in s.source_code[:12]
            vis = SymbolVisibility.PUBLIC if is_pub else SymbolVisibility.PRIVATE

            domain_symbols.append(
                Symbol(
                    name=SymbolName(s.name),
                    symbol_type=stype,
                    visibility=vis,
                    location=SourceLocation(start_line=s.start_line, end_line=s.end_line),
                )
            )

        imports = tuple(
            ImportReference(
                source=imp.module_path,
                location=SourceLocation(start_line=1),
            )
            for imp in extracted_imports
        )

        exports = tuple(
            ExportReference(
                name=s.name.value,
                location=s.location,
            )
            for s in domain_symbols
            if s.visibility == SymbolVisibility.PUBLIC
        )

        return ParsedSourceFile(
            source_file=source_file,
            symbols=tuple(domain_symbols),
            imports=imports,
            exports=exports,
        )

    @staticmethod
    def _read_source(source_file: SourceFile) -> str:
        if source_file.absolute_path is None:
            return ""
        return source_file.absolute_path.read_text(encoding="utf-8")
