# Phase 2: Semantic CPG Slicing (Research POC)

## 1. Abstract and Motivation
Current state-of-the-art software verification and CI/CD optimization tools rely heavily on deterministic Dependency Graphs (often mapping file-to-file relationships). While effective for finding linked components, these models suffer from **Blast Radius Explosion**—a high rate of false positives where unaffected files and tests are erroneously flagged for execution simply because an `import` statement exists.

To achieve a true "research-grade" outcome, Radius will pioneer a hybrid approach: **Semantic CPG Slicing**. We will bridge the gap between fast, deterministic structural analysis and deep, contextual neural understanding.

## 2. The Novel Approach
Instead of relying solely on AST file-level graphs or purely on Large Language Models (which are slow and token-heavy for entire repositories), Radius will combine both:

1. **Symbol-Level Code Property Graph (CPG):** We utilize `tree-sitter` to deterministically parse repositories into a granular Code Property Graph. This graph maps relationships not at the file level, but at the symbol level (classes, functions, methods, and variables).
2. **Execution Slicing:** When a Pull Request modifies a function, we traverse the CPG to extract the exact execution path (the "slice") of upstream callers that depend on that specific function.
3. **Semantic LLM Pruning:** We feed *only the extracted micro-slice* (the old function, the new function, and the caller) into an LLM. The AI evaluates if the specific semantic change in the callee breaks the expected contract of the caller. If it does not, the graph edge is dynamically pruned.

### Advantages over Industry Standard
* **Precision:** Reduces the blast radius by eliminating false positives caused by dead code paths or non-breaking semantic changes (e.g., adding a log line).
* **Performance:** LLMs are only invoked on highly targeted, 50-100 line code slices rather than entire files or repositories, ensuring lightning-fast execution.
* **Explainability:** Generates human-readable explanations for *why* a test must be run (e.g., "Function A no longer handles nulls, which breaks Function B").

## 3. Proof of Concept (POC) Architecture

### 3.1 Components
* **Parser Engine:** Uses `tree-sitter` (Python/TypeScript bindings) to parse source code into an AST.
* **Graph Builder:** Converts the AST into a queryable in-memory Code Property Graph (NetworkX or simple Dictionary representation for the POC).
* **Slicer:** Given a modified line number/symbol, extracts the subgraph of callers.
* **LLM Evaluator:** A prompt wrapper (using Gemini 1.5 Flash/Pro) that compares the `git diff` of the callee against the caller's AST.

### 3.2 POC Workflow
1. **Input:** Two sample files (e.g., `db.py` and `api.py`). `api.py` contains `def get_user()` which calls `db.query()`.
2. **Parse:** Tree-sitter parses both files and builds the CPG edge: `api.get_user -> db.query`.
3. **Simulate Change:** We simulate a PR that changes `db.query()` to throw a `TimeoutError`.
4. **Slice:** The Slicer identifies that `api.get_user` is the only affected caller.
5. **Evaluate:** The LLM is prompted:
   > "The function `query` was modified to throw `TimeoutError`. Function `get_user` calls `query` but does not catch exceptions. Does this change semantically break `get_user`?"
6. **Output:** The LLM returns a JSON classification (`{"impacted": true, "reason": "..."}`). The POC outputs the refined blast radius.

## 4. Implementation Steps

1. **Setup Tree-sitter:** Install and configure `tree-sitter` and language grammars within the worker environment.
2. **Develop Parser Strategy:** Write the AST traversal logic to extract function definitions and call expressions.
3. **Graph Construction:** Link call expressions to function definitions across file boundaries.
4. **LLM Integration:** Draft the prompt engineering pipeline for semantic evaluation.
5. **POC Validation:** Execute the pipeline against a controlled set of mock files to demonstrate false-positive reduction compared to a traditional file-graph approach.
