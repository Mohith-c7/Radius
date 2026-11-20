"""End-to-end v1 pipeline on the shapes of production analysis 432c4bb1.

A dashboard PR (Next.js + node:test) used to end "critical": the component with
``Tests & CI`` in its JSX failed to parse, node:test files were
``framework=unknown`` with a target next to the test, and the pending CI run
cost 25 points. The same PR shape must now parse, map the library change to
the test that really imports it (``"../lib/account-model.ts"``), and report
"awaiting CI" with honest gaps for the genuinely untested page.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from radius_analysis.dto import StartAnalysisCommand
from radius_worker.orchestrator import ExecuteAnalysisCommand
from radius_worker.runner import create_local_orchestrator

FILES = {
    "apps/dashboard/package.json": '{"name": "dashboard", "type": "module"}\n',
    "apps/dashboard/lib/account-model.ts": (
        "export type Row = { label: string };\n"
        "export function profileRows(name: string): Row[] {\n"
        "  return [{ label: name }];\n"
        "}\n"
    ),
    "apps/dashboard/lib/other.ts": "export const other = 1;\n",
    "apps/dashboard/components/data-panels.tsx": (
        'import { profileRows } from "../lib/account-model.ts";\n'
        "export function ProfilePanel({ name }: { name: string }) {\n"
        "  return (\n"
        "    <section>\n"
        "      <h2>Tests & CI</h2>\n"
        "      <p>Branches & Verification Targets</p>\n"
        "      {profileRows(name).map((row) => <span key={row.label}>{row.label}</span>)}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    ),
    "apps/dashboard/app/profile/page.tsx": (
        'import { ProfilePanel } from "../../components/data-panels";\n'
        "export default function Page() {\n"
        '  return <ProfilePanel name="me" />;\n'
        "}\n"
    ),
    "apps/dashboard/tests/account-model.test.mjs": (
        'import assert from "node:assert/strict";\n'
        'import test from "node:test";\n'
        'import { profileRows } from "../lib/account-model.ts";\n'
        'test("rows", () => assert.equal(profileRows("a").length, 1));\n'
    ),
    "apps/dashboard/tests/helpers.mjs": "export const fixture = 1;\n",
    "changelog.d/profile.fixed.md": "Profile shows real data.\n",
}


def _diff(paths: tuple[str, ...]) -> str:
    chunks = []
    for path in paths:
        chunks.append(
            f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            "@@ -1,1 +1,2 @@\n line\n+changed\n"
        )
    return "".join(chunks)


def _run(tmp_path: Path, changed: tuple[str, ...]):
    for relative, text in FILES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    orchestrator = create_local_orchestrator()
    orchestrator._execute_tests = False  # production default: CI runs the tests
    repository_id = uuid4()
    analysis = orchestrator._analysis.start_analysis(
        StartAnalysisCommand(repository_id=repository_id, pull_request_id=uuid4(), commit_sha="b" * 40)
    )
    orchestrator.execute(
        ExecuteAnalysisCommand(
            analysis_id=analysis.id,
            repository_id=repository_id,
            repository_path=tmp_path,
            diff_text=_diff(changed),
        )
    )
    report = orchestrator._confidence.get_report(analysis.id)
    selection = orchestrator._testing.get_selection(analysis.id)
    labels: dict[str, list[str]] = {}
    for item in report.evidence:
        labels.setdefault(item.label, []).append(item.message)
    return report, selection, labels


def test_well_tested_library_change_awaits_ci_and_is_not_high_risk(tmp_path: Path) -> None:
    report, selection, labels = _run(
        tmp_path,
        (
            "apps/dashboard/lib/account-model.ts",
            "apps/dashboard/tests/account-model.test.mjs",
            "changelog.d/profile.fixed.md",
        ),
    )

    assert "parse_failure" not in labels
    assert "unmapped_changed_file" not in labels
    assert labels["covered_changed_file"] == [
        "apps/dashboard/lib/account-model.ts",
        "apps/dashboard/tests/account-model.test.mjs",
    ]
    (selected,) = selection.selected_tests
    assert selected.test.path == "apps/dashboard/tests/account-model.test.mjs"
    assert selected.test.framework == "node_test"
    assert selected.test.target_path == "apps/dashboard/lib/account-model.ts"
    assert report.verification_status == "insufficient_evidence"
    assert labels["verdict_gap"] == [
        "Awaiting CI results for 1 selected test file(s); upload them to verify"
    ]
    assert report.risk_level in {"low", "medium"}
    assert report.risk_level == "medium"  # never "low" before results arrive
    assert report.summary.startswith("Not verified yet")


def test_untested_component_is_reported_as_unmapped_not_as_a_parse_failure(
    tmp_path: Path,
) -> None:
    report, _, labels = _run(
        tmp_path,
        (
            "apps/dashboard/components/data-panels.tsx",
            "apps/dashboard/app/profile/page.tsx",
            "apps/dashboard/lib/account-model.ts",
        ),
    )

    assert "parse_failure" not in labels
    assert sorted(labels["unmapped_changed_file"]) == [
        "apps/dashboard/app/profile/page.tsx",
        "apps/dashboard/components/data-panels.tsx",
    ]
    assert report.verification_status == "insufficient_evidence"
    assert "2 changed file(s) are not reached by any discovered test" in labels["verdict_gap"]
    assert report.risk_level == "high"  # real gaps keep the strict cap; not "critical"
