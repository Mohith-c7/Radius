"""``.radius/waivers.yml`` (version 1): strict parsing and validity (VD-05).

A waiver accepts one tamper finding (``finding``), one tamper rule inside a path
scope (``rule`` + ``paths``) or one criterion (``criterion``), for a limited
time, with a reason and an owner. It never reaches a failed CI case or a
``contradicted`` criterion (see ``apply.py``). Expiry is evaluated against the
``today`` the caller passes in; there is no hidden clock. The file is read from
the base branch only (``repo_config.py``), so the PR author cannot waive their
own findings.

Invalid and expired waivers are not silently dropped: they come back in
``ignored`` with a code and a message so the comment and API can show them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from radius_evidence.policy import miniyaml
from radius_evidence.policy.globs import glob_problem
from radius_evidence.policy.miniyaml import Diagnostic, Map, Scalar, Seq

WAIVERS_VERSION = 1
WAIVERS_PATH = ".radius/waivers.yml"

MAX_LIFETIME_DAYS = 90
MIN_REASON_LENGTH = 20
MAX_REASON_LENGTH = 500
MAX_WAIVERS = 200
MAX_PATHS = 20

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_OWNER = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._@/+-]{0,79}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FINDING = re.compile(r"tf_[0-9a-f]{16}")
_RULE = re.compile(r"T\d{3}(?::[a-z0-9_]+)?")
_CRITERION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_KEYS = frozenset(
    {"id", "finding", "rule", "criterion", "reason", "owner", "created", "expires", "paths"}
)
_TARGETS = ("finding", "rule", "criterion")


@dataclass(frozen=True, slots=True)
class Waiver:
    id: str
    kind: str  # finding | rule | criterion
    target: str
    reason: str  # UNTRUSTED text
    owner: str
    created: date
    expires: date
    paths: tuple[str, ...]
    line: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "reason": self.reason,
            "owner": self.owner,
            "created": self.created.isoformat(),
            "expires": self.expires.isoformat(),
            "paths": list(self.paths),
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class IgnoredWaiver:
    """A waiver (or a malformed entry) that does not apply, with the reason."""

    id: str | None
    line: int
    code: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "line": self.line, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class WaiversParse:
    waivers: tuple[Waiver, ...] = ()
    ignored: tuple[IgnoredWaiver, ...] = ()
    errors: tuple[Diagnostic, ...] = ()
    warnings: tuple[Diagnostic, ...] = ()
    #: The file is unusable as a whole; every waiver is ignored (the safe direction).
    structural_failure: bool = False


def _date(text: object) -> date | None:
    if not isinstance(text, str) or not _DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _entry(
    node: Map, seen: set[str], today: date, warnings: list[Diagnostic]
) -> Waiver | IgnoredWaiver:
    for key, line, _ in node.entries:
        if key not in _KEYS:
            warnings.append(Diagnostic(line, f"Unknown key '{key}' is ignored."))

    def raw(key: str) -> object:
        entry = node.get(key)
        return entry[1].value if entry and isinstance(entry[1], Scalar) else None

    wid_raw = raw("id")
    wid = wid_raw if isinstance(wid_raw, str) and _ID.fullmatch(wid_raw) else None
    line = node.line

    def bad(code: str, message: str) -> IgnoredWaiver:
        return IgnoredWaiver(wid, line, code, message)

    if wid is None:
        return bad("invalid_id", "id is required (letters, digits, '.', '_', '-'; up to 64).")
    if wid in seen:
        return bad("duplicate_id", f"id '{wid}' is used more than once; only the first counts.")
    seen.add(wid)

    present = [k for k in _TARGETS if node.get(k) is not None]
    if len(present) != 1:
        return bad(
            "target",
            "exactly one of 'finding', 'rule' or 'criterion' is required"
            + (f" (found {', '.join(present)})." if present else "."),
        )
    kind = present[0]
    target = raw(kind)
    pattern = {"finding": _FINDING, "rule": _RULE, "criterion": _CRITERION}[kind]
    if not isinstance(target, str) or not pattern.fullmatch(target):
        return bad("invalid_target", f"'{kind}' value is not a valid {kind} id.")

    reason = raw("reason")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_LENGTH:
        return bad("reason", f"reason is required (at least {MIN_REASON_LENGTH} characters).")
    if len(reason) > MAX_REASON_LENGTH:
        return bad("reason", f"reason is longer than {MAX_REASON_LENGTH} characters.")
    owner = raw("owner")
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        return bad("owner", "owner is required (a GitHub user, team or e-mail identity).")

    created, expires = _date(raw("created")), _date(raw("expires"))
    if created is None:
        return bad("created", "created is required as an ISO date (YYYY-MM-DD).")
    if expires is None:
        return bad("expires", "expires is required as an ISO date (YYYY-MM-DD).")
    if created > today:
        return bad("created_in_future", "created is in the future.")
    if expires < created:
        return bad("expires_before_created", "expires is before created.")
    if expires - created > timedelta(days=MAX_LIFETIME_DAYS):
        return bad(
            "lifetime_exceeds_max",
            f"a waiver may last at most {MAX_LIFETIME_DAYS} days (created to expires).",
        )

    paths: list[str] = []
    paths_entry = node.get("paths")
    if paths_entry is not None:
        pnode = paths_entry[1]
        items = [pnode] if isinstance(pnode, Scalar) else list(pnode.items) if isinstance(pnode, Seq) else None
        if items is None or len(items) > MAX_PATHS:
            return bad("paths", f"paths must be a list of up to {MAX_PATHS} globs.")
        for item in items:
            if not isinstance(item, Scalar) or not isinstance(item.value, str):
                return bad("paths", "paths must be a list of glob strings.")
            problem = glob_problem(item.value)
            if problem:
                return bad("paths", f"paths: {problem}.")
            paths.append(item.value)
    if kind == "rule" and not paths:
        return bad("rule_needs_paths", "a rule waiver needs 'paths' to limit its scope.")
    if expires < today:
        return bad("expired", f"expired on {expires.isoformat()}.")
    return Waiver(wid, kind, target, reason.strip(), owner, created, expires, tuple(paths), line)


def parse_waivers(text: str, *, today: date) -> WaiversParse:
    """Parse ``.radius/waivers.yml``. Never raises; expired or invalid entries are reported."""

    parsed = miniyaml.parse(text)
    errors = list(parsed.errors)
    warnings: list[Diagnostic] = []
    if parsed.fatal or parsed.root is None:
        if not parsed.fatal:
            errors.append(Diagnostic(0, "The waivers file is empty."))
        return WaiversParse(errors=tuple(errors), structural_failure=True)
    root = parsed.root
    if not isinstance(root, Map):
        errors.append(Diagnostic(0, "The waivers file must be a mapping with 'version' and 'waivers'."))
        return WaiversParse(errors=tuple(errors), structural_failure=True)
    version = root.get("version")
    version_value = version[1].value if version and isinstance(version[1], Scalar) else None
    if version_value != WAIVERS_VERSION or isinstance(version_value, bool):
        errors.append(
            Diagnostic(version[0] if version else 1, f"'version: {WAIVERS_VERSION}' is required.")
        )
        return WaiversParse(errors=tuple(errors), structural_failure=True)
    for key, line, _ in root.entries:
        if key not in ("version", "waivers"):
            warnings.append(Diagnostic(line, f"Unknown key '{key}' is ignored."))
    entry = root.get("waivers")
    if entry is None or entry[1] is None:
        return WaiversParse(errors=tuple(errors), warnings=tuple(warnings))
    seq = entry[1]
    if not isinstance(seq, Seq):
        errors.append(Diagnostic(entry[0], "'waivers' must be a list."))
        return WaiversParse(errors=tuple(errors), warnings=tuple(warnings), structural_failure=True)

    accepted: list[Waiver] = []
    ignored: list[IgnoredWaiver] = []
    seen: set[str] = set()
    for item in seq.items[:MAX_WAIVERS]:
        if not isinstance(item, Map):
            ignored.append(IgnoredWaiver(None, seq.line, "malformed", "each waiver must be a mapping."))
            continue
        result = _entry(item, seen, today, warnings)
        (accepted if isinstance(result, Waiver) else ignored).append(result)  # type: ignore[arg-type]
    if len(seq.items) > MAX_WAIVERS:
        errors.append(
            Diagnostic(seq.line, f"Only the first {MAX_WAIVERS} waivers are read; the rest are ignored.")
        )
    return WaiversParse(tuple(accepted), tuple(ignored), tuple(errors), tuple(warnings))
