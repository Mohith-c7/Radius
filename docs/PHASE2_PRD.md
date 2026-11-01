# Product Requirements Document (PRD)
**Project:** Radius - AI-Native Software Verification Platform
**Phase:** 2 - Semantic Repository Intelligence
**Status:** DRAFT
**Date:** September 2026

## 1. Executive Summary
Standard software verification tools rely on deterministic, file-level dependency graphs which cause "Blast Radius Explosion"—flagging unaffected downstream code due to brittle `import` tracking. Radius Phase 2 aims to solve this by introducing **Semantic Code Property Graph (CPG) Slicing**. By combining deterministic `tree-sitter` structural parsing with targeted AI (LLM) semantic evaluation, Radius will deeply understand repository structure, isolate precise execution paths, and dynamically prune false positives from the blast radius.

## 2. Objectives & Goals
* **Absolute Precision:** Extract granular symbols (Classes, Methods, Functions, Variables) instead of just files.
* **Semantic Awareness:** Determine not just *if* Function A calls Function B, but *whether* a change in Function B semantically breaks Function A.
* **Performance:** Achieve sub-second structural parsing using native `tree-sitter` bindings. Keep LLM latency low by feeding it only micro-slices (50-100 lines) of code.
* **Robustness:** Ensure backward compatibility with Phase 1. The new intelligence engine must plug into the existing background worker seamlessly.

## 3. Scope & Non-Goals
**In Scope for Phase 2:**
* Integration of `tree-sitter` for Python and TypeScript.
* AST (Abstract Syntax Tree) traversal and Symbol extraction logic.
* In-memory construction of the Code Property Graph (Nodes = Symbols, Edges = Calls/Imports).
* LLM Prompt Engineering for Semantic Pruning (The Proof of Concept).
* End-to-end integration test of the pipeline.

**Out of Scope (Deferred to Phase 3/4):**
* Distributed graph persistence (e.g., Neo4j).
* Automated Test Execution based on the pruned graph (Phase 5).
* Advanced cross-repository graph resolution.

## 4. Functional Requirements
### 4.1. Structural Parsing Engine
* **FR1:** The system MUST parse raw source files into an AST using `tree-sitter` without regular expressions.
* **FR2:** The system MUST identify and extract all declared functions, classes, and methods as discrete entities.
* **FR3:** The system MUST identify all outgoing call expressions (e.g., `db.query()`) and resolve them to their imported origins.

### 4.2. Graph Construction
* **FR4:** The system MUST construct a directed graph representing execution flow between extracted symbols.
* **FR5:** The system MUST be capable of extracting a "Caller Subgraph" (Slice) given a modified target symbol.

### 4.3. Semantic Pruner (AI)
* **FR6:** The system MUST format a sliced execution path (Caller Source + Callee Diff) into an optimized LLM prompt.
* **FR7:** The system MUST parse the LLM's JSON response to determine if the edge should be kept (`impacted: true`) or pruned (`impacted: false`).

## 5. Technical Architecture
1. **`packages/parser`**: New module wrapping `tree-sitter`. Handles language-specific grammars and standardizes the output into a unified `Symbol` schema.
2. **`packages/graph`**: New module utilizing `networkx` (or custom dicts) to stitch `Symbol`s together across file boundaries.
3. **`packages/analysis`**: Updated to orchestrate the pipeline: `Fetch PR Diff -> Identify Changed Symbols -> Extract Slice -> Invoke LLM Pruner`.

## 6. Risks & Mitigations
* **Risk:** LLM Hallucinations causing a true-positive to be pruned (False Negative).
  * *Mitigation:* Strict prompt engineering requiring the LLM to output "chain of thought" reasoning before concluding. Default to `impacted: true` if the LLM fails to parse or is uncertain.
* **Risk:** `tree-sitter` language grammar drift.
  * *Mitigation:* Pin exact versions of `tree-sitter-python` and `tree-sitter-typescript` in dependencies.

## 7. Success Metrics
* **Accuracy:** 0% False Negatives (no broken code missed) on a benchmark test set.
* **Efficiency:** > 40% reduction in Blast Radius size compared to naive file-level tracking.
* **Latency:** < 2 seconds for AST extraction per medium-sized repository.
