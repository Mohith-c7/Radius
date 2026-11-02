"""Shared helpers for the IN-09 gold annotation kit (stdlib only).

Used by ``gold_sample.py``, ``gold_annotate.py``, ``gold_agreement.py`` and
``gold_validate.py``. Defines the on-disk layout, source-text canonicalisation,
hashing, a small JSON-schema checker and the semantic validators for
``sources.json``, ``annotator-<id>.json`` and ``adjudicated.json``.

Layout (``benchmarks/gold/intent``)::

    schema.json
    <pr-id>/sources.json          # stored source texts + sha256 + digest
    <pr-id>/annotator-<id>.json   # one independent pass
    <pr-id>/adjudicated.json      # final gold for the PR

Span semantics are those of ``radius_intent.domain.Span``: half-open
``[start, end)`` over Python ``str`` indices (Unicode code points) of the stored
text. See ``docs/research/annotation/GUIDELINES.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "benchmarks" / "gold" / "intent"
SCHEMA_PATH = GOLD_DIR / "schema.json"

SCHEMA_VERSION = "radius-intent-gold-v1"
SOURCES_SCHEMA_VERSION = "radius-intent-gold-sources-v1"
GUIDELINES_VERSION = "gl-0.1"
TOOL_VERSION = "gold-kit-0.1"

#: Annotation categories (IN-05); ``unrated`` is not a valid human label.
TESTABILITY = (
    "behavioral_testable",
    "structural_checkable",
    "non_functional_measurable",
    "subjective_or_vague",
    "untestable_external",
)
SOURCE_KINDS = (
    "pr_body",
    "pr_title",
    "issue",
    "commit_message",
    "spec_file",
    "agent_prompt",
    "comment",
)
RESOLUTIONS = ("agreed", "take_a", "take_b", "merged", "added", "dropped", "pending")

#: Maximum stored length of one source (matches the IN-07 64 KiB repository limit).
MAX_SOURCE_CHARS = 60_000

PR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")
ANNOTATOR_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
#: Annotator ids that would pass system output off as human gold.
RESERVED_ANNOTATOR_PREFIXES = ("radius", "system", "llm", "bot", "extractor")

_MARKER_PREFIX = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|\[[ xX]\]|-\s*\[[ xX]\])")


class GoldError(ValueError):
    """Invalid gold data or tool usage."""


# --------------------------------------------------------------------------
# Identifiers, text, hashes
# --------------------------------------------------------------------------


def pr_id_for(repo: str, number: int) -> str:
    """``owner/name`` + 12 -> ``owner__name__pr12`` (filesystem and URL safe)."""
    owner, _, name = repo.partition("/")
    pid = f"{owner}__{name}__pr{int(number)}".replace("/", "_")
    check_pr_id(pid)
    return pid


def check_pr_id(pr_id: str) -> str:
    if not isinstance(pr_id, str) or not PR_ID_RE.match(pr_id) or ".." in pr_id:
        raise GoldError(f"invalid pr id: {pr_id!r}")
    return pr_id


def check_annotator_id(annotator_id: str, *, allow_reserved: bool = False) -> str:
    if not isinstance(annotator_id, str) or not ANNOTATOR_RE.match(annotator_id):
        raise GoldError(f"invalid annotator id {annotator_id!r}: use [a-z0-9_-], <= 32 chars")
    if not allow_reserved and annotator_id.startswith(RESERVED_ANNOTATOR_PREFIXES):
        raise GoldError(
            f"annotator id {annotator_id!r} is reserved for system output; "
            "human gold must not be attributed to a tool"
        )
    return annotator_id


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_text(text: str) -> str:
    """Fallback source canonicalisation used when the product sanitiser is absent.

    CRLF/CR -> LF, drop NUL, drop Unicode format characters (category Cf, the
    same class ``radius_intent.normalize_text`` drops). No NFKC, no casefold and
    no whitespace collapsing: the extractors are line oriented (lists, headings,
    fences) and must see the original line structure. Idempotent.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def is_canonical(text: str) -> bool:
    return (
        "\r" not in text
        and "\x00" not in text
        and all(unicodedata.category(ch) != "Cf" for ch in text)
        and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)
    )


