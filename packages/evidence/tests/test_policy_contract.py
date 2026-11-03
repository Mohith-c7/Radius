"""Contract 3 and architecture for the policy package."""

from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

import radius_evidence
from radius_evidence.domain.inputs import StageAInput
from radius_evidence.domain.versions import CONTRACT_VERSION
from radius_evidence.policy.apply import (
    RequirementResult,
    apply_tamper_policy,
    audit_digest,
)
from radius_evidence.policy.effective import NO_POLICY
from radius_evidence.policy.repo_config import resolve_repo_config
from radius_evidence.policy.report import policy_block

PKG = Path(radius_evidence.__file__).parent / "policy"
STDLIB = set(sys.stdlib_module_names)


def test_contract_three_is_declared() -> None:
    assert CONTRACT_VERSION == "verdict-v2-contract-5"


def test_stage_a_repo_config_round_trips_and_defaults_empty() -> None:
    sa = StageAInput("a", "r", "0" * 40, "x..y", (), (), (), (), (), (), ())
    assert sa.repo_config == {}
    with_cfg = StageAInput.from_dict({**sa.to_dict(), "repo_config": {"base_ref": "b", "policy": {"status": "absent"}}})
    assert with_cfg.repo_config["policy"]["status"] == "absent"
    assert StageAInput.from_dict(with_cfg.to_dict()) == with_cfg
    old = sa.to_dict()
    old.pop("repo_config")
    assert StageAInput.from_dict(old).repo_config == {}


def test_policy_package_imports_only_stdlib_and_the_pure_evidence_layers() -> None:
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for mod in mods:
                root = mod.split(".")[0]
                assert root in STDLIB or root == "radius_evidence", f"{path.name} imports {mod}"
                if root == "radius_evidence":
                    assert mod.startswith(("radius_evidence.domain", "radius_evidence.policy")), (path.name, mod)


def test_no_policy_means_no_block() -> None:
    res = resolve_repo_config({}, None, date(2026, 11, 2))
    assert res.policy is NO_POLICY
    assert policy_block(res, apply_tamper_policy([], ()), RequirementResult()) == {}


def test_audit_digest_ignores_key_order() -> None:
    assert audit_digest({"a": 1, "b": [1, 2]}) == audit_digest({"b": [1, 2], "a": 1})
