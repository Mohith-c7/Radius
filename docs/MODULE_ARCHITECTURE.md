# 05_Module_Architecture.md

# Module Architecture

Project: Radius

Version: 1.0

---

# Overview

Radius is composed of independent modules.

Each module owns a single business capability.

Modules communicate through contracts rather than implementation details.

A module may depend on shared abstractions but should never directly depend on another module's internal implementation.

This architecture allows the platform to evolve without tightly coupling different parts of the system.

---

# Module Hierarchy

Radius consists of the following domains.

Repository Domain

↓

Parser Domain

↓

Graph Domain

↓

Analysis Domain

↓

Testing Domain

↓

Confidence Domain

↓

Presentation Domain

Each domain contains one or more modules.

---

# Repository Domain

## Purpose

The Repository Domain is responsible for interacting with source code repositories.

It acts as the gateway between GitHub and the internal Radius pipeline.

No business logic should exist inside this domain.

---

## Responsibilities

Receive GitHub webhooks

Clone repositories

Fetch updates

Checkout branches

Manage repository cache

Provide repository snapshots

---

## Inputs

GitHub Events

Repository URLs

Authentication Tokens

---

## Outputs

Repository Snapshot

Commit Information

Pull Request Information

Repository Metadata

---

## Modules

github

repository

git

---

## Non Responsibilities

Repository analysis

Dependency computation

Parsing

Testing

Confidence scoring

---

# Parser Domain

## Purpose

Convert source code into structured semantic information.

The parser should understand code but never interpret business meaning.

---

## Responsibilities

Parse source files

Extract symbols

Extract imports

Extract exports

Extract functions

Extract classes

Extract interfaces

Extract methods

### Language support (DEC-017)

| Language | Parser | Import resolution | Status |
| --- | --- | --- | --- |
| Python | stdlib `ast` | yes (absolute, relative, src-layout, `from pkg import mod`) | supported |
| TypeScript / JavaScript (`.ts .tsx .mts .cts .js .jsx .mjs .cjs`) | tree-sitter (`tree-sitter-typescript`, `tree-sitter-javascript`) | yes: relative with extension/index resolution, `tsconfig` `baseUrl` + `paths`, nearest tsconfig per file, `extends` chains | supported |
| Go, Java, Rust | tree-sitter | none (no dependency edges) | **experimental** |

A JS/TS file with syntax errors is reported in `parse_failures`, like a Python
file. Bare package imports and unresolvable aliases are classified external.
Not resolved: package `exports`, workspace package names, computed specifiers.
The parser registry flags Go/Java/Rust (`EXPERIMENTAL_LANGUAGES`), and
`RepositoryParseResult.experimental_languages` plus a warning log record when
they were used.

Extract annotations

Generate normalized metadata

---

## Inputs

Repository Snapshot

Changed Files

---

## Outputs

AST

Symbol Table

Import Table

Export Table

Metadata

---

## Internal Modules

parser

language

ast

metadata

---

## Non Responsibilities

Dependency analysis

Graph traversal

Blast radius

Testing

---

# Graph Domain

## Purpose

Represent repository relationships.

The graph becomes the knowledge base of Radius.

---

## Responsibilities

Create graph

Update graph

Delete graph nodes

Resolve dependencies

Resolve references

Reverse lookup

Traversal

---

## Graph Types

File Graph

Module Graph

Package Graph

Symbol Graph

Future

Service Graph

API Graph

Database Graph

---

## Inputs

Repository Metadata

Parser Output

---

## Outputs

Repository Graph

Dependency Graph

Relationship Graph

---

## Internal Modules

graph

resolver

traversal

storage

---

## Non Responsibilities

Parsing

Testing

Confidence

Git operations

---

# Analysis Domain

Purpose

Understand software changes.

---

Modules

Git Change Analyzer

Blast Radius Engine

Risk Engine

---

Responsibilities

Read git diff

Compute changed symbols

Compute impacted nodes

Compute dependency depth

Compute affected modules

Generate impact report

---

Inputs

Git Changes

Repository Graph

---

Outputs

Blast Radius

Impact Report

Risk Factors

---

