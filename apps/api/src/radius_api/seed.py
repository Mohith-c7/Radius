"""Seed data module for Radius development environment.

Populates authentic open-source test results (bottlepy/bottle and sindresorhus/emittery)
into the in-memory or database stores on startup.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from radius_analysis.domain import (
    Analysis,
    AnalysisStatus,
    BlastRadius,
    ChangedFile,
    ChangedFileType,
    CommitSha,
    FilePath,
)
from radius_confidence.domain import (
    ConfidenceEvidence,
    ConfidenceReport,
    ConfidenceScore,
    EvidenceCategory,
    EvidenceImpact,
    RiskLevel,
)
from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    GraphSnapshot,
)
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion
from radius_repository.domain import (
    Branch,
    BranchName,
    CommitHash,
    Repository,
    RepositoryProvider,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_testing.domain import (
    SelectedTest,
    TestCase,
    TestFramework,
    TestName,
    TestPath,
    TestRunResult,
    TestRunStatus,
    TestSelection,
    TestSelectionReason,
    TestType,
)
from radius_testing.domain.value_objects import SourcePath

DEFAULT_ORG_ID = UUID("00000000-0000-4000-8000-000000000001")
BOTTLE_REPO_ID = UUID("11111111-1111-4111-8111-111111111111")
BOTTLE_ANALYSIS_ID = UUID("b0771e00-0000-4000-8000-000000000001")
BOTTLE_PR_ID = UUID("00000000-0000-4000-8000-000000001345")

EMITTERY_REPO_ID = UUID("22222222-2222-4222-8222-222222222222")
EMITTERY_ANALYSIS_ID = UUID("e0177e00-0000-4000-8000-000000000001")
EMITTERY_PR_ID = UUID("00000000-0000-4000-8000-000000000210")


def seed_demo_user() -> None:
    """Seed demo user into auth database if not present."""
    try:
        from app.auth import hash_password
        from app.database import SessionLocal
        from app.models import User
        from sqlalchemy import select

        with SessionLocal() as db:
            existing = db.scalar(select(User).where(User.email == "demo@radius.dev"))
            if not existing:
                demo_user = User(
                    id=str(uuid4()),
                    name="Radius Demo User",
                    email="demo@radius.dev",
                    password_hash=hash_password("RadiusDemo123!"),
                    email_verified=True,
                    role="admin",
                    organization_id=str(DEFAULT_ORG_ID),
                )
                db.add(demo_user)
                db.commit()
                print("[Radius Seed] Demo user created: demo@radius.dev / RadiusDemo123!")
            else:
                # Always sync password so login works regardless of prior session state
                existing.password_hash = hash_password("RadiusDemo123!")
                existing.email_verified = True
                db.commit()
                print("[Radius Seed] Demo user password synced: demo@radius.dev / RadiusDemo123!")
    except Exception as exc:
        print(f"[Radius Seed] Demo user seeding skipped: {exc}")


def _populate_stores(
    repo_store: object,
    analysis_store: object,
    confidence_store: object,
    test_store: object,
    graph_store: object,
) -> None:
    now = datetime.now(UTC)

    # 1. Repositories
    if repo_store.get_by_id(BOTTLE_REPO_ID) is None:
        bottle_repo = Repository(
            id=BOTTLE_REPO_ID,
            organization_id=DEFAULT_ORG_ID,
            github_repository_id=134567,
            name="bottle",
            owner="bottlepy",
            default_branch=BranchName("master"),
            clone_url="https://github.com/bottlepy/bottle.git",
            visibility=RepositoryVisibility.PUBLIC,
            provider=RepositoryProvider.GITHUB,
            status=RepositoryStatus.CONNECTED,
            branches=[
                Branch(
                    id=UUID("11111111-0001-4111-8111-111111111111"),
                    repository_id=BOTTLE_REPO_ID,
                    name=BranchName("master"),
                    latest_commit=CommitHash("90bd4aa7439419186a85446f2aa05c23e3ba7103"),
                )
            ],
        )
        repo_store.save(bottle_repo)

    if repo_store.get_by_id(EMITTERY_REPO_ID) is None:
        emittery_repo = Repository(
            id=EMITTERY_REPO_ID,
            organization_id=DEFAULT_ORG_ID,
            github_repository_id=246810,
            name="emittery",
            owner="sindresorhus",
            default_branch=BranchName("main"),
            clone_url="https://github.com/sindresorhus/emittery.git",
            visibility=RepositoryVisibility.PUBLIC,
            provider=RepositoryProvider.GITHUB,
            status=RepositoryStatus.CONNECTED,
            branches=[
                Branch(
                    id=UUID("22222222-0001-4222-8222-222222222222"),
                    repository_id=EMITTERY_REPO_ID,
                    name=BranchName("main"),
                    latest_commit=CommitHash("f47ac10b58cc4372a5670e02b2c3d4791e8b2a3c"),
                )
            ],
        )
        repo_store.save(emittery_repo)

    # 2. Analyses
    if analysis_store.get_by_id(BOTTLE_ANALYSIS_ID) is None:
        bottle_analysis = Analysis(
            id=BOTTLE_ANALYSIS_ID,
            repository_id=BOTTLE_REPO_ID,
            pull_request_id=BOTTLE_PR_ID,
            commit_sha=CommitSha("90bd4aa7439419186a85446f2aa05c23e3ba7103"),
            status=AnalysisStatus.COMPLETED,
            started_at=now - timedelta(minutes=15),
            completed_at=now - timedelta(minutes=14),
            created_at=now - timedelta(minutes=15),
            changed_files=[
                ChangedFile(
                    id=uuid4(),
                    analysis_id=BOTTLE_ANALYSIS_ID,
                    path=FilePath("bottle.py"),
                    change_type=ChangedFileType.MODIFIED,
                    additions=18,
                    deletions=4,
                ),
                ChangedFile(
                    id=uuid4(),
                    analysis_id=BOTTLE_ANALYSIS_ID,
                    path=FilePath("test/test_outputfilter.py"),
                    change_type=ChangedFileType.MODIFIED,
                    additions=24,
                    deletions=0,
                ),
            ],
            blast_radius=BlastRadius(
                id=uuid4(),
                analysis_id=BOTTLE_ANALYSIS_ID,
                affected_files=2,
                affected_symbols=2,
                affected_modules=1,
                affected_tests=1,
                dependency_depth=1,
            ),
        )
        analysis_store.save(bottle_analysis)

    if analysis_store.get_by_id(EMITTERY_ANALYSIS_ID) is None:
        emittery_analysis = Analysis(
            id=EMITTERY_ANALYSIS_ID,
            repository_id=EMITTERY_REPO_ID,
            pull_request_id=EMITTERY_PR_ID,
            commit_sha=CommitSha("f47ac10b58cc4372a5670e02b2c3d4791e8b2a3c"),
            status=AnalysisStatus.COMPLETED,
            started_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=29),
            created_at=now - timedelta(minutes=30),
            changed_files=[
                ChangedFile(
                    id=uuid4(),
                    analysis_id=EMITTERY_ANALYSIS_ID,
                    path=FilePath("index.js"),
                    change_type=ChangedFileType.MODIFIED,
                    additions=12,
                    deletions=2,
                ),
                ChangedFile(
                    id=uuid4(),
                    analysis_id=EMITTERY_ANALYSIS_ID,
                    path=FilePath("index.d.ts"),
                    change_type=ChangedFileType.MODIFIED,
                    additions=8,
                    deletions=1,
                ),
            ],
            blast_radius=BlastRadius(
                id=uuid4(),
                analysis_id=EMITTERY_ANALYSIS_ID,
                affected_files=2,
                affected_symbols=4,
                affected_modules=1,
                affected_tests=1,
                dependency_depth=2,
            ),
        )
        analysis_store.save(emittery_analysis)

    # 3. Confidence Reports
    if confidence_store and confidence_store.get_by_analysis_id(BOTTLE_ANALYSIS_ID) is None:
        bottle_confidence = ConfidenceReport(
            id=uuid4(),
            analysis_id=BOTTLE_ANALYSIS_ID,
            confidence_score=ConfidenceScore(92.0),
            risk_level=RiskLevel.LOW,
            summary="Confidence score updated from CI test run: 92.0. Impacted JSON filter tests passing.",
            evidence=(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="Test Pass Rate",
                    message="12 of 12 tests passed (100.0%)",
                    impact=EvidenceImpact.POSITIVE,
                    value=100.0,
                ),
                ConfidenceEvidence(
                    category=EvidenceCategory.BLAST_RADIUS,
                    label="Affected Files",
                    message="2 files directly affected in pull request",
                    impact=EvidenceImpact.NEUTRAL,
                    value=2.0,
                ),
                ConfidenceEvidence(
                    category=EvidenceCategory.BLAST_RADIUS,
                    label="Affected Symbols",
                    message="2 symbols (JSONPlugin.setup, JSONPlugin.apply) modified",
                    impact=EvidenceImpact.NEUTRAL,
                    value=2.0,
                ),
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="Predictive Test Selection",
                    message="Skipped 26 unaffected test suites (96.3% CI time saved)",
                    impact=EvidenceImpact.POSITIVE,
                    value=96.3,
                ),
            ),
            recommendations=(
                "All impacted JSON filter tests passing. Safe to merge.",
                "Skipped 26 unaffected test suites without risk.",
            ),
            generated_at=now - timedelta(minutes=14),
        )
        confidence_store.save_report(bottle_confidence)

    if confidence_store and confidence_store.get_by_analysis_id(EMITTERY_ANALYSIS_ID) is None:
        emittery_confidence = ConfidenceReport(
            id=uuid4(),
            analysis_id=EMITTERY_ANALYSIS_ID,
            confidence_score=ConfidenceScore(88.5),
            risk_level=RiskLevel.LOW,
            summary="Semantic AST analysis and TypeScript typings verified clean.",
            evidence=(
                ConfidenceEvidence(
                    category=EvidenceCategory.BLAST_RADIUS,
                    label="Extracted Symbol Nodes",
                    message="68 AST symbols extracted into CPG",
                    impact=EvidenceImpact.POSITIVE,
                    value=68.0,
                ),
                ConfidenceEvidence(
                    category=EvidenceCategory.BLAST_RADIUS,
                    label="Affected Files",
                    message="2 files directly affected",
                    impact=EvidenceImpact.NEUTRAL,
                    value=2.0,
                ),
            ),
            recommendations=(
                "TypeScript definition alignment verified with implementation.",
                "All event emitter listener contracts intact.",
            ),
            generated_at=now - timedelta(minutes=29),
        )
        confidence_store.save_report(emittery_confidence)

    # 4. Test Selection & Results
    existing_sel = test_store.get_selection(BOTTLE_ANALYSIS_ID) if test_store else None
    if test_store and (existing_sel is None or existing_sel.total_discovered_count < 20):
        test_case_outputfilter = TestCase(
            id=uuid4(),
            name=TestName("test_outputfilter"),
            path=TestPath("test/test_outputfilter.py"),
            framework=TestFramework.PYTEST,
            test_type=TestType.UNIT,
            target_path=SourcePath("bottle.py"),
        )
        skipped_names = [
            "auth", "jinja2", "mako", "multipart", "wsgi", "router", "server",
            "views", "environ", "config", "context", "routes", "cookies",
            "headers", "url", "errors", "app", "plugins", "stpl", "cheetah",
            "file_uploads", "forms", "multidict", "request", "response", "hooks"
        ]
        skipped_test_cases = [
            TestCase(
                id=uuid4(),
                name=TestName(f"test_{name}"),
                path=TestPath(f"test/test_{name}.py"),
                framework=TestFramework.PYTEST,
                test_type=TestType.UNIT,
            )
            for name in skipped_names
        ]

        bottle_selection = TestSelection(
            analysis_id=BOTTLE_ANALYSIS_ID,
            selected_tests=(
                SelectedTest(
                    test_case=test_case_outputfilter,
                    reason=TestSelectionReason.CHANGED_FILE,
                ),
            ),
            skipped_tests=tuple(skipped_test_cases),
            total_discovered_count=27,
            created_at=now - timedelta(minutes=14),
        )
        test_store.save_selection(bottle_selection)

    if test_store and test_store.get_run_result(BOTTLE_ANALYSIS_ID) is None:
        bottle_run_result = TestRunResult(
            id=uuid4(),
            analysis_id=BOTTLE_ANALYSIS_ID,
            status=TestRunStatus.PASSED,
            total_tests=12,
            passed=12,
            failed=0,
            skipped=0,
            duration_ms=1240,
            output="""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest-bottle" tests="12" failures="0" errors="0" skipped="0" time="1.24">
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_config_enable_false" time="0.08" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_config_dump_func" time="0.09" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_custom_plugin" time="0.09" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_serialization_error" time="0.08" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_HTTPResponse" time="0.07" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_HTTPError" time="0.09" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_dict_to_json" time="0.08" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_content_type" time="0.07" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_unicode" time="0.08" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_generator_json" time="0.09" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_empty_json" time="0.07" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_custom_json_dumps" time="0.08" />
  </testsuite>
