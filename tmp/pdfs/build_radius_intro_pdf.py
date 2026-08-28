from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "radius_project_introduction.pdf"


class Rule(Flowable):
    def __init__(self, color=colors.HexColor("#2563EB"), thickness=1.4):
        super().__init__()
        self.color = color
        self.thickness = thickness
        self.height = 8
        self.width = 0

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        return avail_width, self.height

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 4, self.width, 4)


class WorkflowDiagram(Flowable):
    def __init__(self, labels: list[str]):
        super().__init__()
        self.labels = labels
        self.width = 7.0 * inch
        self.height = 2.35 * inch

    def wrap(self, avail_width, avail_height):
        self.width = min(avail_width, 7.0 * inch)
        return self.width, self.height

    def draw(self):
        c = self.canv
        box_w = self.width / 3.25
        box_h = 0.36 * inch
        gap_x = (self.width - (3 * box_w)) / 2
        y_positions = [self.height - 0.55 * inch, self.height - 1.18 * inch, self.height - 1.81 * inch]
        x_positions = [0, box_w + gap_x, 2 * (box_w + gap_x)]
        c.setFont("Helvetica", 7.6)
        c.setLineWidth(0.8)
        for idx, label in enumerate(self.labels):
            row = idx // 3
            col = idx % 3
            x = x_positions[col]
            y = y_positions[row]
            c.setFillColor(colors.HexColor("#EFF6FF"))
            c.setStrokeColor(colors.HexColor("#93C5FD"))
            c.roundRect(x, y, box_w, box_h, 5, stroke=1, fill=1)
            c.setFillColor(colors.HexColor("#111827"))
            lines = label.split("\n")
            for line_idx, line in enumerate(lines):
                c.drawCentredString(x + box_w / 2, y + box_h / 2 + 4 - (line_idx * 9), line)
            if idx < len(self.labels) - 1:
                next_row = (idx + 1) // 3
                next_col = (idx + 1) % 3
                nx = x_positions[next_col]
                ny = y_positions[next_row]
                if next_row == row:
                    c.setStrokeColor(colors.HexColor("#64748B"))
                    c.line(x + box_w, y + box_h / 2, nx, ny + box_h / 2)
                    c.line(nx - 5, ny + box_h / 2 + 3, nx, ny + box_h / 2)
                    c.line(nx - 5, ny + box_h / 2 - 3, nx, ny + box_h / 2)
                else:
                    c.setStrokeColor(colors.HexColor("#64748B"))
                    c.line(x + box_w / 2, y, x + box_w / 2, ny + box_h)


def p(text: str, style: ParagraphStyle):
    return Paragraph(text, style)


def bullets(items: list[str], style: ParagraphStyle):
    return [Paragraph(f"- {item}", style) for item in items]


def section(title: str, styles):
    return [Spacer(1, 0.08 * inch), Paragraph(title, styles["SectionTitle"]), Rule(), Spacer(1, 0.08 * inch)]


