import tree_sitter
import tree_sitter_python

class ParserEngine:
    """Core engine to initialize grammars and parse source code into ASTs."""
    
    def __init__(self):
        # Initialize the Python language grammar
        self.python_language = tree_sitter.Language(tree_sitter_python.language())
        
        # Initialize the parser
        self.parser = tree_sitter.Parser(self.python_language)
        
    def parse_python(self, source_code: str) -> tree_sitter.Tree:
        """Parses a string of Python code into an Abstract Syntax Tree."""
        # Tree-sitter requires bytes
        return self.parser.parse(bytes(source_code, "utf8"))