def sources_digest(sources: list[dict]) -> str:
    """sha256 over ``source_id TAB kind TAB text_sha256`` lines sorted by id."""
    rows = sorted(f"{s['source_id']}\t{s['kind']}\t{s['text_sha256']}" for s in sources)
    return sha256_text("\n".join(rows))


def make_source(
    source_id: str,
    kind: str,
    raw_text: str,
    *,
    text: str | None = None,
    fetched_at: str | None = None,
    origin_url: str | None = None,
    truncated: bool = False,
    suspicious_content_removed: bool = False,
) -> dict:
    """Build a ``source`` dict. ``text`` defaults to ``canonicalize_text(raw_text)``."""
    stored = canonicalize_text(raw_text) if text is None else text
    src = {
        "source_id": source_id,
        "kind": kind,
        "text": stored,
        "text_sha256": sha256_text(stored),
        "raw_text_sha256": sha256_text(raw_text),
        "length": len(stored),
        "truncated": bool(truncated),
        "suspicious_content_removed": bool(suspicious_content_removed),
    }
    if fetched_at:
        src["fetched_at"] = fetched_at
    if origin_url:
        src["origin_url"] = origin_url
    return src


def sanitize_for_gold(raw: str, *, source_id: str, kind: str) -> tuple[str, str, dict]:
    """Return ``(stored_text, sanitizer_name, flags)``.

    Uses the product sanitiser (``radius_shared.llm_guard.sanitize_untrusted``)
    when importable, so the gold text equals what the extractor sees in
    production; otherwise ``canonicalize_text`` plus a length cap. CRLF is
    normalised first in both cases.
    """
    raw_lf = raw.replace("\r\n", "\n").replace("\r", "\n")
    try:
        from radius_shared.llm_guard.sanitize import sanitize_untrusted  # type: ignore

        safe_id = re.sub(r"[^A-Za-z0-9_.:\-]", "_", source_id)[:64] or "src"
        res = sanitize_untrusted(
            raw_lf, source_id=safe_id, kind=kind, max_length=MAX_SOURCE_CHARS
        )
        text = canonicalize_text(res.text)
        codes = res.finding_codes()
        flags = {
            "truncated": "truncated" in codes,
            "suspicious_content_removed": bool(
                codes & {"html_comment", "zero_width", "bidi_control", "unicode_tag", "control_char"}
            ),
        }
        return text, "radius_shared.llm_guard.sanitize_untrusted+canonicalize", flags
    except ImportError:
        text = canonicalize_text(raw_lf)
        truncated = len(text) > MAX_SOURCE_CHARS
        if truncated:
            text = text[:MAX_SOURCE_CHARS]
        return text, "canonicalize_text", {
            "truncated": truncated,
            "suspicious_content_removed": text != raw_lf,
        }


# --------------------------------------------------------------------------
# JSON IO
# --------------------------------------------------------------------------


