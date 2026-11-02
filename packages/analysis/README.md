# Radius Analysis Package

Owns Git diff interpretation, changed symbol detection, blast radius computation, impact analysis, and risk factors.

This package must not execute tests or produce presentation-layer reports.

## Symbol-level change extraction (LK-01)

`radius_analysis.symbol_changes` turns a diff plus the base and head snapshots
into a precise, serializable `SymbolChangeSet`: the symbols that changed, how
they changed, and which diff lines belong to each. It is the foundation for
criterion->symbol links (LK-02), symbol->test links (LK-03) and the tamper rules
(EV-02).

Placement (DEC-003): a sub-package of `packages/analysis`, not a new package.
Analysis already uses `radius_graph`, and the TypeScript/JavaScript grammars come
from `radius_parser` (F-09) through the new public `parse_syntax_tree` helper
instead of a second copy of the grammar loading. F-08
(`radius_graph.symbol_impact`) keeps its reference-graph role (who uses a name)
and is untouched; the two share only the `<module>` pseudo-symbol name. LK-01
needs what F-08 does not keep (signature, decorators, docstring, normalised body
per definition, for both versions), so it has its own definition index
(`index_python.py`, `index_ecmascript.py`) instead of bending F-08's.

```python
from radius_analysis.symbol_changes import (
    ExtractionOptions, GitSnapshot, RefRange, extract_symbol_changes,
)

result = extract_symbol_changes(
    GitSnapshot(repo, "origin/develop"),      # repo_base: None rebuilds it from head + diff
    GitSnapshot(repo, "HEAD"),                # repo_head: any SnapshotReader
    RefRange(repo, "origin/develop", "HEAD"), # or a unified-diff string
    ExtractionOptions(),                      # limits, thresholds, ignore globs
)
print(result.to_json(indent=2))
```

Debug CLI (prints JSON, no side effects):

```
python -m radius_analysis.symbol_changes --repo . --base origin/develop --head HEAD
python -m radius_analysis.symbol_changes --diff pr.patch --head-dir ./checkout [--ignore GLOB]
```

Worker: `RADIUS_FEATURE_SYMBOL_CHANGES` (default `false`, setting
`symbol_changes_enabled`) runs the extraction after the diff is analysed and logs
`changed_symbols`, `behavioral_symbols`, `unattributed_hunks`, `file_level_files`
and `truncated` (F-10 logger). Nothing is stored until LK-05; any failure is
logged and ignored.

### Output contract (`algo_version` = `symbol-changes-v1`)

`SymbolChangeSet.to_dict()` / `to_json()` / `from_dict()` / `from_json()` round-trip
exactly and are deterministic (same input, same bytes; input order irrelevant).

| Field | Meaning |
|---|---|
| `algo_version`, `config` | algorithm version and the options used (thresholds, ignore globs) |
| `truncated`, `notes` | a time/file/diff budget was hit; set-level notes (for example `rename_detection_skipped_limit`) |
| `counts` | totals by change kind, language and file level |
| `files[]` | per file: `path`, `old_path`, `status` (added/deleted/modified/renamed/copied), `language`, `level` (`symbol`, `file` = degraded, `ignored`, `none`), `notes` |
| `symbols[]` | the changed symbols, ordered by (path, line, name, kind, change kind) |
| `unattributed_hunks[]` | changed lines outside any symbol: `path`, `language`, `reason`, hunk header and `old_lines` / `new_lines` ranges |

Each symbol: `symbol_id` (`language:path::qualified_name#kind@signature_hash`,
head side when it exists), `key` (the id without the signature hash, stable
across signature changes), `old_symbol_id` / `new_symbol_id`, `language`, `path`,
`old_path`, `qualified_name`, `old_qualified_name`, `kind` (`function`, `method`,
`property`, `class`, `lambda`, `interface`, `type`, `enum`, `namespace`,
`module`, `file`), `change_kind`, `secondary_kinds`, `is_behavioral`,
`old_range` / `new_range` (inclusive 1-based lines), `old_signature` /
`new_signature`, `old_body_hash` / `new_body_hash` (hash of the normalised own
body), `hunks[]` (hunk header plus the deleted / added line ranges attributed to
this symbol), `confidence` and `notes`.

**Invariant (tested as a property):** every changed line of every analysed file
(deleted lines in base coordinates, added lines in head coordinates) is either in
a symbol's `hunks` or in `unattributed_hunks`. Ignored files are listed in `files`
with `level = ignored` and have no symbols.

### Change kinds

