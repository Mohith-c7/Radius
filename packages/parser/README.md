# Radius Parser Package

Owns source discovery, syntax parsing, symbol extraction, import/export extraction, and normalized source metadata.

The parser understands code structure but does not compute business impact.

## Language support

- Python: stdlib `ast`.
- TypeScript / JavaScript: tree-sitter, with tsconfig-aware import resolution in `radius_graph` (`ts_resolver.py`). See DEC-017 in `docs/decisions.md`.
- Go, Java, Rust: tree-sitter, **experimental** (imports not resolved to files).