def read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dumps(doc: object) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_json_atomic(path: Path, doc: object) -> None:
    """Write via a temp file and ``os.replace`` so a crash never truncates."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(doc))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def pr_dir(gold_dir: Path, pr_id: str) -> Path:
    return Path(gold_dir) / check_pr_id(pr_id)


def list_pr_ids(gold_dir: Path) -> list[str]:
    root = Path(gold_dir)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "sources.json").exists()
    )


def annotator_files(gold_dir: Path, pr_id: str) -> dict[str, Path]:
    """annotator id -> path for ``annotator-<id>.json`` files of a PR."""
    out: dict[str, Path] = {}
    d = pr_dir(gold_dir, pr_id)
    for p in sorted(d.glob("annotator-*.json")):
        out[p.stem[len("annotator-"):]] = p
    return out


# --------------------------------------------------------------------------
# JSON-schema subset checker ($ref, type, const, enum, pattern, required,
# properties, additionalProperties, items, minimum, oneOf)
# --------------------------------------------------------------------------

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return read_json(path)


def _type_ok(value, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise GoldError(f"unsupported $ref {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def check_schema(value, schema: dict, root: dict, path: str = "$") -> list[str]:
    if "$ref" in schema:
        return check_schema(value, _resolve(schema["$ref"], root), root, path)
    errors: list[str] = []
    if "oneOf" in schema:
        results = [check_schema(value, s, root, path) for s in schema["oneOf"]]
        ok = [r for r in results if not r]
        if len(ok) != 1:
            best = min(results, key=len)
            return [f"{path}: matches {len(ok)} of {len(results)} alternatives"] + best[:3]
        return []
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, n) for n in names):
            return [f"{path}: expected {names}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors.extend(check_schema(value[key], sub, root, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected property '{key}'")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(check_schema(item, schema["items"], root, f"{path}[{i}]"))
    return errors


def _def_schema(name: str, schema: dict | None = None) -> tuple[dict, dict]:
    root = schema or load_schema()
    return root["$defs"][name], root


# --------------------------------------------------------------------------
# Semantic validation
# --------------------------------------------------------------------------


def validate_sources_doc(doc: dict, schema: dict | None = None) -> list[str]:
    """Errors for a ``sources.json`` document (empty list = valid)."""
    sub, root = _def_schema("sourcesFile", schema)
    errors = check_schema(doc, sub, root)
    if errors:
        return errors
    seen: set[str] = set()
    redistributable = doc.get("text_redistributable", True)
    for i, s in enumerate(doc["sources"]):
        sid = s["source_id"]
        if sid in seen:
            errors.append(f"sources[{i}]: duplicate source_id {sid}")
        seen.add(sid)
        text = s["text"]
        if text is None:
            if redistributable:
                errors.append(f"sources[{i}] {sid}: text is null but text_redistributable is true")
            continue
        if not is_canonical(text):
            errors.append(f"sources[{i}] {sid}: text is not canonical (CR, NUL, Cf or surrogate)")
        if sha256_text(text) != s["text_sha256"]:
            errors.append(f"sources[{i}] {sid}: text_sha256 does not match text")
        if len(text) != s["length"]:
            errors.append(f"sources[{i}] {sid}: length {s['length']} != {len(text)}")
    if sources_digest(doc["sources"]) != doc["sources_digest"]:
        errors.append("sources_digest does not match the sources")
    return errors


def _span_errors(span: dict, texts: dict[str, str | None], where: str) -> list[str]:
    sid = span["source_id"]
    if sid not in texts:
        return [f"{where}: unknown source_id {sid}"]
    text = texts[sid]
    if text is None:
        return []
    if span["end"] <= span["start"]:
        return [f"{where}: end must be greater than start"]
    if span["end"] > len(text):
        return [f"{where}: span [{span['start']},{span['end']}) outside source of length {len(text)}"]
    return []


def validate_annotation_doc(
    doc: dict,
    sources_doc: dict | None = None,
    *,
    schema: dict | None = None,
    require_complete: bool = False,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for an annotator or adjudicated document.

    With ``sources_doc`` the spans are verified against the stored texts
    (bounds, trimmed, text equals slice) and ``sources_digest`` must match.
    ``require_complete`` additionally demands status ``complete``.
    """
    sub, root = _def_schema("annotationFile", schema)
    errors = check_schema(doc, sub, root)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    kind = doc["kind"]
    status = doc["status"]
    adjudicated = kind == "adjudicated"
    if adjudicated:
        if "adjudicator_id" not in doc:
            errors.append("adjudicated file needs adjudicator_id")
        annotators = doc.get("annotators", [])
        if len(annotators) != 2 or len(set(annotators)) != 2:
            errors.append("adjudicated file needs two distinct annotators")
        if doc.get("adjudicator_id") in annotators:
            errors.append("adjudicator must not be one of the two annotators")
    else:
        if "annotator_id" not in doc:
            errors.append("annotation file needs annotator_id")
        if status == "skeleton":
            errors.append("only adjudicated files can be skeletons")
        if "adjudicator_id" in doc:
            errors.append("annotation file must not carry adjudicator_id")
    if require_complete and status != "complete":
        errors.append(f"status is {status!r}, expected 'complete'")

    texts: dict[str, str | None] | None = None
    if sources_doc is not None:
        if doc["sources_digest"] != sources_doc["sources_digest"]:
            errors.append("sources_digest differs from sources.json (sources changed after annotation)")
        if doc["pr_id"] != sources_doc["pr_id"]:
            errors.append("pr_id differs from sources.json")
        texts = {s["source_id"]: s["text"] for s in sources_doc["sources"]}

    ids: set[str] = set()
    seen_spans: dict[tuple, tuple] = {}
    for i, c in enumerate(doc["criteria"]):
        where = f"criteria[{i}] {c['id']}"
        if c["id"] in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(c["id"])
        res = c.get("resolution")
        if adjudicated:
            if res is None:
                errors.append(f"{where}: adjudicated criteria need a resolution")
            elif res == "pending" and status == "complete":
                errors.append(f"{where}: pending item in a complete adjudication")
        elif res is not None:
            errors.append(f"{where}: resolution only allowed in adjudicated files")
        pending = res == "pending"
        dropped = res == "dropped"
        if not pending and not dropped:
            if c["testability"] is None:
                errors.append(f"{where}: testability required")
            if c["text"] is None and c["explicit"] and texts is not None and sources_doc.get(
                "text_redistributable", True
            ):
                errors.append(f"{where}: text required")
        if c["testability"] == "unrated":
            errors.append(f"{where}: 'unrated' is not a human label")
        if c["explicit"]:
            span = c.get("span")
            if span is None:
                if not pending and not dropped:
                    errors.append(f"{where}: explicit criterion needs a span")
                continue
            if c.get("evidence"):
                errors.append(f"{where}: explicit criteria have no evidence spans")
            if texts is not None:
                span_errs = _span_errors(span, texts, where)
                errors.extend(span_errs)
                stext = texts.get(span["source_id"])
                if not span_errs and stext is not None:
                    piece = stext[span["start"]: span["end"]]
                    if c["text"] is not None and c["text"] != piece:
                        errors.append(f"{where}: text does not equal the span slice")
                    if not piece.strip():
                        errors.append(f"{where}: span is whitespace only")
                    elif piece != piece.strip():
                        errors.append(f"{where}: span has leading or trailing whitespace")
                    elif _MARKER_PREFIX.match(piece):
                        warnings.append(f"{where}: span starts with list/checkbox markup")
            key = (span["source_id"], span["start"], span["end"])
            if not dropped and not pending:
                prev = seen_spans.get(key)
                if prev is not None and not (
                    c.get("compound_group") and prev[1] == c.get("compound_group")
                ):
                    errors.append(
                        f"{where}: same span as {prev[0]}; give split criteria a "
                        "shared compound_group or a distinct span"
                    )
                seen_spans.setdefault(key, (c["id"], c.get("compound_group")))
        else:
            if c.get("span") is not None:
                errors.append(f"{where}: implicit criteria have no span (use evidence)")
            if not (c["text"] or "").strip() and not pending and not dropped:
                errors.append(f"{where}: implicit criterion needs a paraphrase in text")
            if texts is not None:
                for j, ev in enumerate(c.get("evidence", [])):
                    errors.extend(_span_errors(ev, texts, f"{where}.evidence[{j}]"))
    if doc.get("no_recoverable_intent") and any(
        c.get("resolution") != "dropped" for c in doc["criteria"]
    ):
        errors.append("no_recoverable_intent is true but criteria are present")
    if status == "complete" and not adjudicated:
        if doc["well_specified"] is None and not doc["no_recoverable_intent"]:
            errors.append("complete annotation must set well_specified")
    if status == "complete" and adjudicated and doc["well_specified"] is None:
        errors.append("complete adjudication must resolve well_specified")
    if adjudicated and status == "skeleton" and not any(
        c.get("resolution") == "pending" for c in doc["criteria"]
    ):
        warnings.append("skeleton has no pending items; set status to 'complete'")
    return errors, warnings


