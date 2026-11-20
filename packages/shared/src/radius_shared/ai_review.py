"""AI merge-readiness review: output contract, validation and storage (DEC-041).

The review is an advisory explanation for the developer, written by an LLM from evidence
Radius already computed plus diff excerpts. The rules that keep it honest live here, so the
worker, the API and the publisher share one definition:

* **Fixed shape.** ``{"summary": str, "risks"|"tests"|"missing_evidence"|"next_steps":
  [{"text": str, "files": [str]}]}``. Unknown keys reject the whole reply.
* **Grounded.** Every cited file must be one Radius computed for this analysis (changed
  files, selected tests, files named in the evidence). Unknown citations are removed;
  ``risks`` and ``tests`` items with no valid citation are dropped.
* **No verdict.** Text may not claim a verdict or approval (``verified``, ``safe to merge``,
  ``LGTM`` ...), carry URLs or markup, commands, ``@mentions``, secrets, the prompt nonce
  or system-prompt fragments. Offending items are dropped; an offending summary rejects the
  review. The deterministic verdict, score and check-run conclusion are computed and
  committed before the review exists, and nothing reads the review back into them.
* **Fail closed.** Anything unparsable yields no review (status ``unavailable``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from radius_shared.llm_guard.output import (
    _COMMAND,
    _URL,
    _VERDICT_TEXT,
    contains_secret,
)

PROMPT_VERSION = "ai-review-v1"
FEATURE_FLAG = "RADIUS_FEATURE_AI_REVIEW"
ADVISORY_LABEL = (
    "AI-generated and advisory. It does not change the Radius verdict, score or check "
    "result; verify every point yourself."
)
SECTIONS = ("risks", "tests", "missing_evidence", "next_steps")
CITATION_REQUIRED = frozenset({"risks", "tests"})
MAX_ITEMS = 5
MAX_TEXT_CHARS = 300
MAX_SUMMARY_CHARS = 700
MAX_FILES_PER_ITEM = 5
MAX_RAW_BYTES = 32_768
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"

REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        **{
            name: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "files"],
                    "additionalProperties": False,
                },
            }
            for name in SECTIONS
        },
    },
    "required": ["summary", *SECTIONS],
    "additionalProperties": False,
}

#: Verdict or approval claims. The review explains; Radius alone decides.
_VERDICT_CLAIM = re.compile(
    r"(?i)\b(?:verified|safe\s+to\s+merge|ready\s+to\s+(?:be\s+)?merged?|good\s+to\s+merge"
    r"|ok(?:ay)?\s+to\s+merge|fine\s+to\s+merge|can\s+(?:safely\s+)?be\s+merged|approved?"
    r"|approves|approving|lgtm|ship\s+it|mergeable|green\s+light|all\s+(?:checks|tests)"
    r"\s+(?:pass|passed|are\s+passing))\b"
)
_MENTION = re.compile(r"(?<![\w.`/])@[A-Za-z0-9][A-Za-z0-9-]{0,38}")
_BAD_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}
_WS = re.compile(r"\s+")


class ReviewRejected(ValueError):
    """The whole reply is unusable. ``code`` is a stable identifier."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReviewValidation:
    review: dict[str, Any]
    dropped: tuple[tuple[str, str], ...] = ()


def normalize_path(value: str) -> str:
    path = value.strip().strip("`'\"").replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def text_problem(
    text: str, *, forbidden: Sequence[str], system_prompt: str, max_chars: int
) -> str | None:
    """Why ``text`` may not be shown (stable code), or ``None`` when it may."""

    if not text.strip() or len(text) > max_chars:
        return "limits"
    if contains_secret(text, forbidden):
        return "leak"
    if system_prompt and len(system_prompt) >= 32:
        for i in range(0, len(system_prompt) - 32 + 1, 8):
            if system_prompt[i : i + 32] in text:
                return "leak"
    if any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in text):
        return "charset"
    if _URL.search(text):
        return "url"
    if _COMMAND.search(text):
        return "command"
    if _VERDICT_TEXT.search(text) or _VERDICT_CLAIM.search(text):
        return "verdict_claim"
    if _MENTION.search(text):
        return "mention"
    return None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ReviewRejected("bad_json")
        out[key] = value
    return out


