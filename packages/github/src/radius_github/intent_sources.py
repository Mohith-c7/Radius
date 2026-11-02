"""Collect raw intent sources for one pull request from GitHub (IN-02).

Sources and their stable ids (no SHA, no delivery id, so criterion ids survive
rebases and new analyses; they match the IN-08 API defaults where one exists):

======================  ==================  ====================================
what                    kind                source id
======================  ==================  ====================================
PR title                ``pr_title``        ``pr-title``
PR body                 ``pr_body``         ``pr-body``
spec file at head SHA   ``spec_file``       ``intent.yml``
commit messages         ``commit_message``  ``commits`` (one source, a section per commit)
linked issue            ``issue``           ``issue:<n>`` or ``issue:<owner>:<repo>:<n>``
maintainer comments     ``comment``         ``issue-comments:<n>`` (opt-in)
======================  ==================  ====================================

The agent task prompt (``agent_prompt`` / ``agent-prompt``) and manual criteria
are submitted through the intent API (IN-08) and are never touched here.

Every missing source is an explicit :class:`SourceOutcome` with a status and a
reason, never an exception: ``PRESENT``, ``ABSENT`` (it is not there for this App:
empty, 404, 410, permission missing) or ``UNAVAILABLE`` (transient: rate limit,
5xx, budget). Fetched text goes through :func:`radius_github.intent_text.prepare_text`.
The order of API calls is PR, commits, spec file, issues, then (opt-in) comments,
so a small budget drops the least important sources first.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote

from radius_intent.domain import IntentSource, IntentSourceKind

from radius_github.intent_links import (
    MAX_LINKED_ISSUES,
    IssueRef,
    collect_linked_issues,
    parse_closing_references,
)
from radius_github.intent_rest import ApiResult, CallBudget, GitHubRestReader
from radius_github.intent_text import prepare_text, strip_commit_trailers

#: Default caps (task IN-02).
MAX_COMMITS = 50
MAX_API_CALLS = 15
MAX_COMMENTS_PER_ISSUE = 5
MAX_COMMENT_CHARS = 4000
MAX_COMMIT_MESSAGE_CHARS = 4000
#: ``.radius/intent.yml`` larger than this is not fetched at all.
MAX_SPEC_BYTES = 1024 * 1024
SPEC_PATH = ".radius/intent.yml"
#: ``author_association`` values whose comments count as maintainer comments.
MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

PR_TITLE_ID = "pr-title"
PR_BODY_ID = "pr-body"
SPEC_ID = "intent.yml"
COMMITS_ID = "commits"
ISSUE_PREFIX = "issue:"
COMMENTS_PREFIX = "issue-comments:"
_MAX_ID = 64


class SourceStatus(StrEnum):
    """What happened when a source was looked up."""

    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


class IntentSourceUnavailableError(Exception):
    """Port-level signal that a fetch failed transiently (not that it is absent)."""


@dataclass(frozen=True)
class SourceOutcome:
    """The result for one source id, with provenance."""

    kind: IntentSourceKind
    source_id: str
    status: SourceStatus
    reason: str | None = None
    source: IntentSource | None = None
    #: ``webhook_payload`` or ``rest_api``.
    origin: str = "rest_api"
    #: Human-readable pointer, for example ``owner/repo#12`` or a commit range.
    reference: str = ""
    #: Sanitizer finding codes (hidden content removed, injection phrases flagged...).
    findings: tuple[str, ...] = ()
    from_cache: bool = False

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable summary without any source text."""
        return {
            "kind": self.kind.value,
            "source_id": self.source_id,
            "status": self.status.value,
            "reason": self.reason,
            "origin": self.origin,
            "reference": self.reference,
            "raw_text_hash": None if self.source is None else self.source.raw_text_hash,
            "truncated": bool(self.source and self.source.truncated),
            "suspicious_content_removed": bool(
                self.source and self.source.suspicious_content_removed
            ),
            "findings": list(self.findings),
            "from_cache": self.from_cache,
        }