Non Responsibilities

Execute tests

Generate reports

Dashboard

---

# Testing Domain

Purpose

Validate repository changes.

---

Modules

Test Discovery

Test Selection

Test Runner

Coverage Collector

---

Responsibilities

Discover tests

Map tests

Execute tests

Collect coverage

Generate execution report

---

Outputs

Test Results

Coverage

Logs

Metrics

---

Future

AI Test Generation

Mutation Testing

Benchmark Testing

Security Testing

---

## Symbol-level impact (F-08)

Behind `RADIUS_FEATURE_SYMBOL_IMPACT` (default `false`, worker setting
`symbol_impact_enabled`). When enabled, the worker narrows the file-level
"files that import the changed file" set to "files containing code that can
reach the changed symbols", for Python only.

Pipeline (all deterministic, algo version `symbol-impact-v1`):

1. `radius_analysis.diff_hunks.parse_diff_line_changes` splits a diff into added
   lines, deletion points and deleted text.
2. `radius_graph.symbol_impact.PythonSymbolGraph` (stdlib `ast`) indexes
   functions, methods, classes and one `<module>` pseudo-symbol per file, and
   maps changed lines to symbols. A reference is a bare name (`Name`,
   `Attribute.attr`, parameter names, dotted string constants such as
   `mock.patch("pkg.mod.f")`); names bound by `import x as y` or `y = x` are
   merged. A symbol is used by every symbol that mentions its name anywhere in
   the repository, which over-approximates real call edges.
3. `radius_analysis.symbol_impact.refine_dependents` runs reverse reachability
   per changed file and intersects the result with the file-level dependents
   (plus tests below a `conftest.py` that depends on the file), so selection is
   a subset of the file-level selection. It also records reason tags.
4. The refined dependents feed the unchanged `map_changes_to_tests` and
   `PathBasedTestSelector` and the blast radius (`symbol_affected_file_paths`).
   Naming-convention matches and changed test files are kept.

Reason tags appear in each test's selection decision (`evidence_sources`
contains `SYMBOL_IMPACT`; `evidence_details` holds
`symbol impact: tests/test_a.py::test_x -> pkg/b.py::g -> pkg/a.py::f (changed)`
or `file-level fallback for <path>: <reason>`).

Safe fallbacks (the changed file keeps its file-level result): non-Python file;
no hunks or unparseable file; module-level code changed; a `def`/`class`/
decorator line deleted; unmodelled class-body statement; an implicit protocol
method (dunder other than `__init__`) changed or reached. If dynamic code
(`importlib.import_module`, `__import__`, `eval`, `exec`, `globals()`,
non-constant `getattr`) is reachable from a test, every changed file keeps its
file-level set and additionally selects each test that contains or reaches that
code (this is the one case where selection can exceed file-level). The
full-suite triggers (`conftest.py`, manifests, deleted/renamed files) are
unchanged and run before any symbol logic.

Known limits: name-based matching is not type-aware (more tests than necessary
for common method names); behaviour wired through entry points, plugin
registries loaded by string from config, or `exec`-style code outside the repo
snapshot is invisible; TypeScript/JavaScript have no symbol-level path yet.
Validation: `tests/test_symbol_impact_ground_truth.py` compares selection with
tests that dynamically execute the changed lines (`sys.settrace`).

---

## Symbol-level change extraction (LK-01)

Behind `RADIUS_FEATURE_SYMBOL_CHANGES` (default `false`, worker setting
`symbol_changes_enabled`). Lives in `packages/analysis`
(`radius_analysis.symbol_changes`), not in a new package: it reuses the F-09
tree-sitter grammars through `radius_parser.infrastructure.ecmascript_parser.parse_syntax_tree`
and leaves F-08 untouched (F-08 answers "who references this name"; LK-01 keeps the
per-definition fingerprints F-08 does not store).

Pipeline (deterministic, algo version `symbol-changes-v1`, no LLM, no network):

1. `diff_files.parse_unified_diff` parses the diff in both coordinate systems
   (renames/copies, new/deleted/binary/mode-only files, "No newline" markers, CRLF,
   quoted paths). Hunks are consumed by their header counts.