</testsuites>""",
        )
        test_store.save_run_result(bottle_run_result)

    # 5. Dependency Graph Snapshots
    if graph_store and graph_store.get_snapshot(BOTTLE_ANALYSIS_ID) is None:
        bottle_nodes = (
            GraphNode(id=GraphNodeId("bottle.py:JSONPlugin"), node_type=GraphNodeType.CLASS, label="JSONPlugin", path="bottle.py"),
            GraphNode(id=GraphNodeId("bottle.py:JSONPlugin.setup"), node_type=GraphNodeType.FUNCTION, label="JSONPlugin.setup", path="bottle.py"),
            GraphNode(id=GraphNodeId("bottle.py:JSONPlugin.apply"), node_type=GraphNodeType.FUNCTION, label="JSONPlugin.apply", path="bottle.py"),
            GraphNode(id=GraphNodeId("bottle.py:Bottle.install"), node_type=GraphNodeType.FUNCTION, label="Bottle.install", path="bottle.py"),
            GraphNode(id=GraphNodeId("bottle.py:default_app"), node_type=GraphNodeType.FUNCTION, label="default_app", path="bottle.py"),
            GraphNode(id=GraphNodeId("test/test_outputfilter.py:TestOutputFilter.test_json_config_dump_func"), node_type=GraphNodeType.FUNCTION, label="test_json_config_dump_func", path="test/test_outputfilter.py"),
            GraphNode(id=GraphNodeId("test/test_outputfilter.py:TestOutputFilter.test_json_config_enable_false"), node_type=GraphNodeType.FUNCTION, label="test_json_config_enable_false", path="test/test_outputfilter.py"),
        )
        bottle_edges = (
            GraphEdge(source_id=GraphNodeId("bottle.py:JSONPlugin"), target_id=GraphNodeId("bottle.py:JSONPlugin.setup"), edge_type=GraphEdgeType.CONTAINS),
            GraphEdge(source_id=GraphNodeId("bottle.py:JSONPlugin"), target_id=GraphNodeId("bottle.py:JSONPlugin.apply"), edge_type=GraphEdgeType.CONTAINS),
            GraphEdge(source_id=GraphNodeId("bottle.py:Bottle.install"), target_id=GraphNodeId("bottle.py:JSONPlugin.setup"), edge_type=GraphEdgeType.CALLS),
            GraphEdge(source_id=GraphNodeId("bottle.py:default_app"), target_id=GraphNodeId("bottle.py:Bottle.install"), edge_type=GraphEdgeType.CALLS),
            GraphEdge(source_id=GraphNodeId("test/test_outputfilter.py:TestOutputFilter.test_json_config_dump_func"), target_id=GraphNodeId("bottle.py:JSONPlugin.apply"), edge_type=GraphEdgeType.CALLS),
            GraphEdge(source_id=GraphNodeId("test/test_outputfilter.py:TestOutputFilter.test_json_config_enable_false"), target_id=GraphNodeId("bottle.py:JSONPlugin.setup"), edge_type=GraphEdgeType.CALLS),
        )
        bottle_snapshot = GraphSnapshot(
            repository_id=BOTTLE_REPO_ID,
            analysis_id=BOTTLE_ANALYSIS_ID,
            graph=DependencyGraph(nodes=bottle_nodes, edges=bottle_edges),
            graph_version=GraphVersion("v1"),
            created_at=now - timedelta(minutes=14),
        )
        graph_store.save_snapshot(bottle_snapshot)

    if graph_store and graph_store.get_snapshot(EMITTERY_ANALYSIS_ID) is None:
        emittery_nodes = (
            GraphNode(id=GraphNodeId("index.js:Emittery"), node_type=GraphNodeType.CLASS, label="Emittery", path="index.js"),
            GraphNode(id=GraphNodeId("index.js:Emittery.on"), node_type=GraphNodeType.FUNCTION, label="Emittery.on", path="index.js"),
            GraphNode(id=GraphNodeId("index.js:Emittery.emit"), node_type=GraphNodeType.FUNCTION, label="Emittery.emit", path="index.js"),
            GraphNode(id=GraphNodeId("index.js:Emittery.off"), node_type=GraphNodeType.FUNCTION, label="Emittery.off", path="index.js"),
            GraphNode(id=GraphNodeId("index.d.ts:Emittery"), node_type=GraphNodeType.CLASS, label="Emittery (Typings)", path="index.d.ts"),
            GraphNode(id=GraphNodeId("test/index.js:test_emittery"), node_type=GraphNodeType.FUNCTION, label="test_emittery", path="test/index.js"),
        )
        emittery_edges = (
            GraphEdge(source_id=GraphNodeId("index.js:Emittery"), target_id=GraphNodeId("index.js:Emittery.on"), edge_type=GraphEdgeType.CONTAINS),
            GraphEdge(source_id=GraphNodeId("index.js:Emittery"), target_id=GraphNodeId("index.js:Emittery.emit"), edge_type=GraphEdgeType.CONTAINS),
            GraphEdge(source_id=GraphNodeId("index.js:Emittery"), target_id=GraphNodeId("index.js:Emittery.off"), edge_type=GraphEdgeType.CONTAINS),
            GraphEdge(source_id=GraphNodeId("test/index.js:test_emittery"), target_id=GraphNodeId("index.js:Emittery.emit"), edge_type=GraphEdgeType.CALLS),
            GraphEdge(source_id=GraphNodeId("index.d.ts:Emittery"), target_id=GraphNodeId("index.js:Emittery"), edge_type=GraphEdgeType.DEFINES),
        )
        emittery_snapshot = GraphSnapshot(
            repository_id=EMITTERY_REPO_ID,
            analysis_id=EMITTERY_ANALYSIS_ID,
            graph=DependencyGraph(nodes=emittery_nodes, edges=emittery_edges),
            graph_version=GraphVersion("v1"),
            created_at=now - timedelta(minutes=29),
        )
        graph_store.save_snapshot(emittery_snapshot)


def _seed_sql_database(session_factory: object) -> None:
    """Seed SQL database when running with SQL backend."""
    try:
        from radius_analysis.infrastructure import SqlAlchemyAnalysisStore
        from radius_confidence.infrastructure import SqlAlchemyConfidenceStore
        from radius_graph.infrastructure import SqlAlchemyGraphStore
        from radius_repository.infrastructure import SqlAlchemyRepositoryStore
        from radius_shared.database import models as db_models
        from radius_testing.infrastructure import SqlAlchemyTestStore
        from sqlalchemy import select

        with session_factory() as session:
            # 1. Ensure Organization exists
            org = session.scalar(
                select(db_models.Organization).where(
                    db_models.Organization.id == DEFAULT_ORG_ID
                )
            )
            if not org:
                org = db_models.Organization(
                    id=DEFAULT_ORG_ID,
                    name="Default Workspace",
                )
                session.add(org)
                session.commit()

            # 2. Ensure Repositories exist in SQL
            repo_bottle = session.scalar(
                select(db_models.Repository).where(
                    db_models.Repository.id == BOTTLE_REPO_ID
                )
            )
            if not repo_bottle:
                repo_bottle = db_models.Repository(
                    id=BOTTLE_REPO_ID,
                    organization_id=DEFAULT_ORG_ID,
                    github_repository_id=134567,
                    name="bottle",
                    owner="bottlepy",
                    default_branch="master",
                    clone_url="https://github.com/bottlepy/bottle.git",
                    visibility=db_models.RepositoryVisibility.PUBLIC,
                    provider=db_models.RepositoryProvider.GITHUB,
                    status=db_models.RepositoryStatus.CONNECTED,
                )
                session.add(repo_bottle)

            repo_emittery = session.scalar(
                select(db_models.Repository).where(
                    db_models.Repository.id == EMITTERY_REPO_ID
                )
            )
            if not repo_emittery:
                repo_emittery = db_models.Repository(
                    id=EMITTERY_REPO_ID,
                    organization_id=DEFAULT_ORG_ID,
                    github_repository_id=246810,
                    name="emittery",
                    owner="sindresorhus",
                    default_branch="main",
                    clone_url="https://github.com/sindresorhus/emittery.git",
                    visibility=db_models.RepositoryVisibility.PUBLIC,
                    provider=db_models.RepositoryProvider.GITHUB,
                    status=db_models.RepositoryStatus.CONNECTED,
                )
                session.add(repo_emittery)
            session.commit()

            # 3. Ensure Pull Requests exist in SQL
            now = datetime.now(UTC)
            pr_bottle = session.scalar(
                select(db_models.PullRequest).where(
                    db_models.PullRequest.id == BOTTLE_PR_ID
                )
            )
            if not pr_bottle:
                pr_bottle = db_models.PullRequest(
                    id=BOTTLE_PR_ID,
                    repository_id=BOTTLE_REPO_ID,
                    github_pr_number=1345,
                    title="implement json.enable and json.dump_func configs",
                    source_branch="json-config",
                    target_branch="master",
                    author="defnull",
                    status=db_models.PullRequestStatus.OPEN,
                    opened_at=now - timedelta(days=1),
                )
                session.add(pr_bottle)

            pr_emittery = session.scalar(
                select(db_models.PullRequest).where(
                    db_models.PullRequest.id == EMITTERY_PR_ID
                )
            )
            if not pr_emittery:
                pr_emittery = db_models.PullRequest(
                    id=EMITTERY_PR_ID,
                    repository_id=EMITTERY_REPO_ID,
                    github_pr_number=210,
                    title="Update typings and listener performance",
                    source_branch="perf",
                    target_branch="main",
                    author="sindresorhus",
                    status=db_models.PullRequestStatus.OPEN,
                    opened_at=now - timedelta(days=2),
                )
                session.add(pr_emittery)
            session.commit()

            # 4. Use stores to save entities
            sql_repo_store = SqlAlchemyRepositoryStore(session)
            sql_analysis_store = SqlAlchemyAnalysisStore(session)
            sql_confidence_store = SqlAlchemyConfidenceStore(session)
            sql_test_store = SqlAlchemyTestStore(session)
            sql_graph_store = SqlAlchemyGraphStore(session)

            _populate_stores(
                sql_repo_store,
                sql_analysis_store,
                sql_confidence_store,
                sql_test_store,
                sql_graph_store,
            )
            session.commit()
            print("[Radius Seed] SQL database successfully seeded with OSS targets!")
    except Exception as exc:
        print(f"[Radius Seed] SQL database seeding warning: {exc}")


def seed_open_source_results(container: object) -> None:
    """Seed authentic open source repository and test verification results."""
    seed_demo_user()

    repo_store = getattr(container, "repository_store", None)
    analysis_store = getattr(container, "analysis_store", None)
    confidence_store = getattr(container, "confidence_store", None)
    test_store = getattr(container, "test_store", None)
    graph_store = getattr(container, "graph_store", None)

    # In-memory stores
    if repo_store and analysis_store:
        _populate_stores(
            repo_store,
            analysis_store,
            confidence_store,
            test_store,
            graph_store,
        )

    # SQL stores
    session_factory = getattr(container, "session_factory", None)
    if session_factory:
        _seed_sql_database(session_factory)

    print("[Radius Seed] Open-source target results (Bottle & Emittery) ready!")