@dataclass(frozen=True)
class PullRequestHint:
    """Pull request fields taken from a webhook payload (no network needed)."""

    title: str | None = None
    body: str | None = None
    #: False when the payload had no ``body`` key at all (not merely ``null``).
    has_body: bool = False
    author: str | None = None
    head_sha: str | None = None
    base_ref: str | None = None
    number: int | None = None

    @property
    def complete(self) -> bool:
        """True when title and body are both known without a REST call."""
        return self.title is not None and self.has_body


@dataclass(frozen=True)
class RepoContext:
    """Which pull request to ingest, and with which credentials scope."""

    owner: str
    repo: str
    pr_number: int
    #: The analysis' commit: the spec file is read at this SHA.
    head_sha: str
    #: Cache scope, typically the installation id.
    scope: str = ""


@dataclass(frozen=True)
class CollectorConfig:
    """Knobs for one collection run."""

    include_issue_comments: bool = False
    #: Fetch issues of other repositories named by closing references.
    allow_cross_repo: bool = False
    max_issues: int = MAX_LINKED_ISSUES
    max_commits: int = MAX_COMMITS
    max_comments_per_issue: int = MAX_COMMENTS_PER_ISSUE


@dataclass(frozen=True)
class Collection:
    """All outcomes of one collection run."""

    outcomes: tuple[SourceOutcome, ...]
    diagnostics: tuple[str, ...] = ()
    api_calls: int = 0
    #: True when link discovery was reliable, so linked-issue sources that are no
    #: longer linked may be dropped. False for payload-only and degraded runs.
    complete: bool = False
    stopped_reason: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def outcome(self, source_id: str) -> SourceOutcome | None:
        """Return the outcome for ``source_id``."""
        return next((o for o in self.outcomes if o.source_id == source_id), None)

    def presence(self) -> dict[str, str]:
        """Return ``{source_id: status}`` (the RQ1 'which sources exist' record)."""
        return {o.source_id: o.status.value for o in self.outcomes}


# -- ids ---------------------------------------------------------------------


def issue_source_id(ref: IssueRef, default_owner: str, default_repo: str) -> str:
    """Stable, API-valid id for a linked issue."""
    if (ref.owner.lower(), ref.repo.lower()) == (
        default_owner.lower(),
        default_repo.lower(),
    ):
        return f"{ISSUE_PREFIX}{ref.number}"
    full = f"{ISSUE_PREFIX}{ref.owner}:{ref.repo}:{ref.number}"
    if len(full) <= _MAX_ID:
        return full
    digest = hashlib.sha256(f"{ref.owner}/{ref.repo}".lower().encode()).hexdigest()[:12]
    return f"{ISSUE_PREFIX}x{digest}:{ref.number}"


def comments_source_id(issue_id: str) -> str:
    """Id of the maintainer-comments source belonging to ``issue_id``."""
    suffix = issue_id.removeprefix(ISSUE_PREFIX)
    full = f"{COMMENTS_PREFIX}{suffix}"
    if len(full) <= _MAX_ID:
        return full
    return f"{COMMENTS_PREFIX}x{hashlib.sha256(suffix.encode()).hexdigest()[:16]}"


def is_owned_source_id(source_id: str, kind: IntentSourceKind) -> bool:
    """True for ids ingestion manages and may drop when GitHub no longer has them.

    The spec file is deliberately not owned: an absent ``.radius/intent.yml``
    must not delete a spec an engineer submitted through the API under the same
    default id (the analysis is pinned to one SHA, so the file cannot vanish).
    """
    if kind is IntentSourceKind.PR_TITLE:
        return source_id == PR_TITLE_ID
    if kind is IntentSourceKind.PR_BODY:
        return source_id == PR_BODY_ID
    if kind is IntentSourceKind.COMMIT_MESSAGE:
        return source_id == COMMITS_ID
    if kind is IntentSourceKind.ISSUE:
        return source_id.startswith(ISSUE_PREFIX)
    if kind is IntentSourceKind.COMMENT:
        return source_id.startswith(COMMENTS_PREFIX)
    return False


# -- outcome builders (no network) -----------------------------------------------


