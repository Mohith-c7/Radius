"""``.radius/policy.yml`` (version 1): model, bounds and the strict parser (VD-04).

Pure standard library. The parser never raises. A value that is out of bounds or
of the wrong type is reported as an *error* and ignored (the default applies); an
unknown key is reported as a *warning*. Only a file that cannot be understood at
all (syntax error, missing or unsupported ``version``, root not a mapping) is a
*structural failure*: the caller then treats the policy as invalid (see
``docs/policy.md``). Every accepted setting remembers its source line so the
justification can show which rule came from which policy line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from radius_evidence.policy import miniyaml
from radius_evidence.policy.globs import glob_problem
from radius_evidence.policy.miniyaml import Diagnostic, Map, Node, Scalar, Seq

POLICY_VERSION = 1
POLICY_PATH = ".radius/policy.yml"

SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")
#: Severities a tamper finding may be lowered *below* only with ``allow_disable``.
PROTECTED_FROM = "high"
STATES_REQUIRED: tuple[str, ...] = ("weak", "proven")

MIN_ACK_LENGTH = 10
MAX_ITEMS = 50

#: Safe bounds of every threshold override: ``(lowest, highest)``.
BOUNDS: dict[str, tuple[float, float]] = {
    "tau_support": (0.30, 0.90),
    "uim_max": (0.0, 0.40),
    "intent_coverage_min": (0.30, 1.0),
    "link_review_min": (0.30, 0.90),
    "cap_static": (0.30, 0.80),
}
#: +1: a higher value is stricter; -1: a lower value is stricter.
STRICT_DIRECTION: dict[str, int] = {
    "tau_support": 1,
    "uim_max": -1,
    "intent_coverage_min": 1,
    "link_review_min": 1,
    "cap_static": -1,
}
#: Allowed values of the two tamper thresholds (a lower label is stricter).
FAIL_ON_ALLOWED: tuple[str, ...] = ("medium", "high")
REVIEW_ON_ALLOWED: tuple[str, ...] = ("low", "medium", "high")

_RULE_KEY = re.compile(r"T\d{3}(?::[a-z0-9_]+)?")
_TOP_KEYS = frozenset(
    {"version", "mode", "head_policy", "thresholds", "tamper", "require", "evidence", "exclude"}
)
_THRESHOLD_KEYS = frozenset(BOUNDS)
_TAMPER_KEYS = frozenset({"fail_on_at_least", "review_on_at_least", "rules"})
_RULE_KEYS = frozenset({"severity", "enabled", "allow_disable"})
_REQUIRE_KEYS = frozenset({"paths", "min_state"})
_EVIDENCE_KEYS = frozenset({"require_non_agent_test", "paths"})
_EXCLUDE_KEYS = frozenset({"paths"})


class Mode(StrEnum):
    ADVISORY = "advisory"
    BLOCKING = "blocking"


class HeadPolicyMode(StrEnum):
    IGNORE = "ignore"
    TIGHTEN_ONLY = "tighten_only"


def severity_rank(label: str) -> int:
    value = str(label).strip().lower()
    return SEVERITIES.index(value) if value in SEVERITIES else -1


@dataclass(frozen=True, slots=True)
class TamperRule:
    """One entry of ``tamper.rules``: ``T002`` or ``T012:check``."""

    rule: str
    line: int
    severity: str | None = None
    enabled: bool | None = None
    allow_disable: str | None = None
    #: Set for head policies in ``tighten_only`` mode: a severity can only go up.
    raise_only: bool = False
    origin: str = "base"


@dataclass(frozen=True, slots=True)
class Requirement:
    """Criteria linked to code under ``paths`` must reach ``min_state``."""

    paths: tuple[str, ...]
    min_state: str
    line: int
    origin: str = "base"


@dataclass(frozen=True, slots=True)
class EvidenceRule:
    """At least one counted test per criterion that is not agent-authored."""

    require_non_agent_test: bool
    paths: tuple[str, ...]  # empty = every criterion
    line: int
    origin: str = "base"


@dataclass(frozen=True, slots=True)
class Policy:
    version: int = POLICY_VERSION
    mode: Mode | None = None
    head_policy: HeadPolicyMode = HeadPolicyMode.IGNORE
    thresholds: dict[str, float] = field(default_factory=dict)
    fail_on_at_least: str | None = None
    review_on_at_least: str | None = None
    tamper_rules: tuple[TamperRule, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    evidence: EvidenceRule | None = None
    exclude_paths: tuple[str, ...] = ()
    #: dotted key (``thresholds.tau_support``) -> source line
    lines: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyParse:
    policy: Policy | None
    errors: tuple[Diagnostic, ...] = ()
    warnings: tuple[Diagnostic, ...] = ()
    #: The file as a whole is unusable (the caller must not treat it as "no policy").
    structural_failure: bool = False


class _Collector:
    def __init__(self) -> None:
        self.errors: list[Diagnostic] = []
        self.warnings: list[Diagnostic] = []

    def error(self, line: int, message: str) -> None:
        self.errors.append(Diagnostic(line, message))

    def warn(self, line: int, message: str) -> None:
        self.warnings.append(Diagnostic(line, message))


def _scalar(node: Node) -> object | None:
    return node.value if isinstance(node, Scalar) else None


def _unknown(col: _Collector, node: Map, known: frozenset[str], where: str) -> None:
    for key, line, _ in node.entries:
        if key not in known:
            col.warn(line, f"Unknown key '{where}{key}' is ignored.")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _globs(col: _Collector, key_line: int, node: Node, what: str) -> tuple[str, ...]:
    """A list of path globs (or one glob string); invalid ones are dropped with an error."""

    raw: list[Scalar] = []
    if isinstance(node, Scalar):
        raw = [node]
    elif isinstance(node, Seq):
        raw = [i for i in node.items if isinstance(i, Scalar)]
        if len(raw) != len(node.items):
            col.error(key_line, f"{what} must be a list of glob strings.")
    else:
        col.error(key_line, f"{what} must be a glob or a list of globs.")
        return ()
    out: list[str] = []
    for item in raw[:MAX_ITEMS]:
        if not isinstance(item.value, str):
            col.error(item.line, f"{what}: a glob must be a string.")
            continue
        problem = glob_problem(item.value)
        if problem:
            col.error(item.line, f"{what}: {problem}.")
            continue
        out.append(item.value)
    if len(raw) > MAX_ITEMS:
        col.error(key_line, f"{what}: at most {MAX_ITEMS} globs are allowed.")
    return tuple(out)


def _parse_thresholds(col: _Collector, node: Node, line: int, lines: dict[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(node, Map):
        if node is not None:
            col.error(line, "'thresholds' must be a mapping.")
        return out
    _unknown(col, node, _THRESHOLD_KEYS, "thresholds.")
    for key, kline, value in node.entries:
        if key not in BOUNDS:
            continue
        num = _number(_scalar(value))
        lo, hi = BOUNDS[key]
        if num is None:
            col.error(kline, f"thresholds.{key} must be a number.")
        elif not lo <= num <= hi:
            col.error(
                kline,
                f"thresholds.{key} = {num:g} is outside the allowed range {lo:g} to {hi:g}; "
                "the default is kept.",
            )
        else:
            out[key] = num
            lines[f"thresholds.{key}"] = kline
    return out


def _parse_rule(col: _Collector, key: str, kline: int, value: Node) -> TamperRule | None:
    if not _RULE_KEY.fullmatch(key):
        col.error(kline, f"tamper.rules.{key}: expected a rule id like T002 or T012:check.")
        return None
    severity: str | None = None
    enabled: bool | None = None
    allow: str | None = None
    if isinstance(value, Scalar):
        severity_raw: object = value.value
        sev_line = kline
        if not isinstance(severity_raw, str) or severity_raw.lower() not in SEVERITIES:
            col.error(sev_line, f"tamper.rules.{key}: severity must be one of {', '.join(SEVERITIES)}.")
            return None
        severity = severity_raw.lower()
    elif isinstance(value, Map):
        _unknown(col, value, _RULE_KEYS, f"tamper.rules.{key}.")
        for sub, sline, node in value.entries:
            raw = _scalar(node)
            if sub == "severity":
                if not isinstance(raw, str) or raw.lower() not in SEVERITIES:
                    col.error(sline, f"tamper.rules.{key}.severity must be one of {', '.join(SEVERITIES)}.")
                else:
                    severity = raw.lower()
            elif sub == "enabled":
                if isinstance(raw, bool):
                    enabled = raw
                else:
                    col.error(sline, f"tamper.rules.{key}.enabled must be true or false.")
            elif sub == "allow_disable":
                if isinstance(raw, str) and len(raw.strip()) >= MIN_ACK_LENGTH:
                    allow = raw.strip()
                else:
                    col.error(
                        sline,
                        f"tamper.rules.{key}.allow_disable must be a reason of at least "
                        f"{MIN_ACK_LENGTH} characters.",
                    )
    else:
        col.error(kline, f"tamper.rules.{key} must be a severity or a mapping.")
        return None
    if severity is None and enabled is None:
        col.error(kline, f"tamper.rules.{key} sets neither severity nor enabled.")
        return None
    return TamperRule(key, kline, severity, enabled, allow)


def _parse_tamper(
    col: _Collector, node: Node, line: int, lines: dict[str, int]
) -> tuple[str | None, str | None, tuple[TamperRule, ...]]:
    fail_on: str | None = None
    review_on: str | None = None
    rules: list[TamperRule] = []
    if not isinstance(node, Map):
        if node is not None:
            col.error(line, "'tamper' must be a mapping.")
        return None, None, ()
    _unknown(col, node, _TAMPER_KEYS, "tamper.")
    for key, kline, value in node.entries:
        raw = _scalar(value)
        if key in ("fail_on_at_least", "review_on_at_least"):
            allowed = FAIL_ON_ALLOWED if key == "fail_on_at_least" else REVIEW_ON_ALLOWED
            if isinstance(raw, str) and raw.lower() in allowed:
                lines[f"tamper.{key}"] = kline
                if key == "fail_on_at_least":
                    fail_on = raw.lower()
                else:
                    review_on = raw.lower()
            else:
                col.error(kline, f"tamper.{key} must be one of {', '.join(allowed)}.")
        elif key == "rules":
            if not isinstance(value, Map):
                if value is not None:
                    col.error(kline, "'tamper.rules' must be a mapping of rule ids.")
                continue
            for rkey, rline, rvalue in value.entries[:200]:
                rule = _parse_rule(col, rkey, rline, rvalue)
                if rule is not None:
                    rules.append(rule)
    return fail_on, review_on, tuple(rules)


def _parse_require(col: _Collector, node: Node, line: int) -> tuple[Requirement, ...]:
    if not isinstance(node, Seq):
        if node is not None:
            col.error(line, "'require' must be a list of {paths, min_state} entries.")
        return ()
    out: list[Requirement] = []
    for item in node.items[:MAX_ITEMS]:
        if not isinstance(item, Map):
            col.error(node.line, "Each 'require' entry must be a mapping with paths and min_state.")
            continue
        _unknown(col, item, _REQUIRE_KEYS, "require[].")
        paths_entry = item.get("paths")
        state_entry = item.get("min_state")
        if paths_entry is None:
            col.error(item.line, "A 'require' entry needs 'paths'.")
            continue
        paths = _globs(col, paths_entry[0], paths_entry[1], "require[].paths")
        state = "proven"
        if state_entry is not None:
            raw = _scalar(state_entry[1])
            if isinstance(raw, str) and raw.lower() in STATES_REQUIRED:
                state = raw.lower()
            else:
                col.error(state_entry[0], f"require[].min_state must be one of {', '.join(STATES_REQUIRED)}.")
                continue
        if not paths:
            continue
        out.append(Requirement(paths, state, item.line))
    return tuple(out)


def _parse_evidence(col: _Collector, node: Node, line: int) -> EvidenceRule | None:
    if not isinstance(node, Map):
        if node is not None:
            col.error(line, "'evidence' must be a mapping.")
        return None
    _unknown(col, node, _EVIDENCE_KEYS, "evidence.")
    flag = node.get("require_non_agent_test")
    if flag is None:
        return None
    raw = _scalar(flag[1])
    if not isinstance(raw, bool):
        col.error(flag[0], "evidence.require_non_agent_test must be true or false.")
        return None
    paths: tuple[str, ...] = ()
    paths_entry = node.get("paths")
    if paths_entry is not None:
        paths = _globs(col, paths_entry[0], paths_entry[1], "evidence.paths")
    return EvidenceRule(raw, paths, flag[0]) if raw else None


def _parse_exclude(col: _Collector, node: Node, line: int) -> tuple[str, ...]:
    if not isinstance(node, Map):
        if node is not None:
            col.error(line, "'exclude' must be a mapping with 'paths'.")
        return ()
    _unknown(col, node, _EXCLUDE_KEYS, "exclude.")
    entry = node.get("paths")
    return _globs(col, entry[0], entry[1], "exclude.paths") if entry else ()


def parse_policy(text: str) -> PolicyParse:
    """Parse ``.radius/policy.yml``. Never raises."""

    parsed = miniyaml.parse(text)
    col = _Collector()
    col.errors.extend(parsed.errors)
    if parsed.fatal or parsed.root is None:
        if not parsed.fatal:
            col.error(0, "The policy file is empty.")
        return PolicyParse(None, tuple(col.errors), (), True)
    root = parsed.root
    if not isinstance(root, Map):
        col.error(root.line if isinstance(root, (Seq, Scalar)) else 0, "The policy must be a mapping.")
        return PolicyParse(None, tuple(col.errors), (), True)
    version = root.get("version")
    if version is None or _scalar(version[1]) != POLICY_VERSION or isinstance(_scalar(version[1]), bool):
        col.error(version[0] if version else 1, f"'version: {POLICY_VERSION}' is required.")
        return PolicyParse(None, tuple(col.errors), tuple(col.warnings), True)
    _unknown(col, root, _TOP_KEYS, "")

    lines: dict[str, int] = {}
    mode: Mode | None = None
    head_policy = HeadPolicyMode.IGNORE
    thresholds: dict[str, float] = {}
    fail_on: str | None = None
    review_on: str | None = None
    rules: tuple[TamperRule, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    evidence: EvidenceRule | None = None
    exclude: tuple[str, ...] = ()
    for key, line, node in root.entries:
        raw = _scalar(node)
        if key == "mode":
            if isinstance(raw, str) and raw.lower() in {m.value for m in Mode}:
                mode = Mode(raw.lower())
                lines["mode"] = line
            else:
                col.error(line, "mode must be 'advisory' or 'blocking'.")
        elif key == "head_policy":
            if isinstance(raw, str) and raw.lower() in {m.value for m in HeadPolicyMode}:
                head_policy = HeadPolicyMode(raw.lower())
                lines["head_policy"] = line
            else:
                col.error(line, "head_policy must be 'ignore' or 'tighten_only'.")
        elif key == "thresholds":
            thresholds = _parse_thresholds(col, node, line, lines)
        elif key == "tamper":
            fail_on, review_on, rules = _parse_tamper(col, node, line, lines)
        elif key == "require":
            requirements = _parse_require(col, node, line)
        elif key == "evidence":
            evidence = _parse_evidence(col, node, line)
        elif key == "exclude":
            exclude = _parse_exclude(col, node, line)

    if (
        fail_on is not None
        and review_on is not None
        and severity_rank(review_on) > severity_rank(fail_on)
    ):
        col.error(
            lines["tamper.review_on_at_least"],
            "tamper.review_on_at_least must be at or below fail_on_at_least; both are ignored.",
        )
        fail_on = review_on = None
        lines.pop("tamper.fail_on_at_least", None)
        lines.pop("tamper.review_on_at_least", None)

    policy = Policy(
        mode=mode,
        head_policy=head_policy,
        thresholds=thresholds,
        fail_on_at_least=fail_on,
        review_on_at_least=review_on,
        tamper_rules=rules,
        requirements=requirements,
        evidence=evidence,
        exclude_paths=exclude,
        lines=lines,
    )
    return PolicyParse(policy, tuple(col.errors), tuple(col.warnings), False)
