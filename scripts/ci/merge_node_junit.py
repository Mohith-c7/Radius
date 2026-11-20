"""Merge per-file Node test-runner JUnit reports into one report with file paths.

Node's ``--test-reporter=junit`` (Node 22) writes ``classname="test"`` and no
``file`` attribute, so Radius cannot tell which test file a case came from and
the upload is not evidence for any selected test. Run each test file with its
own report named ``<test file name>.xml`` (for example ``api.test.mjs.xml``) and
merge them here: every ``<testcase>`` gets ``file`` and ``classname`` set to the
repository-relative test path (``apps/dashboard/tests/api.test.mjs``), the same
form as jest-junit/vitest reports, and each file becomes one ``<testsuite>``.

Usage::

    python scripts/ci/merge_node_junit.py --prefix apps/dashboard/tests \
        --out reports/junit-dashboard.xml reports/node/*.xml

Standard library only. The inputs are reports written by this CI job.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


def _test_path(report: Path, prefix: str) -> str:
    name = report.name.removesuffix(".xml")
    return str(PurePosixPath(prefix.strip("/").replace("\\", "/")) / name)


def merge(reports: list[Path], prefix: str) -> ET.Element:
    root = ET.Element("testsuites")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for report in sorted(reports, key=lambda p: p.name):
        path = _test_path(report, prefix)
        suite = ET.SubElement(root, "testsuite", name=path, file=path)
        counts = dict.fromkeys(totals, 0)
        seconds = 0.0
        for case in ET.parse(report).getroot().iter("testcase"):
            out = ET.SubElement(suite, "testcase", name=case.get("name") or "unnamed")
            out.set("classname", path)
            out.set("file", path)
            if case.get("time"):
                out.set("time", case.get("time"))
                try:
                    seconds += float(case.get("time"))
                except ValueError:
                    pass
            counts["tests"] += 1
            for kind, key in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
                found = case.find(kind)
                if found is not None:
                    child = ET.SubElement(out, kind)
                    if found.get("type"):
                        child.set("type", found.get("type"))
                    if found.get("message"):
                        child.set("message", found.get("message"))
                    counts[key] += 1
                    break
        for key, value in counts.items():
            suite.set(key, str(value))
            totals[key] += value
        suite.set("time", f"{seconds:.3f}")
    for key, value in totals.items():
        root.set(key, str(value))
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", required=True, help="Repository-relative directory of the test files.")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args(argv)
    reports = [report for report in args.reports if report.is_file()]
    if not reports:
        print("merge_node_junit: no report files found", file=sys.stderr)
        return 1
    root = merge(reports, args.prefix)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(args.out, encoding="utf-8", xml_declaration=True)
    print(
        f"merge_node_junit: {len(reports)} files, {root.get('tests')} cases, "
        f"{root.get('failures')} failures -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
