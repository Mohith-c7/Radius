import tree_sitter
import tree_sitter_python
import tree_sitter_typescript

try:
    import tree_sitter_go
except ImportError:
    tree_sitter_go = None

try:
    import tree_sitter_java
except ImportError:
    tree_sitter_java = None

try:
    import tree_sitter_rust
except ImportError:
    tree_sitter_rust = None


class ParserEngine:
    """Core engine to initialize grammars and parse source code into ASTs."""

    def __init__(self):
        # Initialize the Python language grammar
        self.python_language = tree_sitter.Language(tree_sitter_python.language())
        self.python_parser = tree_sitter.Parser(self.python_language)

        # Initialize the TypeScript language grammar
        self.ts_language = tree_sitter.Language(
            tree_sitter_typescript.language_typescript()
        )
        self.ts_parser = tree_sitter.Parser(self.ts_language)

        # Initialize the Go language grammar
        if tree_sitter_go is not None:
            self.go_language = tree_sitter.Language(tree_sitter_go.language())
            self.go_parser = tree_sitter.Parser(self.go_language)
        else:
            self.go_language = None
            self.go_parser = None

        # Initialize the Java language grammar
        if tree_sitter_java is not None:
            self.java_language = tree_sitter.Language(tree_sitter_java.language())
            self.java_parser = tree_sitter.Parser(self.java_language)
        else:
            self.java_language = None
            self.java_parser = None

        # Initialize the Rust language grammar
        if tree_sitter_rust is not None:
            self.rust_language = tree_sitter.Language(tree_sitter_rust.language())
            self.rust_parser = tree_sitter.Parser(self.rust_language)
        else:
            self.rust_language = None
            self.rust_parser = None

    def parse_python(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Python code into an Abstract Syntax Tree."""
        return self.python_parser.parse(bytes(source_code, "utf8"))

    def parse_typescript(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of TypeScript code into an Abstract Syntax Tree."""
        return self.ts_parser.parse(bytes(source_code, "utf8"))

    def parse_go(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Go code into an Abstract Syntax Tree."""
        if self.go_parser is None:
            raise RuntimeError("tree-sitter-go is not installed.")
        return self.go_parser.parse(bytes(source_code, "utf8"))

    def parse_java(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Java code into an Abstract Syntax Tree."""
        if self.java_parser is None:
            raise RuntimeError("tree-sitter-java is not installed.")
        return self.java_parser.parse(bytes(source_code, "utf8"))

    def parse_rust(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Rust code into an Abstract Syntax Tree."""
        if self.rust_parser is None:
            raise RuntimeError("tree-sitter-rust is not installed.")
        return self.rust_parser.parse(bytes(source_code, "utf8"))
