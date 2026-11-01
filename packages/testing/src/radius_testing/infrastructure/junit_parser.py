"""JUnit and CI test run report parser."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from uuid import UUID, uuid4

try:
    import defusedxml.ElementTree as defused_ET
except ImportError:
    defused_ET = None

from radius_shared.errors import ValidationError

from radius_testing.domain.entities import TestRunResult
from radius_testing.domain.enums import TestRunStatus


class JUnitReportParser:
    """Parser for JUnit XML and JSON test execution reports."""

    def parse(self, content: str | bytes, analysis_id: UUID) -> TestRunResult:
        """Parse test execution report content in JSON or XML format.

        Raises ``ValidationError`` for empty, malformed or non-report content,
        so a broken upload can never be mistaken for a (passing) test run.
        """
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
        else:
            text = str(content)

        stripped = text.strip()
        if not stripped:
            msg = "Test report is empty."
            raise ValidationError(msg)
        try:
            if stripped.startswith(("{", "[")):
                result = self._parse_json(stripped, analysis_id)
            else:
                result = self._parse_xml(stripped, analysis_id)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - any parse failure is a client error
            msg = (
                "Test report could not be parsed as JUnit XML or JSON "
                f"({type(exc).__name__})."
            )
            raise ValidationError(msg) from None
        counts = (result.total_tests, result.passed, result.failed, result.skipped)
        if min(counts) < 0 or result.duration_ms < 0:
            msg = "Test report contains negative test counts or duration."
            raise ValidationError(msg)
        return result

    def _parse_json(self, text: str, analysis_id: UUID) -> TestRunResult:
        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
        if not items or not all(isinstance(item, dict) for item in items):
            msg = "JSON test report must be an object or a non-empty list of objects."
            raise ValidationError(msg)

        if isinstance(data, list):
            total = sum(
                int(item.get("total_tests", item.get("total", 0))) for item in data
            )
            failed = sum(
                int(item.get("failed", item.get("failures", 0))) for item in data
            )
            passed = sum(int(item.get("passed", 0)) for item in data)
            skipped = sum(int(item.get("skipped", 0)) for item in data)
            duration_ms = sum(
                int(item.get("duration_ms", item.get("duration", 0)))
                for item in data
            )
            output = "\n".join(
                str(item.get("output", "")) for item in data if item.get("output")
            )
            coverage_percent = None
        else:
            total_val = data.get("total_tests")
            if total_val is None:
                total_val = data.get("total")
            total = int(total_val) if total_val is not None else None

            failed_val = data.get("failed")
            if failed_val is None:
                failed_val = data.get("failures")
            failed = int(failed_val) if failed_val is not None else 0

            passed_val = data.get("passed")
            passed = int(passed_val) if passed_val is not None else None

            skipped_val = data.get("skipped", 0)
            skipped = int(skipped_val) if skipped_val is not None else 0

            if total is None and passed is not None:
                total = passed + failed + skipped
            elif total is not None and passed is None:
                passed = max(0, total - failed - skipped)
            elif total is None and passed is None:
                total = 0
                passed = 0

            duration_raw = data.get("duration_ms")
            if duration_raw is not None:
                duration_ms = int(float(duration_raw))
            else:
                dur = data.get("duration", 0)
                if isinstance(dur, float) and dur < 1000.0:
                    duration_ms = int(dur * 1000)
                else:
                    duration_ms = int(float(dur))

            coverage_raw = data.get("coverage_percent")
            coverage_percent = (
                float(coverage_raw) if coverage_raw is not None else None
            )
            output = str(data.get("output", ""))

        if (failed == 0 and total > 0) or (total == 0 and failed == 0):
            status = TestRunStatus.PASSED
        else:
            status = TestRunStatus.FAILED

        return TestRunResult(
            id=uuid4(),
            analysis_id=analysis_id,
            status=status,
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_ms=int(duration_ms),
            coverage_percent=coverage_percent,
            output=output,
        )

    def _parse_xml(self, text: str, analysis_id: UUID) -> TestRunResult:
        try:
            if defused_ET is not None:
                root = defused_ET.fromstring(text.encode("utf-8"))
            else:
                root = ET.fromstring(text.encode("utf-8"))  # nosec B314
        except Exception:
            if defused_ET is not None:
                root = defused_ET.fromstring(text)
            else:
                root = ET.fromstring(text)  # nosec B314

        tag = root.tag.lower() if isinstance(root.tag, str) else ""
        if not tag.endswith(("testsuite", "testsuites")) and next(
            root.iter("testcase"), None
        ) is None:
            msg = (
                f"XML report root <{root.tag}> is not a JUnit <testsuite>/<testsuites> "
                "element and contains no <testcase> elements."
            )
            raise ValidationError(msg)

        testsuites = (
            [root]
            if root.tag.lower().endswith("testsuite")
            else list(root.iter("testsuite"))
        )
        testcases = list(root.iter("testcase"))

        failure_outputs: list[str] = []
        tc_failed = 0
        tc_skipped = 0

        for tc in testcases:
            failures = tc.findall("failure") + tc.findall("error")
            if failures:
                tc_failed += 1
                name = tc.attrib.get("name", "")
                classname = tc.attrib.get("classname", "")
                tc_label = (
                    f"{classname}.{name}"
                    if classname and name
                    else (name or classname or "unknown_test")
                )
                for fail in failures:
                    msg = fail.attrib.get("message", "")
                    body = (fail.text or "").strip()
                    detail = f"{tc_label}: {msg}" if msg else tc_label
                    if body:
                        failure_outputs.append(f"{detail}\n{body}")
                    else:
                        failure_outputs.append(detail)
            elif tc.findall("skipped"):
                tc_skipped += 1

        for suite in testsuites:
            for fail in suite.findall("failure") + suite.findall("error"):
                s_name = suite.attrib.get("name", "suite")
                msg = fail.attrib.get("message", "")
                body = (fail.text or "").strip()
                detail = f"{s_name}: {msg}" if msg else s_name
                if body:
                    failure_outputs.append(f"{detail}\n{body}")
                else:
                    failure_outputs.append(detail)

        suite_total: int | None = None
        suite_failures: int | None = None
        suite_skipped: int | None = None

        if "tests" in root.attrib:
            suite_total = int(root.attrib["tests"])
            suite_failures = int(root.attrib.get("failures", 0)) + int(
                root.attrib.get("errors", 0)
            )
            suite_skipped = int(root.attrib.get("skipped", 0))
        elif testsuites and any("tests" in s.attrib for s in testsuites):
            suite_total = sum(
                int(s.attrib.get("tests", 0))
                for s in testsuites
                if "tests" in s.attrib
            )
            suite_failures = sum(
                int(s.attrib.get("failures", 0))
                + int(s.attrib.get("errors", 0))
                for s in testsuites
            )
            suite_skipped = sum(
                int(s.attrib.get("skipped", 0)) for s in testsuites
            )

        if suite_total is not None:
            total = suite_total
            failed = max(suite_failures if suite_failures is not None else 0, tc_failed)
            skipped = max(suite_skipped if suite_skipped is not None else 0, tc_skipped)
        else:
            total = len(testcases)
            failed = tc_failed
            skipped = tc_skipped

        total = max(total, len(testcases))
        passed = max(0, total - failed - skipped)

        tc_durations = [
            float(tc.attrib[k])
            for tc in testcases
            for k in ("time", "duration")
            if k in tc.attrib
        ]
        ts_durations = [
            float(ts.attrib[k])
            for ts in testsuites
            for k in ("time", "duration")
            if k in ts.attrib
        ]

        if tc_durations:
            duration_sec = sum(tc_durations)
        elif ts_durations:
            duration_sec = sum(ts_durations)
        elif "time" in root.attrib:
            duration_sec = float(root.attrib["time"])
        elif "duration" in root.attrib:
            duration_sec = float(root.attrib["duration"])
        else:
            duration_sec = 0.0

        duration_ms = int(round(duration_sec * 1000))
        output = "\n\n".join(failure_outputs)

        if (failed == 0 and total > 0) or (total == 0 and failed == 0):
            status = TestRunStatus.PASSED
        else:
            status = TestRunStatus.FAILED

        return TestRunResult(
            id=uuid4(),
            analysis_id=analysis_id,
            status=status,
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_ms=duration_ms,
            coverage_percent=None,
            output=output,
        )
