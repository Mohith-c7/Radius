"""Coverage report parser tests."""

from radius_confidence.infrastructure import parse_coverage_report


def test_lcov_parser_preserves_test_file_and_symbol_relationships() -> None:
    report = parse_coverage_report(
        "lcov",
        """TN:tests/test_payment.py
SF:src/payment.py
FN:10,process_payment
FNDA:2,process_payment
DA:10,2
DA:11,0
end_of_record
""",
        "pytest",
    )

    assert report.coverage_percent == 50.0
    assert report.files[0]["test_path"] == "tests/test_payment.py"
    assert report.symbols[0]["symbol"] == "process_payment"


def test_coverage_py_json_parser_preserves_actual_totals_without_inventing_tests() -> None:
    report = parse_coverage_report(
        "coverage-json",
        '{"files":{"src/payment.py":{"summary":{"num_statements":10,"covered_lines":8}}}}',
        "pytest",
    )

    assert report.coverage_percent == 80.0
    assert report.files[0]["path"] == "src/payment.py"
    assert "test_path" not in report.files[0]
