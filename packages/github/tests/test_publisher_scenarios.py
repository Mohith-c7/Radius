"""F-06: publisher behaviour against a stateful fake of GitHub's Checks/Comments API.

Models what the live scenarios assert: one ``Radius confidence`` Check Run per
head SHA that is updated (not duplicated) when re-published, and exactly one
bot comment per pull request that is edited in place across pushes.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from radius_github.publisher import (
    CHECK_RUN_NAME,
    COMMENT_MARKER,
    GitHubAnalysisPublisher,
    GitHubAnalysisReport,
)


class StatefulGitHub:
    def __init__(self) -> None:
        self.check_runs: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, dict[str, Any]] = {}
        self._next = 100
        self.tokens = 0

    def _id(self) -> int:
        self._next += 1
        return self._next

    def create_installation_token(self, installation_id: int):
        self.tokens += 1
        return type("T", (), {"token": "t"})()

    def list_check_runs_for_ref(self, *, ref: str, check_name: str, **_: Any):
        return [
            run
            for run in self.check_runs.values()
            if run["head_sha"] == ref and run["name"] == check_name
        ]

    def create_check_run(self, **kwargs: Any):
        run_id = self._id()
        self.check_runs[run_id] = {
            "id": run_id,
            "started_at": f"2026-11-02T09:{run_id % 60:02d}:00Z",
            **{k: v for k, v in kwargs.items() if k != "token"},
        }
        return self.check_runs[run_id]

    def update_check_run(self, *, check_run_id: int, **kwargs: Any):
        self.check_runs[check_run_id].update({k: v for k, v in kwargs.items() if k != "token"})
        return self.check_runs[check_run_id]

    def list_issue_comments(self, **_: Any):
        return list(self.comments.values())

    def create_issue_comment(self, *, body: str, **_: Any):
        comment_id = self._id()
        self.comments[comment_id] = {"id": comment_id, "body": body, "user": {"type": "Bot"}}
        return self.comments[comment_id]

    def update_issue_comment(self, *, comment_id: int, body: str, **_: Any):
        self.comments[comment_id]["body"] = body
        return self.comments[comment_id]


def _report(sha: str, score: float = 70, status: str = "insufficient_evidence"):
    return GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="o",
        repository_name="r",
        pull_request_number=1,
        head_sha=sha,
        confidence_score=score,
        risk_level="medium",
        summary=f"summary for {sha[:4]}",
        recommendations=(),
        verification_status=status,
    )


def _radius_comments(gh: StatefulGitHub) -> list[dict[str, Any]]:
    return [c for c in gh.comments.values() if COMMENT_MARKER in c["body"]]


def test_in_progress_then_complete_updates_the_same_check_run() -> None:
    gh = StatefulGitHub()
    publisher = GitHubAnalysisPublisher(gh)
    sha = "a" * 40
    publisher.publish_in_progress(installation_id=1, owner="o", repository_name="r", head_sha=sha)
    assert [r["status"] for r in gh.check_runs.values()] == ["in_progress"]
    publisher.publish(installation_id=1, report=_report(sha))
    assert len(gh.check_runs) == 1
    run = next(iter(gh.check_runs.values()))
    assert run["status"] == "completed"
    assert run["name"] == CHECK_RUN_NAME


def test_republishing_same_sha_never_duplicates_check_run_or_comment() -> None:
    gh = StatefulGitHub()
    publisher = GitHubAnalysisPublisher(gh)
    sha = "a" * 40
    for _ in range(3):
        publisher.publish(installation_id=1, report=_report(sha))
    assert len(gh.check_runs) == 1
    assert len(_radius_comments(gh)) == 1


def test_each_push_gets_its_own_check_run_but_the_comment_is_edited_in_place() -> None:
    gh = StatefulGitHub()
    publisher = GitHubAnalysisPublisher(gh)
    shas = ["1" * 40, "2" * 40, "3" * 40]
    for index, sha in enumerate(shas):
        publisher.publish_in_progress(
            installation_id=1, owner="o", repository_name="r", head_sha=sha
        )
        publisher.publish(installation_id=1, report=_report(sha, score=60 + index))
    runs_by_sha = {}
    for run in gh.check_runs.values():
        runs_by_sha.setdefault(run["head_sha"], []).append(run)
    assert {sha: len(runs) for sha, runs in runs_by_sha.items()} == dict.fromkeys(shas, 1)
    assert all(run["status"] == "completed" for run in gh.check_runs.values())
    comments = _radius_comments(gh)
    assert len(comments) == 1
    assert "62/100" in comments[0]["body"]
    assert "summary for 3333" in comments[0]["body"]


def test_failure_after_in_progress_completes_the_check_instead_of_leaving_it_stuck() -> None:
    gh = StatefulGitHub()
    publisher = GitHubAnalysisPublisher(gh)
    sha = "b" * 40
    publisher.publish_in_progress(installation_id=1, owner="o", repository_name="r", head_sha=sha)
    publisher.publish_failure(
        installation_id=1, owner="o", repository_name="r", head_sha=sha, error_summary="boom"
    )
    run = next(iter(gh.check_runs.values()))
    assert (run["status"], run["conclusion"]) == ("completed", "neutral")
    assert len(gh.check_runs) == 1


def test_human_comment_with_marker_is_left_alone_and_bot_comment_created() -> None:
    gh = StatefulGitHub()
    gh.comments[1] = {"id": 1, "body": f"{COMMENT_MARKER} quoted", "user": {"type": "User"}}
    GitHubAnalysisPublisher(gh).publish(installation_id=1, report=_report("c" * 40))
    assert gh.comments[1]["body"].endswith("quoted")
    assert len(gh.comments) == 2


def test_rerun_on_same_sha_reopens_the_completed_check_run_instead_of_adding_one() -> None:
    gh = StatefulGitHub()
    publisher = GitHubAnalysisPublisher(gh)
    sha = "d" * 40
    publisher.publish(installation_id=1, report=_report(sha))
    publisher.publish_in_progress(installation_id=1, owner="o", repository_name="r", head_sha=sha)
    assert [r["status"] for r in gh.check_runs.values()] == ["in_progress"]
    publisher.publish(installation_id=1, report=_report(sha, score=90))
    assert len(gh.check_runs) == 1
    assert next(iter(gh.check_runs.values()))["status"] == "completed"


def test_comment_failure_is_reported_separately_and_leaves_check_completed() -> None:
    import pytest
    from radius_github.publisher import CommentPublishError

    class BrokenComments(StatefulGitHub):
        def list_issue_comments(self, **_: Any):
            raise RuntimeError("comments API down")

    gh = BrokenComments()
    publisher = GitHubAnalysisPublisher(gh)
    sha = "e" * 40
    publisher.publish_in_progress(installation_id=1, owner="o", repository_name="r", head_sha=sha)
    with pytest.raises(CommentPublishError):
        publisher.publish(installation_id=1, report=_report(sha, status="verified"))
    run = next(iter(gh.check_runs.values()))
    assert run["status"] == "completed"
    assert len(gh.check_runs) == 1
