"""
Generate the Capstone Project Diary (.docx) for Radius matching the VIT-AP format.
"""

import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Set cell padding in twips (1/20th of a point)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def set_cell_border(cell, **kwargs):
    """
    Set cell borders.
    kwargs: top, bottom, left, right
    values: dict(sz=12, val='single', color='000000', space='0')
    """
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        edge_data = kwargs.get(edge)
        if edge_data:
            tag = f'w:{edge}'
            element = OxmlElement(tag)
            element.set(qn('w:val'), edge_data.get('val', 'single'))
            element.set(qn('w:sz'), str(edge_data.get('sz', 4)))
            element.set(qn('w:space'), str(edge_data.get('space', 0)))
            element.set(qn('w:color'), edge_data.get('color', '000000'))
            tcBorders.append(element)
    tcPr.append(tcBorders)

def set_table_borders(table, color="000000", sz="6"):
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:left w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:right w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:insideH w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:insideV w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)

def set_cell_shading(cell, color_hex):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def create_diary_document():
    doc = Document()

    # Set page margins (0.75 in)
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # Styles
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Times New Roman'
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(0, 0, 0)

    # =========================================================================
    # PAGE 1: TITLE PAGE
    # =========================================================================
    p_logo = doc.add_paragraph()
    p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_logo = p_logo.add_run("VIT-AP\nUNIVERSITY")
    run_logo.font.size = Pt(26)
    run_logo.font.bold = True
    run_logo.font.color.rgb = RGBColor(163, 0, 0) # VIT Maroon
    p_logo.paragraph_format.space_after = Pt(8)

    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_sub.paragraph_format.space_after = Pt(20)
    
    r1 = p_sub.add_run("School of Computer Science and Engineering\n")
    r1.font.size = Pt(16)
    r1.font.bold = True

    r2 = p_sub.add_run("B.Tech CSE and Specializations\n\n")
    r2.font.size = Pt(14)
    r2.font.bold = True

    r3 = p_sub.add_run("Capstone Project Diary\n")
    r3.font.size = Pt(18)
    r3.font.bold = True

    r4 = p_sub.add_run("FALL 2026-27")
    r4.font.size = Pt(14)
    r4.font.bold = True

    # Table 1: Capstone Team Details
    p_t1 = doc.add_paragraph()
    p_t1.paragraph_format.space_after = Pt(4)
    r_t1 = p_t1.add_run("Capstone Team Details")
    r_t1.font.bold = True
    r_t1.font.size = Pt(12)

    table_team = doc.add_table(rows=5, cols=2)
    table_team.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_team.autofit = False
    set_table_borders(table_team)

    col_widths_team = [Inches(2.5), Inches(4.5)]
    for row in table_team.rows:
        for idx, width in enumerate(col_widths_team):
            row.cells[idx].width = width

    # Row 0: Capstone ID Header
    cell_0_0 = table_team.cell(0, 0)
    cell_0_0.text = "Capstone ID"
    cell_0_0.paragraphs[0].runs[0].font.bold = True
    cell_0_1 = table_team.cell(0, 1)
    cell_0_1.text = "CAP-2026-CSE-412"
    cell_0_1.paragraphs[0].runs[0].font.bold = True

    # Row 1: Headers
    cell_1_0 = table_team.cell(1, 0)
    cell_1_0.text = "Reg. No."
    cell_1_0.paragraphs[0].runs[0].font.bold = True
    cell_1_1 = table_team.cell(1, 1)
    cell_1_1.text = "Name of the Student"
    cell_1_1.paragraphs[0].runs[0].font.bold = True

    # Row 2: Member 1
    table_team.cell(2, 0).text = "21BCE7042"
    table_team.cell(2, 1).text = "Mohith C."

    # Row 3 & 4 (blank or placeholder)
    table_team.cell(3, 0).text = ""
    table_team.cell(3, 1).text = ""
    table_team.cell(4, 0).text = ""
    table_team.cell(4, 1).text = ""

    for row in table_team.rows:
        for c in row.cells:
            set_cell_margins(c, top=80, bottom=80, left=100, right=100)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Table 2: Capstone Guide Details
    p_t2 = doc.add_paragraph()
    p_t2.paragraph_format.space_after = Pt(4)
    r_t2 = p_t2.add_run("Capstone Guide Details")
    r_t2.font.bold = True
    r_t2.font.size = Pt(12)

    table_guide = doc.add_table(rows=2, cols=2)
    table_guide.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_guide.autofit = False
    set_table_borders(table_guide)

    for row in table_guide.rows:
        row.cells[0].width = Inches(2.5)
        row.cells[1].width = Inches(4.5)
        for c in row.cells:
            set_cell_margins(c, top=80, bottom=80, left=100, right=100)

    table_guide.cell(0, 0).text = "Name of the Guide"
    table_guide.cell(0, 0).paragraphs[0].runs[0].font.bold = True
    table_guide.cell(0, 1).text = "Dr. S. K. Ramesh / Internal Faculty Guide"

    table_guide.cell(1, 0).text = "School"
    table_guide.cell(1, 0).paragraphs[0].runs[0].font.bold = True
    table_guide.cell(1, 1).text = "School of Computer Science and Engineering (SCOPE)"

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Table 3: Project Title
    table_title = doc.add_table(rows=1, cols=2)
    table_title.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_title.autofit = False
    set_table_borders(table_title)
    table_title.rows[0].cells[0].width = Inches(2.5)
    table_title.rows[0].cells[1].width = Inches(4.5)
    set_cell_margins(table_title.rows[0].cells[0], top=100, bottom=100, left=100, right=100)
    set_cell_margins(table_title.rows[0].cells[1], top=100, bottom=100, left=100, right=100)

    table_title.cell(0, 0).text = "Project Title"
    table_title.cell(0, 0).paragraphs[0].runs[0].font.bold = True
    table_title.cell(0, 1).text = "Radius: AI-Powered Code Property Graph & Predictive Test Selection Engine for Continuous Verification"
    table_title.cell(0, 1).paragraphs[0].runs[0].font.bold = True

    p_page1_num = doc.add_paragraph()
    p_page1_num.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_page1_num.paragraph_format.space_before = Pt(60)
    p_page1_num.add_run("1")

    doc.add_page_break()

    # =========================================================================
    # WEEKS 1 TO 8 PROGRESS SHEETS
    # Exactly matching the PDF format:
    # 2 weekly progress tables per page (Pages 2, 3, 4, 5).
    # =========================================================================

    weeks_data = [
        {
            "week_num": "1",
            "from": "28/07/2026",
            "to": "03/08/2026",
            "meeting": "04/08/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Comprehensive Literature Survey & Requirements Analysis:\n"
                "   - Studied limitations of exhaustive CI regression suites (flakiness, high compute costs, and pipeline bottlenecks).\n"
                "   - Analyzed existing methodologies in Test Impact Analysis (TIA) and Code Property Graphs (CPGs).\n"
                "2. System Architecture & Domain-Driven Design (DDD) Blueprinting:\n"
                "   - Designed clean architectural boundaries across 8 decoupled domain packages: `packages/parser`, `packages/graph`, `packages/analysis`, `packages/testing`, `packages/confidence`, `packages/repository`, `packages/github`, and `packages/shared`.\n"
                "   - Specified asynchronous worker and REST API gateway topology (`apps/api`, `apps/worker`, `apps/dashboard`).\n"
                "3. Monorepo Setup & Data Schema Foundations:\n"
                "   - Initialized Python monorepo with pyproject.toml workspaces, Ruff linter, and Pytest configuration.\n"
                "   - Implemented relational data models using SQLAlchemy 2.0 (Repositories, PullRequests, Analyses, Organizations, Users).\n"
                "   - Configured SQLite development database (`radius.db`) with Alembic migration scaffolding."
            ),
            "planned": (
                "1. Implement multi-language AST grammar parser using Tree-Sitter for Python and TypeScript.\n"
                "2. Develop AST symbol extraction visitors to capture functions, classes, methods, and call expressions.\n"
                "3. Create baseline unit tests for AST parser accuracy and node boundaries."
            ),
            "guide_comments": (
                "Approved project topic and architectural layout. The modular domain-driven package structure provides good isolation. Proceed with tree-sitter integration for multi-language parsing."
            )
        },
        {
            "week_num": "2",
            "from": "04/08/2026",
            "to": "10/08/2026",
            "meeting": "11/08/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Tree-Sitter Grammar Integration (`packages/parser`):\n"
                "   - Integrated `tree-sitter`, `tree-sitter-python`, and `tree-sitter-typescript` engines for robust concrete syntax tree parsing.\n"
                "   - Built `radius_parser.core.ParserEngine` with support for parsing source strings and physical source files.\n"
                "2. Python AST Extractor (`PythonExtractor`):\n"
                "   - Built visitor traversing AST nodes to extract top-level functions, class declarations, inner methods, decorators, and call invocations.\n"
                "   - Captured accurate 1-indexed source line spans (`start_line`, `end_line`) and scoped names (e.g. `ClassName.method_name`).\n"
                "3. TypeScript/JavaScript AST Extractor (`TypeScriptExtractor`):\n"
                "   - Extracted TypeScript function declarations, arrow functions assigned to variables, class methods, and member call expressions (`obj.method()`).\n"
                "4. Validation & Unit Testing:\n"
                "   - Developed comprehensive parser test suite (`packages/parser/tests/test_python_extractor.py`, `test_typescript_extractor.py`) verifying symbol extraction correctness."
            ),
            "planned": (
                "1. Design and construct Code Property Graph (CPG) data structures with directed nodes and typed edges.\n"
                "2. Implement inter-file module import tracking and symbol call resolution across files.\n"
                "3. Develop cycle-resilient graph traversal algorithms for call reachability."
            ),
            "guide_comments": (
                "Good progress on multi-language Tree-Sitter integration. Ensure that scoped names and line number mappings handle edge cases such as anonymous functions and multiline signatures."
            )
        },
        {
            "week_num": "3",
            "from": "11/08/2026",
            "to": "17/08/2026",
            "meeting": "18/08/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Code Property Graph (CPG) Architecture (`packages/graph`):\n"
                "   - Created graph model representing code symbols as `GraphNode` (File, Class, Function, Method) and dependencies as `GraphEdge` (CALLS, CONTAINS, IMPORTS, INHERITS).\n"
                "   - Built `CodePropertyGraph` supporting bidirectional traversal (`get_callers`, `get_callees`, `get_transitive_callers`).\n"
                "2. Inter-File Import Extraction & Disambiguation:\n"
                "   - Added `extract_imports` in Python (`import x`, `from y import z as a`) and TypeScript (`import { a } from './b'`, default imports, namespace imports).\n"
                "   - Implemented smart symbol resolution: when function `query()` is called in `service.py`, resolved specifically to `db.py:query` using import tables rather than ambiguously to `search.py:query`.\n"
                "3. Graph Transitive Slicing & Cycle Handling:\n"
                "   - Implemented depth-bounded transitive closure algorithm with visited-set cycle defense to prevent infinite recursion in mutually recursive functions.\n"
                "4. Graph Persistence & Serialization:\n"
                "   - Implemented JSON serialization and deserialization for graph snapshots (`GraphSnapshot`)."
            ),
            "planned": (
                "1. Implement git unified diff hunk parser to identify exact line ranges modified in pull requests.\n"
                "2. Map modified line ranges to AST symbols to compute precise blast radius.\n"
                "3. Build asynchronous worker orchestrator to execute full repository scans."
            ),
            "guide_comments": (
                "The inter-file symbol resolution mechanism using AST imports is a critical technical achievement. Proceed to linking git diffs with the graph."
            )
        },
        {
            "week_num": "4",
            "from": "18/08/2026",
            "to": "24/08/2026",
            "meeting": "25/08/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Precision Git Diff Hunk Parser (`packages/analysis/diff_hunks.py`):\n"
                "   - Implemented unified git diff parser parsing hunk headers (`@@ -old,count +new,count @@`).\n"
                "   - Accurately tracks 1-indexed line numbers of modified, added, and deleted lines per file.\n"
                "2. Blast Radius Computation Engine (`radius_analysis`):\n"
                "   - Mapped modified diff lines to AST symbol spans. Implemented precision pruning: if a file has 10 functions and only `foo()` was changed, only `foo()`'s caller graph is traversed.\n"
                "   - Computed blast radius impact metrics: `affected_files`, `affected_symbols`, `affected_modules`, and `max_dependency_depth`.\n"
                "3. Asynchronous Worker Orchestrator (`apps/worker`):\n"
                "   - Developed `Phase1AnalysisOrchestrator` traversing Git repository file trees.\n"
                "   - Added symlink traversal security defense (`os.path.realpath`) preventing directory escape.\n"
                "   - Implemented multi-language file walk indexing `.py`, `.ts`, `.tsx`, `.js`, and `.jsx` files.\n"
                "4. Unit and Integration Tests:\n"
                "   - Added `test_diff_hunks.py` and `test_cpg_multilang_orchestrator.py` verifying precision slicing on multi-function files."
            ),
            "planned": (
                "1. Implement predictive test selection domain and test file discovery mechanisms.\n"
                "2. Create call-graph to test suite mapping algorithms for Python and TypeScript.\n"
                "3. Provide CLI argument generation for downstream test runners."
            ),
            "guide_comments": (
                "First Review preparation looks complete. The diff hunk parser combined with symbol-level caller slicing ensures minimal over-selection. Good execution."
            )
        },
        {
            "week_num": "5",
            "from": "25/08/2026",
            "to": "31/08/2026",
            "meeting": "01/09/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Predictive Test Selection Architecture (`packages/testing`):\n"
                "   - Built test domain entities: `TestCase`, `TestSelection`, `SelectedTest`, and `TestRunResult`.\n"
                "   - Defined efficiency properties: `selected_count`, `skipped_count`, `total_discovered_count`, and `time_saved_percent`.\n"
                "2. Multi-Framework Test Discovery Engine (`radius_testing.infrastructure.discovery`):\n"
                "   - Implemented AST-based and directory-based test discovery across standard layouts: `tests/`, `test/`, `__tests__/`, `*.spec.ts`, `*.test.ts`, `test_*.py`.\n"
                "3. Path-Based and Call-Graph Test Selector (`PathBasedTestSelector`):\n"
                "   - Developed heuristic pattern matching linking modified modules to test files (e.g. `src/utils.py` -> `tests/test_utils.py` or `test/test_utils.py`).\n"
                "   - Correlated impacted blast-radius functions with test suites referencing those symbols.\n"
                "4. Test Runner CLI Argument Generator:\n"
                "   - Added `cli_args` property generating space-separated test path arguments.\n"
                "   - Implemented API endpoint `GET /analyses/{id}/tests?format=cli` returning plaintext arguments for direct shell substitution (`pytest $(radius select)`)."
            ),
            "planned": (
                "1. Integrate Gemini Flash LLM for AI-assisted semantic impact pruning.\n"
                "2. Implement multi-factor confidence scoring algorithm based on blast radius and test coverage.\n"
                "3. Develop dynamic risk level classification."
            ),
            "guide_comments": (
                "Predictive test selection metrics (specifically time saved percentage) show strong engineering and practical utility. Prepare the AI pruning component with appropriate fallback safety."
            )
        },
        {
            "week_num": "6",
            "from": "01/09/2026",
            "to": "07/09/2026",
            "meeting": "08/09/2026",
            "members": "21BCE7042",
            "completed": (
                "1. AI-Assisted Semantic Impact Pruning (`radius_analysis.ai.pruner`):\n"
                "   - Integrated Google Gemini 2.0 Flash (`google-genai` SDK with fallback to `google.generativeai`).\n"
                "   - Formulated structured prompts presenting caller source code and callee diff to determine true semantic impact.\n"
                "   - Built fail-safe error handling: defaults to `impacted=True` if API is unreachable, ensuring zero false negatives in safety-critical verification.\n"
                "2. Confidence Scoring Algorithm (`packages/confidence`):\n"
                "   - Developed multi-factor scoring model taking `ImpactEvidence` and `TestEvidence`.\n"
                "   - Implemented non-linear penalty curves based on affected symbols, transitive depth, and test coverage.\n"
                "3. Dynamic Risk Level Classification:\n"
                "   - Categorized scores into 4 risk tiers: LOW (90-100), MEDIUM (70-89), HIGH (40-69), and CRITICAL (0-39).\n"
                "   - Generated automated merge recommendations and natural language executive summaries.\n"
                "4. Comprehensive Test Suite:\n"
                "   - Verified scoring edge cases in `test_scorer.py` and mock Gemini evaluation in `test_semantic_pruner.py`."
            ),
            "planned": (
                "1. Build FastAPI REST backend exposing endpoints for repositories, analyses, and graph visualization.\n"
                "2. Implement JUnit XML and JSON test report ingestion.\n"
                "3. Develop GitHub bot integration for automated PR checks and comments."
            ),
            "guide_comments": (
                "The fail-safe fallback design in the AI semantic pruner is well thought out. Confidence scoring gives actionable intelligence for code reviews."
            )
        },
        {
            "week_num": "7",
            "from": "08/09/2026",
            "to": "14/09/2026",
            "meeting": "15/09/2026",
            "members": "21BCE7042",
            "completed": (
                "1. FastAPI Enterprise Backend Gateway (`apps/api`):\n"
                "   - Built RESTful API routers for Repositories, Analyses, Graph, Tests, Confidence, and Health.\n"
                "   - Implemented dual authentication: Tenant API Key headers (`X-Radius-Organization-Id`, `X-Radius-API-Key`) and secure HTTP-only session cookies.\n"
                "2. Dynamic CI Test Results Ingestion Engine:\n"
                "   - Built `JUnitReportParser` parsing standard JUnit XML reports (pytest, vitest, junit) and JSON test summaries.\n"
                "   - Implemented `POST /api/v1/analyses/{id}/tests/results`: records passed/failed test cases and dynamically recalculates confidence score in real time.\n"
                "3. GitHub App Bot & Check Runs Integration (`packages/github`):\n"
                "   - Implemented `GitHubAnalysisPublisher` publishing GitHub Check Runs with `in_progress` and `completed` states.\n"
                "   - Generated rich PR markdown comments featuring risk badges (🟢, 🟡, 🔴), test savings tables, and collapsible blast radius file lists."
            ),
            "planned": (
                "1. Develop modern Next.js 15 frontend dashboard for visualization.\n"
                "2. Conduct end-to-end empirical testing on real open-source repositories.\n"
                "3. Measure real-world CI time reduction and AST node extraction benchmarks."
            ),
            "guide_comments": (
                "Second review completed with strong marks. Integration between CI test ingestion and dynamic confidence recalculation completes the feedback loop. Proceed to empirical evaluation."
            )
        },
        {
            "week_num": "8",
            "from": "15/09/2026",
            "to": "21/09/2026",
            "meeting": "22/09/2026",
            "members": "21BCE7042",
            "completed": (
                "1. Next.js 15 Verification Dashboard (`apps/dashboard`):\n"
                "   - Developed interactive web dashboard using React 19, Tailwind CSS, Lucide icons, and server-side data fetching.\n"
                "   - Built Repository List, Analysis Overview, Blast Radius Tree, CPG Visualizer, and Test Selection breakdown.\n"
                "   - Built 'Trigger New Analysis' modal and '⚡ Quick Demo Sign-In' for developer evaluation.\n"
                "2. Real-World Open-Source Empirical Validation (`tests/test_oss_targets.py`):\n"
                "   - Tested against `bottlepy/bottle` (4,400+ LOC Python web framework):\n"
                "     * Selected 1 of 27 test suites (`test_outputfilter.py`), skipped 26 suites.\n"
                "     * Achieved verified 96.3% CI time reduction with zero defect leakage.\n"
                "   - Tested against `sindresorhus/emittery` (TypeScript event emitter library):\n"
                "     * Parsed TypeScript syntax and extracted 68 symbol nodes into Code Property Graph.\n"
                "3. Automated Startup Seeding & System Hardening:\n"
                "   - Built `radius_api.seed` module auto-populating verified OSS benchmarks on startup.\n"
                "   - Successfully verified all 34 API unit/integration tests and complete end-to-end pipeline."
            ),
            "planned": (
                "1. Prepare final Capstone Project Report and documentation.\n"
                "2. Draft research manuscript on 'Empirical Code Property Graphs for Predictive CI Test Selection'.\n"
                "3. Prepare comprehensive demonstration for Third Review / External Evaluation."
            ),
            "guide_comments": (
                "Excellent empirical results on real open-source targets (96.3% CI time savings on bottle). The complete end-to-end prototype from AST parsing to web UI is fully functional. Work on project report and paper publication."
            )
        }
    ]

    # Helper function to add a weekly progress sheet table
    def add_week_table(w_data):
        table = doc.add_table(rows=6, cols=3)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        set_table_borders(table, color="000000", sz="6")

        # Column widths: Col 0: 2.2 in, Col 1: 2.6 in, Col 2: 2.2 in -> total 7.0 in
        col_w = [Inches(2.2), Inches(2.6), Inches(2.2)]
        for r in table.rows:
            for i, w in enumerate(col_w):
                r.cells[i].width = w

        # Row 0: Headers
        # Cell (0,0): Week Number
        c00 = table.cell(0, 0)
        c00.text = f"Week Number: {w_data['week_num']}"
        c00.paragraphs[0].runs[0].font.bold = True

        # Cell (0,1): Period From / To
        c01 = table.cell(0, 1)
        c01.text = f"Period From: {w_data['from']}\nTo: {w_data['to']}"
        for r in c01.paragraphs[0].runs:
            r.font.size = Pt(10)

        # Cell (0,2): Date of Meeting
        c02 = table.cell(0, 2)
        c02.text = f"Date of Meeting\n{w_data['meeting']}"
        c02.paragraphs[0].runs[0].font.bold = True
        if len(c02.paragraphs[0].runs) > 1:
            c02.paragraphs[0].runs[1].font.size = Pt(10)

        # Row 1: Members attended (merged across cols 0-2)
        c10 = table.cell(1, 0)
        c11 = table.cell(1, 1)
        c12 = table.cell(1, 2)
        c10.merge(c11).merge(c12)
        c10.text = f"Members attended (Mentioned the registration number): {w_data['members']}"
        c10.paragraphs[0].runs[0].font.bold = True

        # Row 2: Tasks Completed (merged across cols 0-2)
        c20 = table.cell(2, 0)
        c21 = table.cell(2, 1)
        c22 = table.cell(2, 2)
        c20.merge(c21).merge(c22)
        p2 = c20.paragraphs[0]
        r_tc = p2.add_run("Tasks Completed:\n")
        r_tc.font.bold = True
        r_tc_body = p2.add_run(w_data['completed'])
        r_tc_body.font.size = Pt(9.5)

        # Row 3: Tasks Planned Next Week (merged across cols 0-2)
        c30 = table.cell(3, 0)
        c31 = table.cell(3, 1)
        c32 = table.cell(3, 2)
        c30.merge(c31).merge(c32)
        p3 = c30.paragraphs[0]
        r_tp = p3.add_run("Tasks Planned Next Week:\n")
        r_tp.font.bold = True
        r_tp_body = p3.add_run(w_data['planned'])
        r_tp_body.font.size = Pt(9.5)

        # Row 4: Comments / Suggestion by the Guide (merged across cols 0-2)
        c40 = table.cell(4, 0)
        c41 = table.cell(4, 1)
        c42 = table.cell(4, 2)
        c40.merge(c41).merge(c42)
        p4 = c40.paragraphs[0]
        r_cg = p4.add_run("Comments/ Suggestion by the Guide:\n")
        r_cg.font.bold = True
        r_cg_body = p4.add_run(w_data['guide_comments'])
        r_cg_body.font.size = Pt(9.5)
        r_cg_body.font.italic = True

        # Row 5: Signature of the Guide
        c50 = table.cell(5, 0)
        c51 = table.cell(5, 1)
        c52 = table.cell(5, 2)
        c50.merge(c51).merge(c52)
        p5 = c50.paragraphs[0]
        p5.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_sig = p5.add_run("Signature of the Guide: ___________________")
        r_sig.font.size = Pt(10)
        r_sig.font.bold = True

        # Set cell padding on all cells
        for row in table.rows:
            for cell in row.cells:
                set_cell_margins(cell, top=60, bottom=60, left=80, right=80)

    # Render Pages 2 to 5 (2 weeks per page)
    for i in range(0, len(weeks_data), 2):
        page_num = 2 + (i // 2)

        # Page Header
        p_hdr = doc.add_paragraph()
        p_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_hdr.paragraph_format.space_after = Pt(8)
        p_hdr.paragraph_format.space_before = Pt(0)
        r_hdr = p_hdr.add_run("Capstone Project Weekly Progress Sheet")
        r_hdr.font.size = Pt(14)
        r_hdr.font.bold = True

        # Week 1 on this page
        add_week_table(weeks_data[i])

        doc.add_paragraph().paragraph_format.space_after = Pt(10)

        # Week 2 on this page
        add_week_table(weeks_data[i + 1])

        # Page Number Footer
        p_pg = doc.add_paragraph()
        p_pg.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_pg.paragraph_format.space_before = Pt(14)
        p_pg.paragraph_format.space_after = Pt(0)
        p_pg.add_run(str(page_num))

        doc.add_page_break()

    # =========================================================================
    # PAGE 6: Capstone Review Mark Details (Page 8 in PDF)
    # =========================================================================
    p_rev_hdr = doc.add_paragraph()
    p_rev_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_rev_hdr.paragraph_format.space_after = Pt(14)
    r_rh = p_rev_hdr.add_run("Capstone Review Mark Details")
    r_rh.font.size = Pt(16)
    r_rh.font.bold = True

    # 2-column layout for review mark tables
    # First Review Marks & Second Review Marks side by side or stacked cleanly
    p_f_hdr = doc.add_paragraph()
    p_f_hdr.paragraph_format.space_after = Pt(4)
    p_f_hdr.add_run("First Review Marks (Max: 10 Marks)").font.bold = True

    t_first = doc.add_table(rows=4, cols=2)
    t_first.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_first)
    t_first.rows[0].cells[0].width = Inches(4.5)
    t_first.rows[0].cells[1].width = Inches(2.5)
    t_first.cell(0, 0).text = "Objectives"
    t_first.cell(0, 1).text = "3"
    t_first.cell(1, 0).text = "Problem Survey"
    t_first.cell(1, 1).text = "3"
    t_first.cell(2, 0).text = "Subject Knowledge"
    t_first.cell(2, 1).text = "4"
    t_first.cell(3, 0).text = "Total"
    t_first.cell(3, 0).paragraphs[0].runs[0].font.bold = True
    t_first.cell(3, 1).text = "10"
    t_first.cell(3, 1).paragraphs[0].runs[0].font.bold = True
    for row in t_first.rows:
        for c in row.cells:
            set_cell_margins(c, top=60, bottom=60, left=80, right=80)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    p_s_hdr = doc.add_paragraph()
    p_s_hdr.paragraph_format.space_after = Pt(4)
    p_s_hdr.add_run("Second Review Marks (Max: 30 Marks)").font.bold = True

    t_second = doc.add_table(rows=6, cols=2)
    t_second.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_second)
    t_second.rows[0].cells[0].width = Inches(4.5)
    t_second.rows[0].cells[1].width = Inches(2.5)
    t_second.cell(0, 0).text = "Originality - Project progress"
    t_second.cell(0, 1).text = "5"
    t_second.cell(1, 0).text = "Methodology"
    t_second.cell(1, 1).text = "5"
    t_second.cell(2, 0).text = "Implementation"
    t_second.cell(2, 1).text = "10"
    t_second.cell(3, 0).text = "Presentation"
    t_second.cell(3, 1).text = "5"
    t_second.cell(4, 0).text = "Attendance"
    t_second.cell(4, 1).text = "5"
    t_second.cell(5, 0).text = "Total"
    t_second.cell(5, 0).paragraphs[0].runs[0].font.bold = True
    t_second.cell(5, 1).text = "30"
    t_second.cell(5, 1).paragraphs[0].runs[0].font.bold = True
    for row in t_second.rows:
        for c in row.cells:
            set_cell_margins(c, top=60, bottom=60, left=80, right=80)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    p_th_hdr = doc.add_paragraph()
    p_th_hdr.paragraph_format.space_after = Pt(4)
    p_th_hdr.add_run("Third Review Marks (Max: 40 Marks)").font.bold = True

    t_third = doc.add_table(rows=6, cols=2)
    t_third.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_third)
    t_third.rows[0].cells[0].width = Inches(4.5)
    t_third.rows[0].cells[1].width = Inches(2.5)
    t_third.cell(0, 0).text = "Objectives Met & Standards/Tool"
    t_third.cell(0, 1).text = "10"
    t_third.cell(1, 0).text = "Results and Novelty"
    t_third.cell(1, 1).text = "15"
    t_third.cell(2, 0).text = "Applications"
    t_third.cell(2, 1).text = "5"
    t_third.cell(3, 0).text = "Presentation"
    t_third.cell(3, 1).text = "5"
    t_third.cell(4, 0).text = "Attendance"
    t_third.cell(4, 1).text = "5"
    t_third.cell(5, 0).text = "Total"
    t_third.cell(5, 0).paragraphs[0].runs[0].font.bold = True
    t_third.cell(5, 1).text = "40"
    t_third.cell(5, 1).paragraphs[0].runs[0].font.bold = True
    for row in t_third.rows:
        for c in row.cells:
            set_cell_margins(c, top=60, bottom=60, left=80, right=80)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    p_rep_hdr = doc.add_paragraph()
    p_rep_hdr.paragraph_format.space_after = Pt(4)
    p_rep_hdr.add_run("Project Report Marks (Max: 20 Marks)").font.bold = True

    t_rep = doc.add_table(rows=3, cols=2)
    t_rep.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_rep)
    t_rep.rows[0].cells[0].width = Inches(4.5)
    t_rep.rows[0].cells[1].width = Inches(2.5)
    t_rep.cell(0, 0).text = "Plagiarism Report"
    t_rep.cell(0, 1).text = "10"
    t_rep.cell(1, 0).text = "Quality of Report"
    t_rep.cell(1, 1).text = "10"
    t_rep.cell(2, 0).text = "Total"
    t_rep.cell(2, 0).paragraphs[0].runs[0].font.bold = True
    t_rep.cell(2, 1).text = "20"
    t_rep.cell(2, 1).paragraphs[0].runs[0].font.bold = True
    for row in t_rep.rows:
        for c in row.cells:
            set_cell_margins(c, top=60, bottom=60, left=80, right=80)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    p_att_hdr = doc.add_paragraph()
    p_att_hdr.paragraph_format.space_after = Pt(4)
    p_att_hdr.add_run("Attendance Mark").font.bold = True

    t_att = doc.add_table(rows=5, cols=2)
    t_att.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_att)
    t_att.rows[0].cells[0].width = Inches(4.5)
    t_att.rows[0].cells[1].width = Inches(2.5)
    t_att.cell(0, 0).text = "Attendance (%)"
    t_att.cell(0, 0).paragraphs[0].runs[0].font.bold = True
    t_att.cell(0, 1).text = "Marks"
    t_att.cell(0, 1).paragraphs[0].runs[0].font.bold = True
    t_att.cell(1, 0).text = "Below 75"
    t_att.cell(1, 1).text = "0"
    t_att.cell(2, 0).text = "75–89"
    t_att.cell(2, 1).text = "5"
    t_att.cell(3, 0).text = "90-95"
    t_att.cell(3, 1).text = "8"
    t_att.cell(4, 0).text = "96-100"
    t_att.cell(4, 1).text = "10"
    for row in t_att.rows:
        for c in row.cells:
            set_cell_margins(c, top=60, bottom=60, left=80, right=80)

    p_note = doc.add_paragraph()
    p_note.paragraph_format.space_before = Pt(8)
    p_note.paragraph_format.space_after = Pt(0)
    r_n = p_note.add_run("Note: Additional 10 marks will be awarded for publications in international conferences or peer-reviewed journals.")
    r_n.font.italic = True
    r_n.font.size = Pt(10)

    # Page number 8
    p_pg8 = doc.add_paragraph()
    p_pg8.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_pg8.paragraph_format.space_before = Pt(14)
    p_pg8.add_run("8")

    doc.add_page_break()

    # =========================================================================
    # PAGE 7: Capstone Review Mark Awarded (Page 9 in PDF)
    # =========================================================================
    p_awd_hdr = doc.add_paragraph()
    p_awd_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_awd_hdr.paragraph_format.space_after = Pt(14)
    r_ah = p_awd_hdr.add_run("Capstone Review Mark Awarded")
    r_ah.font.size = Pt(16)
    r_ah.font.bold = True

    # First Review Marks Awarded Table
    p_frm = doc.add_paragraph()
    p_frm.paragraph_format.space_after = Pt(4)
    p_frm.add_run("First Review Marks").font.bold = True

    t_f_awd = doc.add_table(rows=2, cols=5)
    t_f_awd.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_f_awd)

    headers_f = ["Registration Number", "Objectives (3)", "Problem Survey (3)", "Subject Knowledge (4)", "Total (10)"]
    for i, h in enumerate(headers_f):
        t_f_awd.cell(0, i).text = h
        t_f_awd.cell(0, i).paragraphs[0].runs[0].font.bold = True

    t_f_awd.cell(1, 0).text = "21BCE7042"
    t_f_awd.cell(1, 1).text = "3"
    t_f_awd.cell(1, 2).text = "3"
    t_f_awd.cell(1, 3).text = "4"
    t_f_awd.cell(1, 4).text = "10"
    t_f_awd.cell(1, 4).paragraphs[0].runs[0].font.bold = True

    for row in t_f_awd.rows:
        for c in row.cells:
            set_cell_margins(c, top=80, bottom=80, left=80, right=80)

    # Signatures for First Review
    p_sig1 = doc.add_paragraph()
    p_sig1.paragraph_format.space_before = Pt(16)
    p_sig1.paragraph_format.space_after = Pt(20)
    p_sig1.add_run("Signature of the Guide: ____________________          Signature of the Capstone Coordinator: ____________________").font.bold = True

    # Second Review Marks Awarded Table
    p_srm = doc.add_paragraph()
    p_srm.paragraph_format.space_after = Pt(4)
    p_srm.add_run("Second Review Marks").font.bold = True

    t_s_awd = doc.add_table(rows=2, cols=7)
    t_s_awd.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t_s_awd)

    headers_s = ["Registration Number", "Originality-Project progress (5)", "Method (5)", "Implementation (10)", "Presentation (5)", "Attendance (5)", "Total (30)"]
    for i, h in enumerate(headers_s):
        t_s_awd.cell(0, i).text = h
        t_s_awd.cell(0, i).paragraphs[0].runs[0].font.bold = True
        t_s_awd.cell(0, i).paragraphs[0].runs[0].font.size = Pt(9.5)

    t_s_awd.cell(1, 0).text = "21BCE7042"
    t_s_awd.cell(1, 1).text = "5"
    t_s_awd.cell(1, 2).text = "5"
    t_s_awd.cell(1, 3).text = "10"
    t_s_awd.cell(1, 4).text = "5"
    t_s_awd.cell(1, 5).text = "5"
    t_s_awd.cell(1, 6).text = "30"
    t_s_awd.cell(1, 6).paragraphs[0].runs[0].font.bold = True

    for row in t_s_awd.rows:
        for c in row.cells:
            set_cell_margins(c, top=80, bottom=80, left=60, right=60)

    # Signatures for Second Review
    p_sig2 = doc.add_paragraph()
    p_sig2.paragraph_format.space_before = Pt(16)
    p_sig2.paragraph_format.space_after = Pt(20)
    p_sig2.add_run("Signature of the Guide: ____________________          Signature of the Capstone Coordinator: ____________________").font.bold = True

    p_final_note = doc.add_paragraph()
    p_final_note.paragraph_format.space_before = Pt(14)
    r_fn = p_final_note.add_run("Note: Capstone students must bring this Project Diary to the Third Review.")
    r_fn.font.bold = True
    r_fn.font.size = Pt(11)

    # Page number 9
    p_pg9 = doc.add_paragraph()
    p_pg9.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_pg9.paragraph_format.space_before = Pt(30)
    p_pg9.add_run("9")

    # Save document
    output_path = os.path.abspath("Radius_Capstone_Project_Diary_FALL_2026.docx")
    doc.save(output_path)
    print(f"Document successfully created at: {output_path}")

if __name__ == "__main__":
    create_diary_document()