| `change_kind` | Meaning |
|---|---|
| `added` / `removed` | the definition exists only at head / only at base |
| `modified_signature` | name-free signature differs (parameters, defaults, annotations, return type, `async`, base classes, TS modifiers, `export`) |
| `modified_body` | the own body differs structurally (nested definitions excluded) |
| `decorator_or_annotation_changed` | only the decorators differ (Python and TS decorators) |
| `docstring_or_comment_only` | only the docstring or comments differ; not behavioral |
| `formatting_only` | the normalised AST (Python) or token stream (TS/JS) is identical; not behavioral |
| `renamed` | same parent, different name, body similarity at or above the threshold |
| `moved` | same file, different parent (for example a method moved to another class) |
| `moved_between_files` | removed in one file, added in another with similar body; also every symbol of a git-renamed file |

When several apply, the primary kind is chosen by priority `modified_signature`
> `modified_body` > `decorator_or_annotation_changed` > docstring/comment >
formatting, and the structural others are listed in `secondary_kinds`. Renamed and
moved symbols list structural differences as secondary kinds, add notes such as
`renamed_with_body_changes`, and their `confidence` is the similarity score.
Symbols whose lines were only touched cosmetically are still reported, as
`formatting_only`, so consumers filter on `is_behavioral`.

Rename and move detection: multiset-Jaccard of token 3-grams over signature plus
body (children included for classes). Defaults: similarity >= 0.85 and at least 12
tokens on both sides (tiny functions are never guessed), same kind, greedy
best-first with deterministic tie-breaks, bounded by `max_similarity_pairs`.

Note `suppression_marker_changed` marks a symbol whose changed lines contain a
suppression marker (`# type: ignore`, `# noqa`, `# pragma: no cover`,
`eslint-disable`, `@ts-ignore`, ...); EV-02 rules T009 and T013 can start there.

### Degradation (never crashes the pipeline)

A file becomes one file-level unit (`kind = file`, `qualified_name = <file>`,
`confidence = 0.5`, all its hunks attached) with a note when: the language has no
indexer (`unsupported_language`), the file is binary (`binary_file`), too large
(`file_too_large`), a snapshot is missing (`snapshot_missing_base/head`), either
version fails to parse (`parse_error_base:...` / `parse_error_head:...`), the time
budget or `max_files` was exceeded (`timeout`, `max_files_exceeded`, set-level
`truncated`) or an unexpected error occurred (`internal_error:<Type>`). Generated
or vendored paths (configurable `ignore_globs`, plus `@generated` / `DO NOT EDIT`
headers) are listed as ignored.

### Unattributed reasons

`import` (module-level import statements), `blank_or_comment` (outside any
symbol), `blank_between_members` (blank lines between members of a class or
namespace), `module_level` (module code when `module_pseudo_symbol=False`),
`out_of_range` (diff lines beyond the file; indicates a diff/snapshot mismatch).
Other module-level statements form the `<module>` pseudo-symbol.

### Limitations

* Python and TypeScript/JavaScript only; other languages are file-level.
* Identity within a file is (qualified name, kind); duplicated names (overloads,
  conditional redefinitions) are paired by signature, then body, then order, and
  named `name@2`, `name@3`.
* Comments directly above a definition belong to a TS/JS symbol (JSDoc) but not to
  a Python one; the Python docstring is always part of the symbol.
* TS/JS fingerprints are token based: semicolons, trailing commas, quote style and
  whitespace are normalised, but parenthesisation or object-key order are not, so
  those register as `modified_body`.
* Not tracked as symbols: CommonJS/prototype assignment patterns
  (`exports.f = ...`, `X.prototype.m = ...`), object-literal methods and anonymous
  callbacks (`describe`/`it` bodies are `<module>` code), class fields that are not
  functions (part of the class body).
* Rename detection needs similar bodies of at least 12 tokens; a renamed one-liner
  is reported as removed plus added.
* The diff must belong to the given snapshots; on a mismatch lines fall to
  `out_of_range` or are mis-attributed. `--no-prefix` diffs and combined
  (`diff --cc`) diffs are not supported (the latter is flagged).
* Path aliases (`tsconfig` `paths`) are not needed: symbols are keyed by repository
  path, alias resolution stays in the dependency graph.
* If `tree-sitter-javascript` is missing in an environment, JavaScript files are
  parsed with the TSX grammar (a superset); it is a declared dependency, so CI uses
  the JavaScript grammar.

### Consumers

* EV-02 (tamper rules): `change_kind` / `is_behavioral` to ignore cosmetic edits,
  `removed` and `old_range` for deleted tests, `decorator_or_annotation_changed`
  for added skip/xfail markers, `old_signature` / `new_signature` and `hunks` for
  before/after snippets, `notes` (`suppression_marker_changed`).
* LK-02 (criterion->symbol): candidates are behavioral symbols (`symbol_id`,
  `qualified_name`, `path`, ranges); `key` caches embeddings across signature
  edits and `new_body_hash` is the content hash.
* LK-03 (symbol->test): `symbol_id` / `key` plus `new_range` for coverage-context
  joins; `renamed` / `moved*` carry `old_symbol_id` so links can be carried over.
* LK-05 will persist `SymbolChangeSet.to_dict()` keyed by (analysis, head SHA).
