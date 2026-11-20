"""Server-authoritative test evidence manifests and report-slot validation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from radius_testing.domain.entities import ReportedTestCase, TestSelection

MANIFEST_VERSION = 1
PREDICATE_TYPE = "https://github.com/Mohith-c7/Radius/attestations/test-results/v1"
_SAFE_SLOT = re.compile(r"^[a-f0-9]{24}$")


def canonical_json(value: Any) -> bytes:
    """Encode JSON with the single canonical form used for manifest hashes."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def build_manifest(
    analysis_id: UUID,
    repository_id: UUID,
    head_sha: str,
    selection: TestSelection,
) -> tuple[dict[str, Any], str]:
    """Create a deterministic manifest and one authorized JUnit slot per file."""

    grouped: dict[str, list[dict[str, str]]] = {}
    for selected in selection.selected_tests:
        case = selected.test_case
        path = case.path.value.replace("\\", "/").removeprefix("./")
        grouped.setdefault(path, []).append(
            {
                "test_id": str(case.id),
                "path": path,
                "name": case.name.value,
                "framework": case.framework.value,
            }
        )
    slots = []
    tests = []
    for path in sorted(grouped):
        file_tests = sorted(grouped[path], key=lambda item: item["test_id"])
        slot_material = f"{analysis_id}\0{path}\0junit\0default".encode()
        slot_id = hashlib.sha256(slot_material).hexdigest()[:24]
        slots.append(
            {
                "slot_id": slot_id,
                "report_type": "junit",
                "suite_id": path,
                "shard_id": "default",
                "test_ids": [item["test_id"] for item in file_tests],
                "test_paths": [path],
            }
        )
        tests.extend(file_tests)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_VERSION,
        "analysis_id": str(analysis_id),
        "repository_id": str(repository_id),
        "head_sha": head_sha.lower(),
        "tests": tests,
        "slots": slots,
    }
    digest = hashlib.sha256(canonical_json(manifest)).hexdigest()
    return manifest, digest


def validate_cases_for_slot(
    cases: tuple[ReportedTestCase, ...], manifest: dict[str, Any], slot_id: str
) -> bool:
    """Require every reported case to identify a file authorized by the slot."""

    if not _SAFE_SLOT.fullmatch(slot_id):
        return False
    slot = next((item for item in manifest.get("slots", ()) if item.get("slot_id") == slot_id), None)
    if slot is None:
        return False
    allowed = set(slot.get("test_paths", ()))
    return bool(cases) and all(
        _normalize_case_path(case.file) in allowed for case in cases
    )


def _normalize_case_path(value: str | None) -> str:
    if not value:
        return ""
    path = value.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path
