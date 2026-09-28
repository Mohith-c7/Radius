import tree_sitter
import tree_sitter_python
import tree_sitter_typescript


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

    def parse_python(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Python code into an Abstract Syntax Tree."""
        return self.python_parser.parse(bytes(source_code, "utf8"))

    def parse_typescript(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of TypeScript code into an Abstract Syntax Tree."""
        return self.ts_parser.parse(bytes(source_code, "utf8"))