def validate_review_output(
    raw: str,
    *,
    allowed_files: Iterable[str],
    forbidden: Sequence[str] = (),
    system_prompt: str = "",
) -> ReviewValidation:
    """Validate a model reply against the contract; raise :class:`ReviewRejected`."""

    if len(raw.encode("utf-8", "replace")) > MAX_RAW_BYTES:
        raise ReviewRejected("too_large")
    try:
        doc = json.loads(raw.strip(), object_pairs_hook=_no_duplicates)
    except ReviewRejected:
        raise
    except ValueError:
        raise ReviewRejected("bad_json") from None
    if not isinstance(doc, dict) or not set(doc) <= {"summary", *SECTIONS}:
        raise ReviewRejected("schema")
    summary = doc.get("summary")
    if not isinstance(summary, str):
        raise ReviewRejected("schema")
    summary = _WS.sub(" ", summary).strip()
    problem = text_problem(
        summary, forbidden=forbidden, system_prompt=system_prompt, max_chars=MAX_SUMMARY_CHARS
    )
    if problem is not None:
        raise ReviewRejected(f"summary_{problem}")
    allowed = {normalize_path(p) for p in allowed_files if p}
    dropped: list[tuple[str, str]] = []
    out: dict[str, Any] = {"summary": summary}
    for section in SECTIONS:
        items = doc.get(section, [])
        if not isinstance(items, list):
            raise ReviewRejected("schema")
        kept: list[dict[str, Any]] = []
        for item in items:
            if len(kept) >= MAX_ITEMS:
                dropped.append((section, "too_many"))
                break
            if not (
                isinstance(item, dict)
                and set(item) <= {"text", "files"}
                and isinstance(item.get("text"), str)
                and isinstance(item.get("files", []), list)
            ):
                dropped.append((section, "schema"))
                continue
            text = _WS.sub(" ", item["text"]).strip()
            problem = text_problem(
                text, forbidden=forbidden, system_prompt=system_prompt, max_chars=MAX_TEXT_CHARS
            )
            if problem is not None:
                dropped.append((section, problem))
                continue
            files: list[str] = []
            for value in item.get("files", []):
                path = normalize_path(value) if isinstance(value, str) else ""
                if path in allowed and path not in files:
                    files.append(path)
                elif path:
                    dropped.append((section, "unknown_file"))
            files = files[:MAX_FILES_PER_ITEM]
            if section in CITATION_REQUIRED and not files:
                dropped.append((section, "uncited"))
                continue
            kept.append({"text": text, "files": files})
        out[section] = kept
    return ReviewValidation(out, tuple(dropped))


# --------------------------------------------------------------------------
# storage


@dataclass(frozen=True)
class StoredAiReview:
    organization_id: UUID
    analysis_id: UUID
    status: str
    reason_code: str | None
    provider: str | None
    model: str | None
    prompt_version: str
    review: Mapping[str, Any] | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, Any]:
        """The API / dashboard shape. Always labelled advisory."""

        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        body: dict[str, Any] = {
            "analysis_id": str(self.analysis_id),
            "status": self.status,
            "reason_code": self.reason_code,
            "advisory": True,
            "ai_generated": True,
            "label": ADVISORY_LABEL,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": created.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        review = dict(self.review or {})
        body["summary"] = review.get("summary") if self.status == STATUS_OK else None
        for section in SECTIONS:
            body[section] = list(review.get(section) or []) if self.status == STATUS_OK else []
        body["notes"] = dict(review.get("notes") or {})
        return body


class AiReviewRepository(Protocol):
    def get(self, organization_id: UUID, analysis_id: UUID) -> StoredAiReview | None: ...

    def save(self, review: StoredAiReview) -> None: ...


class InMemoryAiReviewRepository:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, UUID], StoredAiReview] = {}

    def get(self, organization_id: UUID, analysis_id: UUID) -> StoredAiReview | None:
        return self._rows.get((organization_id, analysis_id))

    def save(self, review: StoredAiReview) -> None:
        self._rows[(review.organization_id, review.analysis_id)] = review


class SqlAiReviewRepository:
    """Every query is filtered by ``organization_id`` (tenant isolation)."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, organization_id: UUID, analysis_id: UUID) -> StoredAiReview | None:
        from radius_shared.database.ai_review import AnalysisAiReviewRow

        row = (
            self._session.query(AnalysisAiReviewRow)
            .filter_by(organization_id=organization_id, analysis_id=analysis_id)
            .one_or_none()
        )
        if row is None:
            return None
        return StoredAiReview(
            organization_id=row.organization_id,
            analysis_id=row.analysis_id,
            status=row.status,
            reason_code=row.reason_code,
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            review=row.review,
            created_at=row.created_at,
        )

    def save(self, review: StoredAiReview) -> None:
        """Insert or replace the analysis' row (the caller commits)."""

        from radius_shared.database.ai_review import AnalysisAiReviewRow

        row = (
            self._session.query(AnalysisAiReviewRow)
            .filter_by(analysis_id=review.analysis_id)
            .one_or_none()
        )
        if row is not None and row.organization_id != review.organization_id:
            raise ValueError("analysis belongs to another organization")
        if row is None:
            row = AnalysisAiReviewRow(
                organization_id=review.organization_id, analysis_id=review.analysis_id
            )
            self._session.add(row)
        row.status = review.status
        row.reason_code = review.reason_code
        row.provider = review.provider
        row.model = review.model
        row.prompt_version = review.prompt_version
        row.review = dict(review.review) if review.review is not None else None
        row.created_at = review.created_at
        self._session.flush()


__all__ = [
    "ADVISORY_LABEL",
    "CITATION_REQUIRED",
    "FEATURE_FLAG",
    "PROMPT_VERSION",
    "REVIEW_JSON_SCHEMA",
    "SECTIONS",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "AiReviewRepository",
    "InMemoryAiReviewRepository",
    "ReviewRejected",
    "ReviewValidation",
    "SqlAiReviewRepository",
    "StoredAiReview",
    "normalize_path",
    "text_problem",
    "validate_review_output",
]