2. A `SnapshotReader` port supplies base and head content (`DictSnapshot`,
   `DirectorySnapshot`, `GitSnapshot`, or `DiffReversedSnapshot` which rebuilds the
   base from head + diff).
3. `index_python` (stdlib `ast`) and `index_ecmascript` (tree-sitter) list the
   definitions of each version with signature, decorators, docstring and a
   normalised own body.
4. Definitions are matched by (qualified name, kind); leftovers are paired by body
   similarity into `renamed` / `moved` / `moved_between_files`.
5. Every changed line is attributed to its innermost symbol or to an unattributed
   bucket; each touched symbol is classified (signature, body, decorator,
   docstring/comment, formatting).
6. Output: `SymbolChangeSet` (contract in `packages/analysis/README.md`).

Budgets: `max_files`, `max_file_bytes`, `max_diff_bytes`, `time_budget_seconds`,
`max_similarity_pairs`. Any per-file failure degrades to a file-level unit with a
recorded reason. The worker step only logs counts (nothing is persisted before
LK-05) and swallows failures.

CLI: `python -m radius_analysis.symbol_changes --repo . --base REF --head REF`.

---

# Confidence Domain

Purpose

Transform engineering evidence into an explainable confidence report.

---

Inputs

Blast Radius

Coverage

Test Results

Repository Metrics

---

Outputs

Confidence Score

Risk Summary

Evidence

Recommendations

---

Responsibilities

Aggregate evidence

Calculate confidence

Explain confidence

Generate report

---

Future

Historical learning

Predictive confidence

Adaptive scoring

---

# Intent Domain (research, DEC-007)

Package: `packages/intent` (import name `radius_intent`).

Purpose

Capture what a change is supposed to do as confirmable, testable criteria with provenance (DESIGN section 6.1, RQ1).

---

Inputs

Raw intent sources (PR title/body, issues, commits, spec file, agent prompt, comments), supplied through the `IntentSourceFetcher` port.

---

Outputs

`IntentSnapshot`: immutable, versioned, ordered `Criterion` set with `Provenance` and `Span` into each source; snapshot diffs by stable criterion id.

---

Responsibilities

Domain model and invariants only (IN-01). Ports: `IntentSourceFetcher`, `CriterionExtractor`, `TestabilityRater`. The domain layer imports only the standard library and itself (AST test plus import-linter contract).

---

Non Responsibilities

Persistence, HTTP, LLM calls, ingestion, extraction (IN-02 to IN-08).

---

# Presentation Domain

Purpose

Present Radius intelligence to developers.

---

Modules

Dashboard

REST API

GitHub Check

Notifications

---

Responsibilities

Display reports

Display graphs

Display history

Display recommendations

Manage repositories

---

Non Responsibilities

Analysis

Parsing

Testing

Confidence calculation

---

# Shared Domain

Purpose

Reusable utilities shared across all domains.

---

Modules

shared

logging

configuration

events

database

auth

cache

types

errors

constants

utils

---

Responsibilities

Configuration

Logging

Authentication

Validation

Error handling

Common interfaces

Shared DTOs

---

# Domain Dependencies

Repository

↓

Parser

↓

Graph

↓

Analysis

↓

Testing

↓

Confidence

↓

Presentation

Only downward dependencies are allowed.

No module may create circular dependencies.

---

# Communication Rules

Modules communicate using interfaces.

Modules never access another module's database tables directly.

Modules should expose services rather than implementation.

Shared types belong only inside the shared package.

---

# Extension Strategy

Future modules should be added without changing existing ones.

Examples

AI Test Generator

Security Scanner

CodeQL Analyzer

MCP Server

VS Code Extension

CLI

Slack Integration

All future capabilities should integrate through contracts.

---

# Module Ownership

Every module should satisfy one rule.

One module.

One responsibility.

One public interface.

This keeps Radius maintainable as the platform grows.

---

# Summary

The module architecture separates repository management, parsing, graph construction, analysis, testing, confidence evaluation, and presentation into independent domains.

This separation ensures maintainability, scalability, and extensibility while providing clear ownership boundaries for every component within Radius.