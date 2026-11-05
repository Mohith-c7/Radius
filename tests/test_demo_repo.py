"""scripts/demo_repo.py builds a deterministic demo repository; demo/EXPECTED.md is in sync."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("demo_repo", ROOT / "scripts" / "demo_repo.py")
demo_repo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = demo_repo
_spec.loader.exec_module(demo_repo)


def _git(repo: Path, *args: str) -> str:
    return demo_repo.git(list(args), repo)


def test_build_is_deterministic_and_has_all_branches(tmp_path) -> None:
    first = demo_repo.build_work_repo(tmp_path / "one")
    second = demo_repo.build_work_repo(tmp_path / "two")

    assert first == second
    expected = {"main"}
    for scenario in demo_repo.SCENARIOS:
        expected |= {scenario.base_branch, scenario.branch}
    assert set(first) == expected
    branches = _git(tmp_path / "one", "branch", "--format=%(refname:short)").split()
    assert set(branches) == expected


def test_each_pr_changes_one_module_on_top_of_its_scoped_base(tmp_path) -> None:
    shas = demo_repo.build_work_repo(tmp_path / "w")
    work = tmp_path / "w"
    for scenario in demo_repo.SCENARIOS:
        changed = _git(
            work, "diff", "--name-only", scenario.base_branch, scenario.branch
        ).splitlines()
        assert changed and all(name.startswith(("src/", "tests/")) for name in changed)
        assert len({Path(name).stem.removeprefix("test_") for name in changed}) == 1
        assert _git(work, "rev-parse", f"{scenario.branch}~1") == shas[scenario.base_branch]
        spec = _git(work, "show", f"{scenario.base_branch}:.radius/intent.yml")
        assert spec == demo_repo.combined_intent_spec((scenario,)).strip()
    main_spec = _git(work, "show", "main:.radius/intent.yml")
    assert main_spec.count("- id:") == sum(
        demo_repo.combined_intent_spec((s,)).count("- id:") for s in demo_repo.SCENARIOS
    )


def test_tampered_branch_really_weakens_tests(tmp_path) -> None:
    demo_repo.build_work_repo(tmp_path / "w")
    scenario = demo_repo.SCENARIOS[2]
    diff = _git(tmp_path / "w", "diff", scenario.base_branch, scenario.branch, "--", "tests")
    assert "pytest.mark.skip" in diff
    assert "is not None" in diff


def test_cli_emits_push_commands_without_pushing(tmp_path) -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "demo_repo.py"), "--out", str(tmp_path / "o"),
         "--repo", "someone/radius-demo-test"],
        check=True, capture_output=True, text=True,
    )
    assert "git remote add origin https://github.com/someone/radius-demo-test.git" in done.stdout
    assert "git push -u origin main demo/a-base" in done.stdout
    assert (tmp_path / "o" / "radius-demo.git").is_dir()
    assert (tmp_path / "o" / "PR_BODIES.md").is_file()
    remote = _git(tmp_path / "o" / "work", "remote")
    assert remote == ""  # the script never configures or contacts a remote


def test_expected_markdown_is_in_sync() -> None:
    current = (ROOT / "demo" / "EXPECTED.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == demo_repo.expected_markdown()
