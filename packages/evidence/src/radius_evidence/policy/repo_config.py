"""Read and resolve the repository config files (``policy.yml``, ``waivers.yml``).

Source rule (the security property of this module): both files are read from the
**base** side of the pull request through ``read_base``. The head side is only
read for ``.radius/policy.yml`` when the base policy opted in with
``head_policy: tighten_only``, and then only to tighten (see ``effective.py``).
``waivers.yml`` is never read from the head, so the PR author cannot waive their
own findings.

``collect_repo_config`` (Stage A) captures the raw text, hash and status of each
file into a plain dict stored with the Stage A input. ``resolve_repo_config``
(Stage B) parses that dict deterministically for a given ``today``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.policy.effective import (
    NO_POLICY,
    EffectivePolicy,
    apply_to_config,
    resolve_policy,
)
from radius_evidence.policy.miniyaml import MAX_BYTES
from radius_evidence.policy.policy import (
    POLICY_PATH,
    HeadPolicyMode,
    Policy,
    parse_policy,
)
from radius_evidence.policy.waivers import WAIVERS_PATH, WaiversParse, parse_waivers

Reader = Callable[[str], "bytes | None"]

STATUS_OK = "ok"
STATUS_ABSENT = "absent"
STATUS_UNREADABLE = "unreadable"
STATUS_TOO_LARGE = "too_large"
STATUS_NO_BASE = "no_base"

#: Degraded markers (blocking, see ``rules.BLOCKING_DEGRADED_EXACT``).
MARK_POLICY_INVALID = "policy_invalid"
MARK_POLICY_UNREADABLE = "policy_unreadable"


def _read(reader: Reader | None, path: str) -> dict[str, Any]:
    if reader is None:
        return {"status": STATUS_NO_BASE}
    try:
        raw = reader(path)
    except Exception:  # noqa: BLE001 - reading must never crash the analysis
        return {"status": STATUS_UNREADABLE}
    if raw is None:
        return {"status": STATUS_ABSENT}
    if len(raw) > MAX_BYTES:
        return {"status": STATUS_TOO_LARGE, "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"status": STATUS_UNREADABLE, "sha256": hashlib.sha256(raw).hexdigest()}
    return {"status": STATUS_OK, "sha256": hashlib.sha256(raw).hexdigest(), "text": text}


def collect_repo_config(
    read_base: Reader | None,
    read_head: Reader | None = None,
    *,
    base_ref: str | None = None,
    base_available: bool = True,
) -> dict[str, Any]:
    """Stage A: capture the config files. ``read_base`` must read at the base ref.

    ``base_available`` False (the base commit cannot be resolved) marks both files
    unreadable instead of absent, so a missing object can never look like "no policy".
    """

    out: dict[str, Any] = {"base_ref": base_ref or ""}
    if read_base is None:
        out["policy"] = {"status": STATUS_NO_BASE}
        out["waivers"] = {"status": STATUS_NO_BASE}
        return out
    if not base_available:
        out["policy"] = {"status": STATUS_UNREADABLE}
        out["waivers"] = {"status": STATUS_UNREADABLE}
        return out
    out["policy"] = _read(read_base, POLICY_PATH)
    out["waivers"] = _read(read_base, WAIVERS_PATH)
    if out["policy"]["status"] == STATUS_OK:
        parsed = parse_policy(out["policy"]["text"])
        if (
            parsed.policy is not None
            and parsed.policy.head_policy is HeadPolicyMode.TIGHTEN_ONLY
            and read_head is not None
        ):
            out["head_policy"] = _read(read_head, POLICY_PATH)
    return out


@dataclass(frozen=True, slots=True)
class RepoConfigResolution:
    policy: EffectivePolicy = NO_POLICY
    config: VerdictV2Config = field(default_factory=VerdictV2Config)
    waivers: WaiversParse = field(default_factory=WaiversParse)
    status: str = STATUS_ABSENT
    waivers_status: str = STATUS_ABSENT
    source: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    waiver_errors: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    head_note: str | None = None


def _source(entry: Mapping[str, Any], path: str, base_ref: str, origin: str = "base") -> dict[str, Any]:
    return {
        "origin": origin,
        "path": path,
        "ref": base_ref,
        "status": entry.get("status", STATUS_ABSENT),
        "sha256": entry.get("sha256"),
    }


def resolve_repo_config(
    repo_config: Mapping[str, Any] | None,
    defaults: VerdictV2Config | None,
    today: date,
) -> RepoConfigResolution:
    """Stage B: parse the captured files into an overlay and the valid waivers."""

    cfg = defaults or VerdictV2Config()
    if not repo_config:
        return RepoConfigResolution(config=cfg)
    base_ref = str(repo_config.get("base_ref") or "")
    pol_entry = repo_config.get("policy") or {}
    wav_entry = repo_config.get("waivers") or {}
    errors: list[str] = []
    warnings: list[str] = []
    degraded: list[str] = []
    status = str(pol_entry.get("status", STATUS_ABSENT))
    source = _source(pol_entry, POLICY_PATH, base_ref)
    base_policy: Policy | None = None
    head_policy: Policy | None = None
    head_note: str | None = None

    if status == STATUS_OK:
        parsed = parse_policy(str(pol_entry.get("text", "")))
        errors.extend(f"{POLICY_PATH} {d}" for d in parsed.errors)
        warnings.extend(f"{POLICY_PATH} {d}" for d in parsed.warnings)
        if parsed.structural_failure or parsed.policy is None:
            status = "invalid"
            degraded.append(MARK_POLICY_INVALID)
        else:
            base_policy = parsed.policy
    elif status in (STATUS_UNREADABLE, STATUS_TOO_LARGE):
        degraded.append(MARK_POLICY_UNREADABLE if status == STATUS_UNREADABLE else MARK_POLICY_INVALID)
        errors.append(f"{POLICY_PATH} could not be read ({status}).")

    head_entry = repo_config.get("head_policy")
    if base_policy is not None and isinstance(head_entry, Mapping):
        if head_entry.get("status") == STATUS_OK:
            hp = parse_policy(str(head_entry.get("text", "")))
            if hp.policy is None:
                head_note = "the head policy is invalid and was ignored"
                warnings.append(f"head {POLICY_PATH}: invalid, ignored.")
            else:
                head_policy = hp.policy
                warnings.extend(f"head {POLICY_PATH} {d}" for d in hp.warnings)
        elif head_entry.get("status") == STATUS_ABSENT:
            head_note = None

    effective = resolve_policy(base_policy, head_policy, cfg)
    config = apply_to_config(effective, cfg)

    wstatus = str(wav_entry.get("status", STATUS_ABSENT))
    waivers = WaiversParse()
    waiver_errors: list[str] = []
    if wstatus == STATUS_OK:
        waivers = parse_waivers(str(wav_entry.get("text", "")), today=today)
        waiver_errors.extend(str(d) for d in waivers.errors)
        if waivers.structural_failure:
            wstatus = "invalid"
    elif wstatus in (STATUS_UNREADABLE, STATUS_TOO_LARGE):
        waiver_errors.append(f"could not be read ({wstatus}); no waiver applies.")

    return RepoConfigResolution(
        policy=effective,
        config=config,
        waivers=waivers,
        status=status,
        waivers_status=wstatus,
        source=source,
        errors=tuple(errors),
        warnings=tuple(warnings),
        waiver_errors=tuple(waiver_errors),
        degraded=tuple(degraded),
        head_note=head_note,
    )


def waivers_source(repo_config: Mapping[str, Any] | None) -> dict[str, Any]:
    if not repo_config:
        return {}
    return _source(repo_config.get("waivers") or {}, WAIVERS_PATH, str(repo_config.get("base_ref") or ""))
