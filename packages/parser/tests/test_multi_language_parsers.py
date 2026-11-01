"""Multi-language parser test suite for Go, Java, and Rust."""

from pathlib import Path
from tempfile import TemporaryDirectory

from radius_parser.core import ParserEngine
from radius_parser.domain.entities import SourceFile
from radius_parser.domain.enums import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.domain.value_objects import FileChecksum, SourcePath
from radius_parser.infrastructure.filesystem_discovery import FilesystemSourceDiscovery
from radius_parser.infrastructure.parser_registry import (
    default_language_parser_registry,
)
from radius_parser.infrastructure.tree_sitter_parsers import (
    GoLanguageParser,
    JavaLanguageParser,
    RustLanguageParser,
)


def test_parser_engine_go_java_rust_support() -> None:
    """Verify ParserEngine parses Go, Java, and Rust source code."""
    engine = ParserEngine()

    go_tree = engine.parse_go("package main\nfunc Hello() string { return \"hello\" }")
    assert go_tree.root_node.type == "source_file"

    java_tree = engine.parse_java("public class App { public static void main(String[] args) {} }")
    assert java_tree.root_node.type == "program"

    rust_tree = engine.parse_rust("pub fn add(a: i32, b: i32) -> i32 { a + b }")
    assert rust_tree.root_node.type == "source_file"


def test_go_extractor_and_language_parser() -> None:
    """Verify Go extractor and GoLanguageParser on structs, methods, and functions."""
    source_code = """package server

import (
    "fmt"
    "net/http"
)

type Config struct {
    Port int
}

type Handler interface {
    Handle(w http.ResponseWriter, r *http.Request)
}

func NewConfig(port int) *Config {
    return &Config{Port: port}
}

func (c *Config) Validate() bool {
    fmt.Println(c.Port)
    return c.Port > 0
}
"""
    with TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "server.go"
        file_path.write_text(source_code, encoding="utf-8")

        source_file = SourceFile(
            path=SourcePath("server.go"),
            language=SourceLanguage.GO,
            checksum=FileChecksum("abc123go"),
            absolute_path=file_path,
        )

        parser = GoLanguageParser()
        parsed = parser.parse(source_file)

        symbol_names = {s.name.value: s for s in parsed.symbols}
        assert "Config" in symbol_names
        assert symbol_names["Config"].symbol_type == SymbolType.STRUCT
        assert symbol_names["Config"].visibility == SymbolVisibility.PUBLIC

        assert "Handler" in symbol_names
        assert symbol_names["Handler"].symbol_type == SymbolType.INTERFACE
        assert symbol_names["Handler"].visibility == SymbolVisibility.PUBLIC

        assert "NewConfig" in symbol_names
        assert symbol_names["NewConfig"].symbol_type == SymbolType.FUNCTION
        assert symbol_names["NewConfig"].visibility == SymbolVisibility.PUBLIC

        assert "Config.Validate" in symbol_names
        assert symbol_names["Config.Validate"].symbol_type == SymbolType.METHOD
        assert symbol_names["Config.Validate"].visibility == SymbolVisibility.PUBLIC

        # Check imports
        import_sources = [imp.source for imp in parsed.imports]
        assert "fmt" in import_sources
        assert "net/http" in import_sources


def test_java_extractor_and_language_parser() -> None:
    """Verify Java extractor and JavaLanguageParser on classes, interfaces, and methods."""
    source_code = """package com.example.service;

import java.util.List;
import java.io.IOException;

public interface PaymentService {
    void processPayment(double amount) throws IOException;
}

public class StripePaymentService implements PaymentService {
    public StripePaymentService() {}

    public void processPayment(double amount) {
        logPayment(amount);
    }

    private void logPayment(double amount) {}
}
"""
    with TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "Payment.java"
        file_path.write_text(source_code, encoding="utf-8")

        source_file = SourceFile(
            path=SourcePath("Payment.java"),
            language=SourceLanguage.JAVA,
            checksum=FileChecksum("abc123java"),
            absolute_path=file_path,
        )

        parser = JavaLanguageParser()
        parsed = parser.parse(source_file)

        symbol_names = {s.name.value: s for s in parsed.symbols}
        assert "PaymentService" in symbol_names
        assert symbol_names["PaymentService"].symbol_type == SymbolType.INTERFACE

        assert "StripePaymentService" in symbol_names
        assert symbol_names["StripePaymentService"].symbol_type == SymbolType.CLASS

        assert "StripePaymentService.processPayment" in symbol_names
        assert symbol_names["StripePaymentService.processPayment"].symbol_type == SymbolType.METHOD

        import_sources = [imp.source for imp in parsed.imports]
        assert "java.util.List" in import_sources
        assert "java.io.IOException" in import_sources


