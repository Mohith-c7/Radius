"""Evidence-based selection behaviour."""

from pathlib import Path
from uuid import uuid4

from radius_testing.domain import TestCase, TestFramework, TestName, TestPath
from radius_testing.infrastructure import PathBasedTestSelector


def _test(path: str, target: str | None = None) -> TestCase:
    from radius_testing.domain import SourcePath

    return TestCase(
        id=uuid4(), name=TestName(Path(path).stem), path=TestPath(path),
        framework=TestFramework.PYTEST,
        target_path=SourcePath(target) if target else None,
    )


def test_static_evidence_selects_related_test_and_records_skipped_test() -> None:
    selection = PathBasedTestSelector().select(
        uuid4(), (_test("tests/test_payment.py", "src/payment.py"), _test("tests/test_profile.py")),
        ("src/payment.py",), changed_symbols=("processPayment",),
    )
    assert [item.test_case.path.value for item in selection.selected_tests] == ["tests/test_payment.py"]
    payment, profile = selection.decisions
    assert payment.decision.value == "selected"
    assert payment.evidence_sources == ("AST_CPG",)
    assert "processPayment" in payment.reason
    assert profile.decision.value == "skipped"


def test_coverage_and_history_are_additive_evidence() -> None:
    selection = PathBasedTestSelector().select(
        uuid4(), (_test("tests/test_payment.py"),), (),
        coverage_evidence={"tests/test_payment.py": ("Runtime coverage executes processPayment().",)},
        history_evidence={"tests/test_payment.py": ("Historical runs covered src/payment.py.",)},
    )
    decision = selection.decisions[0]
    assert decision.decision.value == "selected"
    assert decision.evidence_sources == ("RUNTIME_COVERAGE", "TEST_HISTORY")
    assert decision.relevance_score == 50.0


def test_multiple_evidence_sources_keep_all_actual_details() -> None:
    selection = PathBasedTestSelector().select(
        uuid4(), (_test("tests/test_payment.py", "src/payment.py"),), ("src/payment.py",),
        semantic_evidence={"tests/test_payment.py": ("Semantic analysis links payment retry behaviour.",)},
        coverage_evidence={"tests/test_payment.py": ("Runtime coverage executes charge().",)},
        history_evidence={"tests/test_payment.py": ("3 prior runs affected this file.",)},
    )
    decision = selection.decisions[0]
    assert decision.evidence_sources == ("AST_CPG", "GEMINI_SEMANTIC", "RUNTIME_COVERAGE", "TEST_HISTORY")
    assert decision.relevance_score == 100.0


def test_missing_optional_evidence_does_not_break_existing_selection() -> None:
    selection = PathBasedTestSelector().select(uuid4(), (_test("tests/test_profile.py"),), ("src/other.py",))
    assert selection.selected_tests == ()
    assert selection.decisions[0].decision.value == "skipped"


def test_symbol_evidence_is_recorded_as_reason_tags_for_selected_tests_only() -> None:
    tests = (_test("tests/test_a.py"), _test("tests/test_b.py"))
    selection = PathBasedTestSelector().select(
        uuid4(), tests, ("src/a.py",), affected_file_paths=("tests/test_a.py",),
        symbol_evidence={
            "tests/test_a.py": ("symbol impact: tests/test_a.py::test_x -> src/a.py::f (changed)",),
            "tests/test_b.py": ("must not appear: test was not selected",),
        },
    )
    a, b = selection.decisions
    assert a.decision.value == "selected"
    assert a.evidence_sources == ("AST_CPG", "SYMBOL_IMPACT")
    assert "src/a.py::f" in a.reason
    assert b.decision.value == "skipped"
    assert "must not appear" not in b.reason