def make_outcome(
    kind: IntentSourceKind,
    source_id: str,
    raw: str | None,
    *,
    now: datetime,
    origin: str,
    reference: str = "",
    from_cache: bool = False,
) -> SourceOutcome:
    """Prepare ``raw`` and wrap it: PRESENT, or ABSENT (``empty``) if nothing is left."""
    if raw is None or not raw.strip():
        return SourceOutcome(
            kind, source_id, SourceStatus.ABSENT, "empty", None, origin, reference
        )
    prepared = prepare_text(raw, source_id=source_id, kind=kind.value)
    if prepared.empty:
        return SourceOutcome(
            kind,
            source_id,
            SourceStatus.ABSENT,
            "empty_after_sanitization",
            None,
            origin,
            reference,
            prepared.findings,
        )
    source = IntentSource(
        source_id=source_id,
        kind=kind,
        text=prepared.text,
        raw_text_hash=prepared.raw_text_hash,
        fetched_at=now,
        truncated=prepared.truncated,
        suspicious_content_removed=prepared.suspicious_content_removed,
    )
    return SourceOutcome(
        kind,
        source_id,
        SourceStatus.PRESENT,
        None,
        source,
        origin,
        reference,
        prepared.findings,
        from_cache,
    )


def _status_outcome(
    kind: IntentSourceKind,
    source_id: str,
    result: ApiResult,
    reference: str = "",
) -> SourceOutcome:
    status = (
        SourceStatus.ABSENT if result.kind == "absent" else SourceStatus.UNAVAILABLE
    )
    return SourceOutcome(
        kind, source_id, status, result.reason or "unknown", None, "rest_api", reference
    )


def pull_request_outcomes(
    title: str | None,
    body: str | None,
    *,
    now: datetime,
    origin: str,
    reference: str = "",
) -> tuple[SourceOutcome, SourceOutcome]:
    """Outcomes for the PR title and body."""
    return (
        make_outcome(
            IntentSourceKind.PR_TITLE,
            PR_TITLE_ID,
            title,
            now=now,
            origin=origin,
            reference=reference,
        ),
        make_outcome(
            IntentSourceKind.PR_BODY,
            PR_BODY_ID,
            body,
            now=now,
            origin=origin,
            reference=reference,
        ),
    )


def issue_text(title: object, body: object) -> str:
    """Compose the stored issue text: title, blank line, body."""
    head = title if isinstance(title, str) else ""
    rest = body if isinstance(body, str) else ""
    return f"{head}\n\n{rest}" if rest.strip() else head


def issue_outcome_from_payload(
    ref: IssueRef,
    issue: Mapping[str, Any],
    *,
    default_owner: str,
    default_repo: str,
    now: datetime,
) -> SourceOutcome:
    """Outcome for an issue whose title/body arrived in a webhook payload."""
    source_id = issue_source_id(ref, default_owner, default_repo)
    if "pull_request" in issue:
        return SourceOutcome(
            IntentSourceKind.ISSUE,
            source_id,
            SourceStatus.ABSENT,
            "is_pull_request",
            None,
            "webhook_payload",
            ref.label(),
        )
    return make_outcome(
        IntentSourceKind.ISSUE,
        source_id,
        issue_text(issue.get("title"), issue.get("body")),
        now=now,
        origin="webhook_payload",
        reference=ref.label(),
    )


# -- the collector -----------------------------------------------------------------