def load_pr(gold_dir: Path, pr_id: str) -> tuple[dict, dict[str, dict], dict | None]:
    """Return ``(sources_doc, {annotator_id: doc}, adjudicated_or_None)``."""
    d = pr_dir(gold_dir, pr_id)
    src = read_json(d / "sources.json")
    anns = {aid: read_json(p) for aid, p in annotator_files(gold_dir, pr_id).items()}
    adj_path = d / "adjudicated.json"
    return src, anns, (read_json(adj_path) if adj_path.exists() else None)


def validate_pr_dir(gold_dir: Path, pr_id: str, *, require_complete: bool = False,
                    allow_synthetic: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    d = pr_dir(gold_dir, pr_id)
    try:
        src = read_json(d / "sources.json")
    except (OSError, ValueError) as exc:
        return [f"{pr_id}/sources.json: {exc}"], warnings
    errors += [f"{pr_id}/sources.json: {e}" for e in validate_sources_doc(src)]
    if errors:
        return errors, warnings
    if src.get("synthetic") and not allow_synthetic:
        errors.append(f"{pr_id}: synthetic data in a real gold dir (use --allow-synthetic for tests)")
    if src["pr_id"] != pr_id:
        errors.append(f"{pr_id}: pr_id in sources.json is {src['pr_id']!r}")
    for aid, p in annotator_files(gold_dir, pr_id).items():
        try:
            doc = read_json(p)
        except (OSError, ValueError) as exc:
            errors.append(f"{p.name}: {exc}")
            continue
        e, w = validate_annotation_doc(doc, src, require_complete=require_complete)
        errors += [f"{pr_id}/{p.name}: {x}" for x in e]
        warnings += [f"{pr_id}/{p.name}: {x}" for x in w]
        if doc.get("annotator_id") != aid:
            errors.append(f"{pr_id}/{p.name}: annotator_id does not match file name")
        if bool(doc.get("synthetic")) != bool(src.get("synthetic")):
            errors.append(f"{pr_id}/{p.name}: synthetic flag differs from sources.json")
    adj = d / "adjudicated.json"
    if adj.exists():
        try:
            doc = read_json(adj)
        except (OSError, ValueError) as exc:
            errors.append(f"adjudicated.json: {exc}")
        else:
            e, w = validate_annotation_doc(doc, src, require_complete=require_complete)
            errors += [f"{pr_id}/adjudicated.json: {x}" for x in e]
            warnings += [f"{pr_id}/adjudicated.json: {x}" for x in w]
            if doc.get("kind") != "adjudicated":
                errors.append(f"{pr_id}/adjudicated.json: kind must be 'adjudicated'")
    return errors, warnings


# --------------------------------------------------------------------------
# Conflict of interest
# --------------------------------------------------------------------------


def load_conflicts(gold_dir: Path) -> dict:
    """``conflicts.json``: ``{annotator_id: {"repos": [...], "login_sha256": [...]}}``."""
    p = Path(gold_dir) / "conflicts.json"
    return read_json(p) if p.exists() else {}


def has_conflict(conflicts: dict, annotator_id: str, sources_doc: dict) -> str | None:
    """Return a reason string when the annotator must not annotate this PR."""
    entry = conflicts.get(annotator_id)
    if not entry:
        return None
    pr = sources_doc["pr"]
    repos = {r.lower() for r in entry.get("repos", [])}
    if pr["repo"].lower() in repos or pr["repo"].split("/")[0].lower() + "/*" in repos:
        return f"declared conflict with repository {pr['repo']}"
    if pr.get("author_login_sha256") in set(entry.get("login_sha256", [])):
        return "declared conflict: annotator is the PR author"
    return None


def login_hash(login: str) -> str:
    return sha256_text(login.strip().lower())


# --------------------------------------------------------------------------
# Span arithmetic shared by tools
# --------------------------------------------------------------------------


def span_iou(a: dict, b: dict) -> float:
    """Character IoU of two spans; 0 when they name different sources."""
    if a["source_id"] != b["source_id"]:
        return 0.0
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    if inter == 0:
        return 0.0
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union


def new_annotation(pr_id: str, sources_doc: dict, annotator_id: str, *, now: str,
                   blinded: bool = True, synthetic: bool = False) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "annotation",
        "pr_id": pr_id,
        "sources_digest": sources_doc["sources_digest"],
        "annotator_id": annotator_id,
        "status": "in_progress",
        "well_specified": None,
        "well_specified_set_at": None,
        "no_recoverable_intent": False,
        "blinded": blinded,
        "criteria": [],
        "links": [],
        "timing": {"active_seconds": 0, "sessions": 0, "first_opened_at": now},
        "tool": {"name": "gold_annotate", "version": TOOL_VERSION},
        "guidelines_version": GUIDELINES_VERSION,
        "synthetic": synthetic,
    }
