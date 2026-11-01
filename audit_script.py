import os
import ast
import json

directories = [
    r"d:\Radius\apps\api",
    r"d:\Radius\apps\worker",
    r"d:\Radius\packages\analysis\src",
    r"d:\Radius\packages\confidence\src",
    r"d:\Radius\packages\github\src",
    r"d:\Radius\packages\graph\src",
    r"d:\Radius\packages\parser\src",
    r"d:\Radius\packages\repository\src",
    r"d:\Radius\packages\shared\src",
    r"d:\Radius\packages\testing\src",
    r"d:\Radius\tests"
]
specific_files = [
    r"d:\Radius\pyproject.toml",
    r"d:\Radius\conftest.py",
    r"d:\Radius\test_e2e.py"
]

report_lines = ["# Radius Python Backend Audit Report\n"]

def analyze_file(filepath):
    if not filepath.endswith('.py') and not filepath.endswith('.toml'):
        return
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        report_lines.append(f"## {filepath}\nError reading: {e}\n")
        return

    if filepath.endswith('.toml'):
        report_lines.append(f"## {filepath}\n- **Type**: Configuration file\n- **TODOs**: {content.count('TODO')}\n- **Lines**: {len(content.splitlines())}\n")
        return

    try:
        tree = ast.parse(content)
    except Exception as e:
        report_lines.append(f"## {filepath}\nError parsing: {e}\n")
        return

    classes = []
    functions = []
    stubs = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
            body_statements = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
            if len(body_statements) == 0 or (len(body_statements) == 1 and isinstance(body_statements[0], ast.Pass)):
                stubs.append(f"Class: {node.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            body = node.body
            is_stub = False
            stmt_count = 0
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    continue # docstring
                stmt_count += 1
                if isinstance(stmt, ast.Pass):
                    is_stub = True
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
                    is_stub = True
                elif isinstance(stmt, ast.Raise):
                    if isinstance(stmt.exc, ast.Name) and stmt.exc.id == 'NotImplementedError':
                        is_stub = True
                    elif isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == 'NotImplementedError':
                        is_stub = True
            
            if is_stub or stmt_count == 0:
                stubs.append(f"Function: {node.name}")

    todos = []
    for i, line in enumerate(content.split('\n')):
        if 'TODO' in line or 'NotImplemented' in line:
            todos.append(f"Line {i+1}: {line.strip()}")

    integrations = []
    lower_content = content.lower()
    if 'github' in lower_content: integrations.append('GitHub API')
    if 'gemini' in lower_content or 'google.generativeai' in lower_content or 'vertex' in lower_content: integrations.append('Gemini AI')
    if 'sqlalchemy' in lower_content: integrations.append('Database (SQLAlchemy)')
    
    # Check test coverage status in test files
    is_test_file = 'test' in filepath.lower() or 'conftest' in filepath.lower()
    
    # Only report if it has significant content
    if classes or functions or todos or integrations or is_test_file:
        report_lines.append(f"## File: {filepath}")
        if classes:
            report_lines.append(f"- **Classes Implemented**: {', '.join(classes)}")
        if functions:
            report_lines.append(f"- **Functions Implemented**: {', '.join(functions)}")
        if stubs:
            report_lines.append(f"- **Stubs/Placeholders**: {', '.join(stubs)}")
        else:
            report_lines.append(f"- **Stubs/Placeholders**: None detected.")
            
        if todos:
            report_lines.append(f"- **TODOs / NotImplemented Markers**:")
            for t in todos:
                report_lines.append(f"  - {t}")
        else:
            report_lines.append(f"- **TODOs**: None")
            
        if integrations:
            report_lines.append(f"- **Integrations Mentioned**: {', '.join(integrations)}")
            if 'mock' in lower_content or 'magicmock' in lower_content or 'pytest-mock' in lower_content:
                report_lines.append(f"- **Mocking**: Detected use of mocking (likely mock integrations)")
        
        if is_test_file:
            if 'def test_' in content or 'class Test' in content:
                report_lines.append(f"- **Test Status**: Contains test cases.")
            else:
                report_lines.append(f"- **Test Status**: Test utility or setup file (no direct test cases found).")
                
        report_lines.append("")

for d in directories:
    if not os.path.exists(d):
        continue
    for root, _, files in os.walk(d):
        for f in files:
            analyze_file(os.path.join(root, f))

for f in specific_files:
    analyze_file(f)

with open(r'd:\Radius\audit_report.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))

print('Audit complete. Report saved to d:\Radius\audit_report.md')