def table(data, col_widths, header=True):
    cell_style = ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=7.8,
        leading=9.7,
        textColor=colors.HexColor("#111827"),
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=cell_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    wrapped = []
    for row_idx, row in enumerate(data):
        wrapped_row = []
        for cell in row:
            style = header_style if header and row_idx == 0 else cell_style
            wrapped_row.append(Paragraph(escape(str(cell)), style))
        wrapped.append(wrapped_row)

    t = Table(wrapped, colWidths=col_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            style.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#F8FAFC")))
    t.setStyle(TableStyle(style))
    return t


def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(doc.leftMargin, 0.45 * inch, "Radius - Final Year Project Introduction")
    canvas.drawRightString(A4[0] - doc.rightMargin, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.65 * inch,
        title="Radius Project Introduction",
        author="Radius Team",
    )

    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=28,
            leading=32,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=8,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#334155"),
            spaceAfter=16,
        ),
        "SectionTitle": ParagraphStyle(
            "SectionTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#1E3A8A"),
            spaceAfter=4,
        ),
        "Heading": ParagraphStyle(
            "Heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=6,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontSize=9.2,
            leading=12.4,
            textColor=colors.HexColor("#111827"),
            spaceAfter=5,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontSize=8.1,
            leading=10.2,
            textColor=colors.HexColor("#334155"),
            spaceAfter=4,
        ),
        "Callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=13.2,
            textColor=colors.HexColor("#0F172A"),
            alignment=TA_LEFT,
            backColor=colors.HexColor("#E0F2FE"),
            borderColor=colors.HexColor("#38BDF8"),
            borderWidth=0.8,
            borderPadding=8,
            spaceAfter=10,
        ),
    }

    story = []

    story.extend(
        [
            Spacer(1, 0.55 * inch),
            p("Radius", styles["Title"]),
            p("The Confidence Layer for Modern Software Development", styles["Subtitle"]),
            Rule(colors.HexColor("#1E3A8A"), 2.2),
            Spacer(1, 0.25 * inch),
            p(
                "Final Year Project - Introduction Round Brief",
                ParagraphStyle(
                    "Intro",
                    parent=styles["Heading"],
                    alignment=TA_CENTER,
                    fontSize=13,
                    textColor=colors.HexColor("#0F172A"),
                ),
            ),
            Spacer(1, 0.2 * inch),
            p(
                "This document explains the idea, technical workflow, current proof of concept, completed work, and roadmap for Radius. It is written for professors, teammates, and reviewers who need to understand the project clearly without reading the entire codebase.",
                styles["Body"],
            ),
            Spacer(1, 0.2 * inch),
            table(
                [
                    ["Project", "Radius - AI-native software verification platform"],
                    ["Core question", "Is this pull request safe to merge?"],
                    ["Current phase", "Phase 1 deterministic repository intelligence and verification foundation"],
                    ["Primary users", "Developers, technical leads, DevOps/platform teams, and organizations using AI-assisted development"],
                    ["Prepared from", "Repository docs and code status on 22 Aug 2026"],
                ],
                [1.6 * inch, 4.8 * inch],
                header=False,
            ),
            PageBreak(),
        ]
    )

    story.extend(section("1. Executive Summary", styles))
    story.append(
        p(
            "Radius is a software verification platform that analyzes code changes before merge and produces explainable evidence about risk and confidence. It does not replace GitHub, CI/CD, or existing test frameworks. Instead, it sits between code changes and deployment, understands the repository structure, computes the affected area of a change, selects relevant validations, and presents a confidence report.",
            styles["Body"],
        )
    )
    story.append(p("In simple terms:", styles["Heading"]))
    story.append(
        p(
            "Radius helps a reviewer move from only asking 'Did the tests pass?' to asking 'What changed, what can break, which tests matter, and how confident are we before merging?'",
            styles["Callout"],
        )
    )
    story.append(p("Why this matters", styles["Heading"]))
    story.extend(
        bullets(
            [
                "AI coding tools and fast development cycles can create large changes quickly.",
                "A passing test suite may still miss hidden dependencies or untested impact areas.",
                "Reviewers need explainable evidence, not a black-box score.",
                "Radius focuses first on deterministic analysis, so results are traceable and repeatable.",
            ],
            styles["Body"],
        )
    )
    story.append(p("Project positioning", styles["Heading"]))
    story.extend(
        bullets(
            [
                "Radius is a repository intelligence and pull request verification system.",
                "Radius is not a CI/CD replacement, source hosting platform, formatter, or AI coding assistant.",
                "Future AI features will enhance summarization and recommendations, but Phase 1 decisions are deterministic.",
            ],
            styles["Body"],
        )
    )
    story.append(PageBreak())

    story.extend(section("2. Problem and Proposed Solution", styles))
    story.append(p("Problem", styles["Heading"]))
    story.append(
        p(
            "Traditional pipelines mostly report whether existing tests passed. They usually do not explain the full impact of a change, which modules depend on modified code, whether selected tests are sufficient, or what evidence supports merge readiness.",
            styles["Body"],
        )
    )
    problem_table = [
        ["Current gap", "Why it is a problem", "Radius response"],
        ["Only pass/fail test output", "Reviewers cannot see what remains unverified.", "Attach confidence evidence and recommendations."],
        ["No repository-level understanding", "Dependency impact is hard to inspect manually.", "Parse code and build dependency graphs."],
        ["Large pull requests are risky", "Hidden affected files and modules can be missed.", "Compute blast radius from graph traversal."],
        ["Tests may be too broad or too narrow", "Teams waste time or miss targeted validation.", "Select relevant tests based on impacted paths."],
    ]
    story.append(table(problem_table, [1.55 * inch, 2.25 * inch, 2.6 * inch]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(p("Solution concept", styles["Heading"]))
    story.append(
        p(
            "Radius builds a deterministic verification pipeline. A GitHub event or manual trigger starts an analysis. Radius synchronizes repository context, reads the diff, parses source files, updates a dependency graph, computes affected files/modules/tests, executes relevant validations, and produces an explainable confidence report visible in the dashboard and, in the target flow, GitHub feedback.",
            styles["Body"],
        )
    )
    story.append(PageBreak())

    story.extend(section("3. End-to-End Workflow", styles))
    story.append(
        p(
            "The core workflow is intentionally pipeline-based. Each step receives structured input, produces structured output, and remains loosely coupled from the next step.",
            styles["Body"],
        )
    )
    story.append(
        WorkflowDiagram(
            [
                "GitHub event\nor manual trigger",
                "Repository\nsync",
                "Git diff and\nchanged files",
                "Source parsing\nand symbols",
                "Dependency graph\nupdate",
                "Blast radius\ncalculation",
                "Relevant tests\nselected/run",
                "Confidence report\nwith evidence",
                "Dashboard and\nGitHub feedback",
            ]
        )
    )
    story.append(p("Workflow details", styles["Heading"]))
    workflow_table = [
        ["Step", "What Radius does", "Output"],
        ["1. Trigger", "Receives GitHub webhook or manual analysis request.", "Analysis record/job"],
        ["2. Repository", "Clones/fetches/checks out repository context.", "Local repository snapshot"],
        ["3. Diff", "Reads Git changes and normalizes added/modified/deleted/renamed files.", "Changed-file evidence"],
        ["4. Parser", "Extracts imports, exports, classes, functions, methods, and symbols.", "Repository metadata"],
        ["5. Graph", "Builds file/module/symbol dependency relationships.", "Graph snapshot"],
        ["6. Blast radius", "Traverses reverse dependencies from changed files.", "Affected files, modules, symbols, tests"],
        ["7. Testing", "Discovers and plans/runs relevant existing tests.", "Test selection and run result"],
        ["8. Confidence", "Scores risk from deterministic evidence.", "Confidence score, risk level, recommendations"],
        ["9. Presentation", "Displays evidence through dashboard and future GitHub checks/comments.", "Reviewer-facing result"],
    ]
    story.append(table(workflow_table, [0.95 * inch, 3.55 * inch, 1.9 * inch]))
    story.append(PageBreak())

    story.extend(section("4. Technical Architecture", styles))
    story.append(p("Architecture style", styles["Heading"]))
    story.extend(
        bullets(
            [
                "Monorepo with independent apps and domain packages.",
                "FastAPI backend exposes REST APIs under /api/v1.",
                "Next.js dashboard consumes API contracts and displays repository/analysis evidence.",
                "Worker service executes long-running analysis jobs.",
                "PostgreSQL and SQLAlchemy support durable production storage; memory stores support local development.",
                "Interfaces isolate business logic from infrastructure details.",
            ],
            styles["Body"],
        )
    )
    tech_table = [
        ["Area", "Technology / package", "Purpose"],
        ["Frontend", "Next.js, React, TypeScript", "Dashboard pages, data panels, repository and analysis views"],
        ["Backend API", "FastAPI, Pydantic", "Request validation, routing, response envelopes, API boundary"],
        ["Worker", "Python worker runtime", "Claim analysis jobs and run the deterministic pipeline"],
        ["Persistence", "PostgreSQL, SQLAlchemy, Alembic", "Durable repositories, analyses, graph/test/confidence artifacts"],
        ["Parsing", "Python AST plus JavaScript/TypeScript adapters", "Source discovery, symbol/import/export extraction"],
        ["Graph", "Domain graph package", "Dependency graph construction and reverse dependency traversal"],
        ["Testing", "Pytest subprocess runner and test selection package", "Relevant test discovery, planning, execution result capture"],
        ["GitHub", "GitHub App/webhook/check/comment support", "Repository events, private clone tokens, feedback publishing"],
        ["Tooling", "pnpm, TurboRepo, Ruff, Black, Pytest, ESLint", "Workspace orchestration and code quality"],
    ]
    story.append(table(tech_table, [1.2 * inch, 2.2 * inch, 3.0 * inch]))
    story.append(PageBreak())

    story.extend(section("5. Domain Modules", styles))
    domain_table = [
        ["Module", "Responsibility", "Current implementation evidence"],
        ["repository", "Connected repositories, branches, pull requests, local Git ingestion.", "Domain contracts, DTOs, app service, SQLAlchemy store, local clone/fetch/checkout adapter."],
        ["parser", "Source file discovery and semantic extraction.", "Python AST parser and JS/TS adapters for imports, exports, symbols."],
        ["graph", "Repository dependency model.", "Graph builder, module resolver, in-memory and SQL-backed graph stores."],
        ["analysis", "Analysis lifecycle, changed files, blast radius.", "Analysis service, diff analyzer, job queue, SQL stores, blast-radius computation."],
        ["testing", "Discover, select, plan, and run existing tests.", "Conventional discovery, path-based selector, subprocess runner, SQL artifact store."],
        ["confidence", "Convert evidence into risk and confidence.", "Deterministic scoring, evidence, recommendations, report persistence."],
        ["shared", "Cross-cutting primitives.", "Settings, database metadata, response envelopes, errors, logging."],
        ["github", "GitHub App integration outputs.", "Installation token flow, check-run and PR-comment publishing support."],
    ]
    story.append(table(domain_table, [1.0 * inch, 2.3 * inch, 3.1 * inch]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(p("API surface implemented for the POC", styles["Heading"]))
    story.extend(
        bullets(
            [
                "Repository endpoints: connect, list, get, disconnect.",
                "Analysis endpoints: start, list, get, rerun.",
                "Artifact endpoints: blast radius, graph, selected tests, confidence.",
                "Operational endpoints: health and readiness.",
                "GitHub webhook endpoint with signature validation and idempotent handling.",
            ],
            styles["Body"],
        )
    )
    story.append(PageBreak())

    story.extend(section("6. Current POC and Completed Work", styles))
    story.append(
        p(
            "The current proof of concept demonstrates the deterministic foundation of Radius. It can run locally with the FastAPI API on port 8000 and the Next.js dashboard on port 3000. The backend supports memory storage for simple local review and SQL-backed storage for realistic persisted execution.",
            styles["Body"],
        )
    )
    poc_table = [
        ["POC capability", "Status"],
        ["Monorepo foundation", "Done - apps, packages, docs, tooling, branch workflow."],
        ["API/dashboard local setup", "Done - local CORS and valid dashboard organization UUID documented."],
        ["Repository and analysis APIs", "Done - route layer and service wiring exist."],
        ["Parser/graph/change/blast-radius core", "Done - deterministic package implementations with tests."],
        ["Test selection and execution", "Done - discovery, planning, subprocess run result capture."],
        ["Confidence reports", "Done - deterministic score, risk level, evidence, recommendations."],
        ["Worker orchestration", "Done - queued job claim/execute/complete/fail helpers and persisted context loading."],
        ["GitHub integration", "Partially complete - webhook, token, checks/comments code exists; live credential smoke validation remains."],
        ["Docker/CI/deployment docs", "Present - Dockerfiles, compose, CI workflow, deployment guide; live Docker smoke depends on local Docker/build runner."],
    ]
    story.append(table(poc_table, [2.0 * inch, 4.4 * inch]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(p("Recent setup improvement", styles["Heading"]))
    story.append(
        p(
            "A local dashboard setup issue was fixed by allowing CORS requests from the dashboard origins and documenting a valid UUID for NEXT_PUBLIC_RADIUS_ORGANIZATION_ID. This prevents browser-side 'Failed to fetch' errors for new developers running the API and dashboard separately.",
            styles["Body"],
        )
    )
    story.append(PageBreak())

    story.extend(section("7. What to Demonstrate in the Introduction Round", styles))
    story.append(p("Recommended demo narrative", styles["Heading"]))
    demo_steps = [
        ["1", "Open the dashboard", "Show that Radius is not a marketing page; it is a working reviewer dashboard."],
        ["2", "Explain the core question", "Every page supports the question: is this pull request safe to merge?"],
        ["3", "Show repository and analysis concepts", "Repositories create analyses; analyses own changed files, blast radius, tests, graph, and confidence."],
        ["4", "Explain deterministic workflow", "Show the pipeline from GitHub/manual trigger to confidence report."],
        ["5", "Discuss current POC", "Local API/dashboard, domain packages, worker, persistence, tests, and GitHub integration code."],
        ["6", "Discuss remaining validation", "Live GitHub App credentials, production-like Docker smoke, and polished final demo data."],
    ]
    story.append(table([["#", "Demo point", "What to say"]] + demo_steps, [0.35 * inch, 1.7 * inch, 4.35 * inch]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(p("One-minute explanation for the professor", styles["Heading"]))
    story.append(
        p(
            "Radius is our final year project for software verification. Modern development, especially AI-assisted development, creates code faster than teams can manually reason about risk. Our system analyzes a pull request, understands changed files and dependencies, computes the blast radius, selects relevant tests, and produces an explainable confidence report. The first version deliberately uses deterministic analysis so that every result can be traced and defended.",
            styles["Callout"],
        )
    )
    story.append(PageBreak())

    story.extend(section("8. Roadmap and Next Steps", styles))
    roadmap_table = [
        ["Milestone", "Goal", "Next action"],
        ["Immediate", "Complete introduction-round readiness.", "Use this PDF, clean demo script, and show localhost dashboard/API."],
        ["POC validation", "Validate real GitHub flow.", "Configure GitHub App credentials, install app on test repository, run webhook-to-confidence demo."],
        ["Deployment smoke", "Prove production runtime shape.", "Run Docker Compose or CI build runner with PostgreSQL, API, worker, dashboard, migrations."],
        ["Dashboard polish", "Improve review experience.", "Add stable demo data, clearer empty states, analysis detail walkthrough, graph visualization improvements."],
        ["Phase 2", "Repository intelligence depth.", "Improve parsers, language coverage, symbol resolution, incremental parsing."],
        ["Phase 3", "Dependency graph quality.", "Improve graph persistence, traversal accuracy, dependency resolution, visual exploration."],
        ["Phase 4", "Pull request impact analysis.", "Stronger changed-symbol detection, richer blast-radius evidence."],
        ["Phase 5", "Test intelligence.", "Better test mapping, coverage input, framework support, faster execution."],
        ["Phase 6", "Confidence engine.", "Refine scoring, risk classification, evidence weighting, recommendations."],
        ["Future", "AI-assisted verification.", "AI explanations, generated tests, security signals, historical learning, integrations."],
    ]
    story.append(table(roadmap_table, [1.05 * inch, 2.1 * inch, 3.25 * inch]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(p("Important scope clarity", styles["Heading"]))
    story.extend(
        bullets(
            [
                "Phase 1 is not trying to build all AI features.",
                "The current focus is the deterministic engine: repository, graph, blast radius, tests, confidence, API, worker, and dashboard.",
                "AI-generated tests, security analysis, historical learning, organization-wide graphs, and autonomous PR reviews are future-phase items.",
            ],
            styles["Body"],
        )
    )
    story.append(PageBreak())

    story.extend(section("9. Review Checklist and Sources", styles))
    story.append(p("Review checklist before final project presentation", styles["Heading"]))
    story.extend(
        bullets(
            [
                "Confirm dashboard loads from localhost and API health/readiness endpoints respond.",
                "Prepare one sample repository or demo analysis record so screens are not empty.",
                "Verify GitHub App secrets only in private environment variables, never in code.",
                "Run the project quality commands before final submission: pnpm install, pnpm lint, pnpm typecheck, pnpm test, pnpm build.",
                "If demonstrating full GitHub automation, complete the live GitHub App smoke test first.",
            ],
            styles["Body"],
        )
    )
    story.append(p("Primary repo sources used", styles["Heading"]))
    source_table = [
        ["Source", "Used for"],
        ["README.md", "Project identity, phase workflow, stack, structure."],
        ["docs/PROJECT_OVERVIEW.md", "Problem, mission, product philosophy, target users."],
        ["docs/PHASE1_SPECIFICATION.md", "Phase 1 goals, deliverables, out-of-scope items, acceptance criteria."],
        ["docs/SYSTEM_ARCHITECTURE.md", "Pipeline architecture and subsystem responsibilities."],
        ["docs/API_CONTRACTS.md", "API boundary, endpoint groups, response envelope."],
        ["docs/DOMAIN_MODEL.md", "Repository, pull request, analysis, graph, testing, confidence concepts."],
        ["docs/PHASE1_BACKEND_TASKS.md", "Completed backend work, remaining validation, current estimate."],
        ["docs/roadmap.md", "Milestones and future roadmap."],
        ["docs/DEPLOYMENT.md", "Services, environment, CI, GitHub App permissions."],
    ]
    story.append(table(source_table, [2.0 * inch, 4.4 * inch]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(
        p(
            "Final takeaway: Radius is a repository-aware verification layer. Its value is not just running tests, but explaining what changed, what is affected, what was validated, and how much confidence reviewers should have before merge.",
            styles["Callout"],
        )
    )

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT)