class GitHubIntentCollector:
    """Fetch PR, commits, spec file, linked issues (and comments) within a budget."""

    def __init__(
        self,
        reader: GitHubRestReader,
        token_provider: Callable[[], str],
        *,
        config: CollectorConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._token_provider = token_provider
        self._config = config or CollectorConfig()
        self._clock = clock

    # -- public ------------------------------------------------------------
    def collect(
        self,
        ctx: RepoContext,
        *,
        hint: PullRequestHint | None = None,
        known_pr: tuple[SourceOutcome, SourceOutcome] | None = None,
        budget: CallBudget | None = None,
    ) -> Collection:
        """Run the full pass (see module docs for the call order).

        ``hint`` (webhook payload fields) or ``known_pr`` (title/body outcomes
        already recorded for this analysis) spare the REST call for the pull
        request; ``known_pr`` is used only when both outcomes are PRESENT.
        """
        budget = budget or CallBudget(max_calls=MAX_API_CALLS)
        now = self._clock()
        session = _Session(self, ctx, budget, now)
        return session.run(hint, known_pr)

    def fetcher(self, ctx: RepoContext, *, budget: CallBudget | None = None):
        """Return an :class:`IntentSourceFetcher` for this pull request."""
        return GitHubIntentSourceFetcher(self, ctx, budget or CallBudget())

    def now(self) -> datetime:
        """Current time from the injected clock."""
        return self._clock()

    # -- used by _Session ----------------------------------------------------
    @property
    def config(self) -> CollectorConfig:
        """The collection knobs."""
        return self._config

    def get(self, ctx: RepoContext, budget: CallBudget, path: str, **params: Any):
        """GET with a lazily minted installation token."""
        try:
            token = self._token_provider()
        except Exception:  # token errors must degrade, never raise
            return ApiResult("unavailable", reason="token_error")
        return self._reader.get_json(
            path, token=token, budget=budget, scope=ctx.scope, params=params or None
        )


def _repo_path(ctx: RepoContext) -> str:
    return f"/repos/{quote(ctx.owner, safe='')}/{quote(ctx.repo, safe='')}"


class _Session:
    """State of one collection run."""

    def __init__(
        self,
        collector: GitHubIntentCollector,
        ctx: RepoContext,
        budget: CallBudget,
        now: datetime,
    ) -> None:
        self._c = collector
        self._ctx = ctx
        self._budget = budget
        self._now = now
        self._outcomes: list[SourceOutcome] = []
        self._diagnostics: list[str] = []

    @property
    def outcomes(self) -> list[SourceOutcome]:
        """Outcomes gathered so far."""
        return self._outcomes

    def run(
        self,
        hint: PullRequestHint | None,
        known_pr: tuple[SourceOutcome, SourceOutcome] | None = None,
    ) -> Collection:
        ctx = self._ctx
        reference = f"{ctx.owner}/{ctx.repo}#{ctx.pr_number}"
        if known_pr is not None and all(
            o.status is SourceStatus.PRESENT for o in known_pr
        ):
            self._outcomes += list(known_pr)
            body_text, body_known = _text(known_pr[1]), True
        else:
            body_text, body_known = self.pull_request(hint, reference)
        commit_messages, commits_ok = self.commits(reference)
        self.spec_file()
        links, dropped = collect_linked_issues(
            [body_text, *commit_messages],
            default_owner=ctx.owner,
            default_repo=ctx.repo,
            limit=self._c.config.max_issues,
        )
        if dropped:
            self._diagnostics.append(f"linked_issues_truncated:{dropped}")
        issue_ids = self.issues(links)
        self.comments(issue_ids)
        return Collection(
            outcomes=tuple(self._outcomes),
            diagnostics=tuple(self._diagnostics),
            api_calls=self._budget.used,
            complete=body_known and commits_ok,
            stopped_reason=self._budget.tripped,
            fetched_at=self._now,
        )

    # -- individual sources -----------------------------------------------------
    def pull_request(
        self, hint: PullRequestHint | None, reference: str
    ) -> tuple[str, bool]:
        """Add title/body outcomes; return (stored body text, body is known)."""
        if hint is not None and hint.complete:
            title, body = pull_request_outcomes(
                hint.title, hint.body, now=self._now, origin="webhook_payload", reference=reference
            )
            self._outcomes += [title, body]
            return _text(body), True
        result = self._c.get(self._ctx, self._budget, _repo_path(self._ctx) + f"/pulls/{self._ctx.pr_number}")
        if result.ok and isinstance(result.data, dict):
            title, body = pull_request_outcomes(
                result.data.get("title"),
                result.data.get("body"),
                now=self._now,
                origin="rest_api",
                reference=reference,
            )
            title = _mark_cache(title, result.from_cache)
            body = _mark_cache(body, result.from_cache)
            self._outcomes += [title, body]
            head = (result.data.get("head") or {}).get("sha")
            if isinstance(head, str) and head and head != self._ctx.head_sha:
                self._diagnostics.append("head_moved")
            return _text(body), True
        if result.ok:
            result = ApiResult("unavailable", reason="invalid_response")
        self._outcomes += [
            _status_outcome(IntentSourceKind.PR_TITLE, PR_TITLE_ID, result, reference),
            _status_outcome(IntentSourceKind.PR_BODY, PR_BODY_ID, result, reference),
        ]
        return "", False

    def commits(self, reference: str) -> tuple[list[str], bool]:
        """Add the commits outcome; return (messages for link parsing, reliable)."""
        cfg = self._c.config
        result = self._c.get(
            self._ctx,
            self._budget,
            _repo_path(self._ctx) + f"/pulls/{self._ctx.pr_number}/commits",
            per_page=cfg.max_commits,
        )
        if not result.ok or not isinstance(result.data, list):
            if result.ok:
                result = ApiResult("unavailable", reason="invalid_response")
            self._outcomes.append(
                _status_outcome(IntentSourceKind.COMMIT_MESSAGE, COMMITS_ID, result, reference)
            )
            return [], result.kind == "absent"
        sections: list[str] = []
        messages: list[str] = []
        merges = 0
        for item in result.data[: cfg.max_commits]:
            if not isinstance(item, dict):
                continue
            if len(item.get("parents") or ()) > 1:
                merges += 1
                continue
            sha = str(item.get("sha") or "")
            commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            message = strip_commit_trailers(str((commit or {}).get("message") or ""))
            if not message.strip():
                continue
            message = message[:MAX_COMMIT_MESSAGE_CHARS]
            sections.append(f"Commit {sha[:7]}:\n{message}")
            messages.append(message)
        if merges:
            self._diagnostics.append(f"merge_commits_skipped:{merges}")
        if len(result.data) >= cfg.max_commits:
            self._diagnostics.append(f"commits_capped_at:{cfg.max_commits}")
        outcome = make_outcome(
            IntentSourceKind.COMMIT_MESSAGE,
            COMMITS_ID,
            "\n\n".join(sections),
            now=self._now,
            origin="rest_api",
            reference=reference,
            from_cache=result.from_cache,
        )
        self._outcomes.append(outcome)
        return messages, True

    def spec_file(self) -> None:
        ctx = self._ctx
        result = self._c.get(
            ctx,
            self._budget,
            _repo_path(ctx) + "/contents/" + quote(SPEC_PATH, safe="/"),
            ref=ctx.head_sha,
        )
        reference = f"{SPEC_PATH}@{ctx.head_sha[:12]}"
        kind = IntentSourceKind.SPEC_FILE
        if not result.ok:
            self._outcomes.append(_status_outcome(kind, SPEC_ID, result, reference))
            return
        text, reason = _decode_contents(result.data)
        if text is None:
            self._outcomes.append(
                SourceOutcome(kind, SPEC_ID, SourceStatus.ABSENT, reason, None, "rest_api", reference)
            )
            return
        self._outcomes.append(
            make_outcome(
                kind,
                SPEC_ID,
                text,
                now=self._now,
                origin="rest_api",
                reference=reference,
                from_cache=result.from_cache,
            )
        )

    def issues(self, links: Iterable[IssueRef]) -> list[tuple[str, IssueRef, int]]:
        """Fetch each linked issue; return (source id, ref, comment count) of present ones."""
        ctx = self._ctx
        present: list[tuple[str, IssueRef, int]] = []
        for ref in links:
            same_repo = (ref.owner.lower(), ref.repo.lower()) == (
                ctx.owner.lower(),
                ctx.repo.lower(),
            )
            if same_repo:  # canonical spelling for the request path
                ref = IssueRef(ctx.owner, ctx.repo, ref.number)
            source_id = issue_source_id(ref, ctx.owner, ctx.repo)
            reference = ref.label()
            if not same_repo and not self._c.config.allow_cross_repo:
                # No request is made: a PR author must not be able to pull issue
                # text from other repositories the installation can read.
                self._outcomes.append(
                    SourceOutcome(
                        IntentSourceKind.ISSUE,
                        source_id,
                        SourceStatus.ABSENT,
                        "cross_repo_disabled",
                        None,
                        "rest_api",
                        reference,
                    )
                )
                continue
            path = (
                f"/repos/{quote(ref.owner, safe='')}/{quote(ref.repo, safe='')}"
                f"/issues/{ref.number}"
            )
            result = self._c.get(ctx, self._budget, path)
            if not result.ok or not isinstance(result.data, dict):
                if result.ok:
                    result = ApiResult("unavailable", reason="invalid_response")
                self._outcomes.append(
                    _status_outcome(IntentSourceKind.ISSUE, source_id, result, reference)
                )
                continue
            if "pull_request" in result.data:
                self._outcomes.append(
                    SourceOutcome(
                        IntentSourceKind.ISSUE,
                        source_id,
                        SourceStatus.ABSENT,
                        "is_pull_request",
                        None,
                        "rest_api",
                        reference,
                    )
                )
                continue
            outcome = make_outcome(
                IntentSourceKind.ISSUE,
                source_id,
                issue_text(result.data.get("title"), result.data.get("body")),
                now=self._now,
                origin="rest_api",
                reference=reference,
                from_cache=result.from_cache,
            )
            self._outcomes.append(outcome)
            comments = result.data.get("comments")
            if outcome.status is SourceStatus.PRESENT and isinstance(comments, int) and comments > 0:
                present.append((source_id, ref, comments))
        return present

    def comments(self, issues: list[tuple[str, IssueRef, int]]) -> None:
        if not self._c.config.include_issue_comments:
            return
        for issue_id, ref, _count in issues:
            source_id = comments_source_id(issue_id)
            reference = ref.label()
            path = (
                f"/repos/{quote(ref.owner, safe='')}/{quote(ref.repo, safe='')}"
                f"/issues/{ref.number}/comments"
            )
            result = self._c.get(self._ctx, self._budget, path, per_page=30)
            kind = IntentSourceKind.COMMENT
            if not result.ok or not isinstance(result.data, list):
                if result.ok:
                    result = ApiResult("unavailable", reason="invalid_response")
                self._outcomes.append(_status_outcome(kind, source_id, result, reference))
                continue
            text = maintainer_comments_text(
                result.data, limit=self._c.config.max_comments_per_issue
            )
            if not text:
                self._outcomes.append(
                    SourceOutcome(
                        kind,
                        source_id,
                        SourceStatus.ABSENT,
                        "no_maintainer_comments",
                        None,
                        "rest_api",
                        reference,
                    )
                )
                continue
            self._outcomes.append(
                make_outcome(
                    kind,
                    source_id,
                    text,
                    now=self._now,
                    origin="rest_api",
                    reference=reference,
                    from_cache=result.from_cache,
                )
            )


def maintainer_comments_text(comments: Iterable[Any], *, limit: int) -> str:
    """Render comments by OWNER/MEMBER/COLLABORATOR humans, each labeled as a comment."""
    parts: list[str] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if comment.get("author_association") not in MAINTAINER_ASSOCIATIONS:
            continue
        user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
        if (user or {}).get("type") == "Bot":
            continue
        body = comment.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        login = str((user or {}).get("login") or "unknown")
        role = str(comment["author_association"])
        parts.append(f"Comment by @{login} ({role}):\n{body[:MAX_COMMENT_CHARS]}")
        if len(parts) >= limit:
            break
    return "\n\n".join(parts)


def _decode_contents(data: Any) -> tuple[str | None, str]:
    """Decode a contents-API file response; return (text, reason-if-none)."""
    if not isinstance(data, dict):
        return None, "not_a_file"
    if data.get("type") != "file":
        return None, "not_a_file"
    size = data.get("size")
    if isinstance(size, int) and size > MAX_SPEC_BYTES:
        return None, "too_large"
    content = data.get("content")
    if data.get("encoding") != "base64" or not isinstance(content, str) or not content:
        return None, "unreadable"
    try:
        raw = base64.b64decode(content, validate=False)
    except (binascii.Error, ValueError):
        return None, "unreadable"
    return raw.decode("utf-8", "replace"), ""


def _text(outcome: SourceOutcome) -> str:
    return "" if outcome.source is None else outcome.source.text


def _mark_cache(outcome: SourceOutcome, from_cache: bool) -> SourceOutcome:
    if not from_cache:
        return outcome
    return SourceOutcome(
        outcome.kind,
        outcome.source_id,
        outcome.status,
        outcome.reason,
        outcome.source,
        outcome.origin,
        outcome.reference,
        outcome.findings,
        True,
    )


class GitHubIntentSourceFetcher:
    """:class:`radius_intent.interfaces.IntentSourceFetcher` over GitHub.

    ``reference`` per kind: ``pr_title``/``pr_body``: ignored; ``issue``:
    ``owner/repo#n`` or ``#n``; ``spec_file``: ignored; ``commit_message``:
    ignored (the aggregate source). Returns ``None`` when the source is absent;
    raises :class:`IntentSourceUnavailableError` when it could not be determined
    (IN-06 then keeps the previous criteria of that kind).
    """

    def __init__(
        self, collector: GitHubIntentCollector, ctx: RepoContext, budget: CallBudget
    ) -> None:
        self._collector = collector
        self._ctx = ctx
        self._budget = budget

    def fetch(
        self, analysis_id: str, kind: IntentSourceKind, reference: str
    ) -> IntentSource | None:
        """Fetch one source; see the class docs."""
        del analysis_id  # the pull request, not the analysis, names the source
        wanted = self._source_id(kind, reference)
        collector = self._collector
        if kind in (IntentSourceKind.ISSUE, IntentSourceKind.COMMENT):
            links = _single_ref(reference, self._ctx)
        else:
            links = []
        # A one-source run: reuse the session machinery with the cheapest path.
        session = _Session(collector, self._ctx, self._budget, collector.now())
        if kind in (IntentSourceKind.PR_TITLE, IntentSourceKind.PR_BODY):
            session.pull_request(None, "")
        elif kind is IntentSourceKind.COMMIT_MESSAGE:
            session.commits("")
        elif kind is IntentSourceKind.SPEC_FILE:
            session.spec_file()
        elif kind is IntentSourceKind.ISSUE:
            session.issues(links)
        else:
            return None
        outcome = next((o for o in session.outcomes if o.source_id == wanted), None)
        if outcome is None or outcome.status is SourceStatus.ABSENT:
            return None
        if outcome.status is SourceStatus.UNAVAILABLE:
            raise IntentSourceUnavailableError(outcome.reason or "unavailable")
        return outcome.source

    def _source_id(self, kind: IntentSourceKind, reference: str) -> str:
        if kind is IntentSourceKind.PR_TITLE:
            return PR_TITLE_ID
        if kind is IntentSourceKind.PR_BODY:
            return PR_BODY_ID
        if kind is IntentSourceKind.COMMIT_MESSAGE:
            return COMMITS_ID
        if kind is IntentSourceKind.SPEC_FILE:
            return SPEC_ID
        links = _single_ref(reference, self._ctx)
        if not links:
            return ""
        return issue_source_id(links[0], self._ctx.owner, self._ctx.repo)


def _single_ref(reference: str, ctx: RepoContext) -> list[IssueRef]:
    return parse_closing_references(
        f"fixes {reference}", default_owner=ctx.owner, default_repo=ctx.repo
    )


__all__ = [
    "COMMENTS_PREFIX",
    "COMMITS_ID",
    "ISSUE_PREFIX",
    "MAINTAINER_ASSOCIATIONS",
    "MAX_API_CALLS",
    "MAX_COMMITS",
    "PR_BODY_ID",
    "PR_TITLE_ID",
    "SPEC_ID",
    "SPEC_PATH",
    "Collection",
    "CollectorConfig",
    "GitHubIntentCollector",
    "GitHubIntentSourceFetcher",
    "IntentSourceUnavailableError",
    "PullRequestHint",
    "RepoContext",
    "SourceOutcome",
    "SourceStatus",
    "comments_source_id",
    "is_owned_source_id",
    "issue_outcome_from_payload",
    "issue_source_id",
    "issue_text",
    "make_outcome",
    "maintainer_comments_text",
    "pull_request_outcomes",
]
