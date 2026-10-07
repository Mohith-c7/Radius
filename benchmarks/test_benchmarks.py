from pathlib import Path
from uuid import uuid4

from radius_confidence.domain.entities import ImpactEvidence, TestEvidence
from radius_confidence.domain.value_objects import CoveragePercent
from radius_confidence.infrastructure.scoring import DeterministicConfidenceScorer
from radius_parser.domain.entities import SourceFile
from radius_parser.domain.enums import SourceLanguage
from radius_parser.domain.value_objects import FileChecksum, SourcePath
from radius_parser.infrastructure.python_parser import PythonAstParser
from radius_testing.domain.entities import TestCase
from radius_testing.domain.enums import TestFramework
from radius_testing.domain.value_objects import TestName, TestPath
from radius_testing.infrastructure.selection import PathBasedTestSelector

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_ast_parser_recall():
    parser = PythonAstParser()
    sample_file = FIXTURES_DIR / "sample.py"
    source_file = SourceFile(
        path=SourcePath("sample.py"),
        language=SourceLanguage.PYTHON,
        checksum=FileChecksum("fake-checksum"),
        absolute_path=sample_file,
    )
    parsed = parser.parse(source_file)
    assert len(parsed.symbols) > 0
    assert any(sym.name.value == "calculate_total" for sym in parsed.symbols)
    assert any(sym.name.value == "OrderProcessor" for sym in parsed.symbols)
    assert any(sym.name.value == "OrderProcessor.add_order" for sym in parsed.symbols)

def test_predictive_test_selection_precision():
    selector = PathBasedTestSelector()
    tests = (
        TestCase(
            id=uuid4(),
            name=TestName("test_sample"),
            path=TestPath("tests/test_sample.py"),
            framework=TestFramework.PYTEST,
        ),
        TestCase(
            id=uuid4(),
            name=TestName("test_other"),
            path=TestPath("tests/test_other.py"),
            framework=TestFramework.PYTEST,
        ),
    )
    changed_files = ("sample.py",)
    selection = selector.select(uuid4(), tests, changed_files)
    
    selected_paths = [t.test_case.path.value for t in selection.selected_tests]
    assert "tests/test_sample.py" in selected_paths
    assert "tests/test_other.py" not in selected_paths

def test_confidence_scoring_completeness_and_verification_status():
    scorer = DeterministicConfidenceScorer()
    
    impact = ImpactEvidence(
        affected_files=2,
        affected_symbols=2,
        affected_modules=1,
        affected_tests=1,
        dependency_depth=1
    )
    
    # Case 1: insufficient evidence (0 tests, but affected files > 0)
    tests_empty = TestEvidence(total_tests=0, passed=0, failed=0, skipped=0, coverage_percent=None)
    result = scorer.score(impact, tests_empty)
    assert result[0] is not None and result[1] is not None
    metrics = result.metrics
    assert metrics["analysis_completeness"] == 50.0
    assert metrics["verification_status"] == "insufficient_evidence"
    
    # Case 2: failed tests
    tests_failed = TestEvidence(total_tests=5, passed=4, failed=1, skipped=0, coverage_percent=CoveragePercent(80))
    result2 = scorer.score(impact, tests_failed)
    assert result2[0] is not None and result2[1] is not None
    metrics2 = result2.metrics
    assert metrics2["verification_status"] == "failed"
    assert metrics2["verification_confidence"] == 50.0

    # Case 3: verified (perfect score, no failures)
    tests_verified = TestEvidence(total_tests=5, passed=5, failed=0, skipped=0, coverage_percent=CoveragePercent(95))
    result3 = scorer.score(impact, tests_verified)
    assert result3[0] is not None and result3[1] is not None
    metrics3 = result3.metrics
    assert metrics3["verification_status"] == "verified"
    assert metrics3["verification_confidence"] == 100.0
    assert metrics3["analysis_completeness"] == 100.0
