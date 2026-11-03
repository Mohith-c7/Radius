"""Shared pull sync: idempotence, drafts, bad pull requests, budget, hook."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from radius_github.pull_sync import (
    parse_pull_request_facts,
    pull_request_status,
    sync_open_pull_requests,
)

REPO = SimpleNamespace(id=uuid4(), owner="acme", name="widgets")


def raw(number: int, sha: str, **extra):
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "open",
        "draft": False,
        "user": {"login": "dev"},
        "head": {"ref": "feature", "sha": sha},
        "base": {"ref": "main", "sha": "0" * 40},
        "created_at": "2026-11-02T10:00:00Z",
        **extra,
    }


class Repos:
    def __init__(self) -> None:
        self.ids: dict[int, object] = {}

    def upsert_pull_request(self, command):
        pr_id = self.ids.setdefault(command.github_pr_number, uuid4())
        return SimpleNamespace(id=pr_id, number=command.github_pr_number, status=command.status)


class Analyses:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []

    def list_analyses(self, query):
        return [
            a
            for a in self.items
            if a.pull_request_id == query.pull_request_id
        ]

    def start_analysis(self, command):
        item = SimpleNamespace(
            id=uuid4(),
            pull_request_id=command.pull_request_id,
            commit_sha=command.commit_sha,
            status="pending",
        )
        self.items.append(item)
        return item


def run(repos, analyses, pulls, **kwargs):
    return sync_open_pull_requests(
        repository_service=repos,
        analysis_service=analyses,
        repository=REPO,
        raw_pull_requests=pulls,
        **kwargs,
    )


def test_second_run_is_a_no_op_and_a_new_head_sha_is_analyzed():
    repos, analyses = Repos(), Analyses()
    first = run(repos, analyses, [raw(1, "a" * 40)])
    assert len(first.analysis_ids) == 1
    assert run(repos, analyses, [raw(1, "a" * 40)]).analysis_ids == []
    assert len(run(repos, analyses, [raw(1, "b" * 40)]).analysis_ids) == 1


def test_drafts_are_recorded_but_not_analyzed_and_auto_analyze_false_queues_nothing():
    repos, analyses = Repos(), Analyses()
    out = run(repos, analyses, [raw(1, "a" * 40, draft=True)])
    assert len(out.synced) == 1 and out.analysis_ids == []
    assert run(repos, analyses, [raw(2, "c" * 40)], auto_analyze=False).analysis_ids == []


def test_failed_analysis_is_retried_only_when_asked():
    repos, analyses = Repos(), Analyses()
    run(repos, analyses, [raw(1, "a" * 40)])
    analyses.items[0].status = "failed"
    assert run(repos, analyses, [raw(1, "a" * 40)], retry_failed=False).analysis_ids == []
    assert len(run(repos, analyses, [raw(1, "a" * 40)]).analysis_ids) == 1


def test_a_bad_pull_request_is_skipped_and_the_rest_continue():
    out = run(Repos(), Analyses(), [{"number": 1, "title": "x"}, raw(2, "a" * 40)])
    assert [s["number"] for s in out.skipped] == [1]
    assert "GITHUB_API_ERROR" in out.skipped[0]["reason"]
    assert len(out.analysis_ids) == 1


def test_budget_defers_and_hook_sees_each_started_analysis():
    repos, analyses = Repos(), Analyses()
    seen = []
    pulls = [raw(n, f"{n:040x}") for n in range(1, 5)]
    out = run(repos, analyses, pulls, max_analyses=2, on_analysis=lambda a, p: seen.append(p.number))
    assert len(out.analysis_ids) == 2 and out.deferred == [3, 4] and seen == [1, 2]
    assert len(out.synced) == 4


def test_status_mapping():
    assert pull_request_status(parse_pull_request_facts(raw(1, "a" * 40))) == "open"
    assert pull_request_status(parse_pull_request_facts(raw(1, "a" * 40, state="closed"))) == "closed"
    assert (
        pull_request_status(parse_pull_request_facts(raw(1, "a" * 40, merged=True, state="closed")))
        == "merged"
    )