def test_rust_extractor_and_language_parser() -> None:
    """Verify Rust extractor and RustLanguageParser on structs, enums, traits, and impl methods."""
    source_code = """use std::collections::HashMap;

pub enum Status {
    Active,
    Inactive,
}

pub trait Processor {
    fn process(&self);
}

pub struct Engine {
    pub id: u64,
}

impl Engine {
    pub fn new(id: u64) -> Self {
        Engine { id }
    }

    fn internal_step(&self) {}
}

pub fn run_engine(engine: &Engine) {
    engine.internal_step();
}
"""
    with TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "engine.rs"
        file_path.write_text(source_code, encoding="utf-8")

        source_file = SourceFile(
            path=SourcePath("engine.rs"),
            language=SourceLanguage.RUST,
            checksum=FileChecksum("abc123rust"),
            absolute_path=file_path,
        )

        parser = RustLanguageParser()
        parsed = parser.parse(source_file)

        symbol_names = {s.name.value: s for s in parsed.symbols}
        assert "Status" in symbol_names
        assert symbol_names["Status"].symbol_type == SymbolType.ENUM
        assert symbol_names["Status"].visibility == SymbolVisibility.PUBLIC

        assert "Processor" in symbol_names
        assert symbol_names["Processor"].symbol_type == SymbolType.TRAIT
        assert symbol_names["Processor"].visibility == SymbolVisibility.PUBLIC

        assert "Engine" in symbol_names
        assert symbol_names["Engine"].symbol_type == SymbolType.STRUCT
        assert symbol_names["Engine"].visibility == SymbolVisibility.PUBLIC

        assert "Engine.new" in symbol_names
        assert symbol_names["Engine.new"].symbol_type == SymbolType.METHOD
        assert symbol_names["Engine.new"].visibility == SymbolVisibility.PUBLIC

        assert "run_engine" in symbol_names
        assert symbol_names["run_engine"].symbol_type == SymbolType.FUNCTION
        assert symbol_names["run_engine"].visibility == SymbolVisibility.PUBLIC

        import_sources = [imp.source for imp in parsed.imports]
        assert any("HashMap" in src for src in import_sources)


def test_default_registry_includes_all_languages() -> None:
    """Verify default_language_parser_registry supports Python, TS, JS, Go, Java, Rust."""
    registry = default_language_parser_registry()

    assert registry.get_parser(SourceLanguage.PYTHON) is not None
    assert registry.get_parser(SourceLanguage.TYPESCRIPT) is not None
    assert registry.get_parser(SourceLanguage.JAVASCRIPT) is not None
    assert registry.get_parser(SourceLanguage.GO) is not None
    assert registry.get_parser(SourceLanguage.JAVA) is not None
    assert registry.get_parser(SourceLanguage.RUST) is not None


def test_filesystem_discovery_supports_go_java_rust() -> None:
    """Verify FilesystemSourceDiscovery detects .go, .java, and .rs files."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.go").write_text("package main", encoding="utf-8")
        (root / "App.java").write_text("class App {}", encoding="utf-8")
        (root / "lib.rs").write_text("fn lib() {}", encoding="utf-8")

        discovery = FilesystemSourceDiscovery()
        discovered = discovery.discover(root)

        languages = {f.language for f in discovered}
        assert SourceLanguage.GO in languages
        assert SourceLanguage.JAVA in languages
        assert SourceLanguage.RUST in languages
