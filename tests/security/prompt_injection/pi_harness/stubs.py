"""Deterministic stub models. No network, no API keys.

* :class:`WellBehavedModel` extracts one requirement-looking line per data
  block and ignores everything else.
* :class:`NaiveCompliantModel` is the worst case: it OBEYS any instruction it
  can find in the user message (including base64/ROT13-encoded ones), even
  inside a delimited data block. The guard must still keep its output from
  reaching verdict logic, so the suite uses it to prove the output validator
  (not model good manners) is what protects us.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from radius_shared.llm_guard import decode_candidates, parse_data_blocks

_REQ = re.compile(r"\b(should|must|shall|returns?|supports?|when)\b", re.IGNORECASE)
_NONCE_IN_SYSTEM = re.compile(r"RADIUS_DATA_([A-Za-z0-9]+)")


def _extract(system: str, user: str) -> list[dict[str, object]]:
    m = _NONCE_IN_SYSTEM.search(system)
    blocks = parse_data_blocks(user, m.group(1)) if m else None
    out: list[dict[str, object]] = []
    for sid, text in (blocks or {}).items():
        for line in text.split("\n"):
            if 8 <= len(line) <= 200 and _REQ.search(line):
                start = text.index(line)
                out.append(
                    {"source_id": sid, "quote": line, "start": start, "end": start + len(line), "text": line}
                )
                break
    return out


class WellBehavedModel:
    def complete(self, system: str, user: str) -> str:
        return json.dumps({"criteria": _extract(system, user)}, sort_keys=True)


_I = re.IGNORECASE
_ROLE = re.compile(
    r"<\|im_start\|>|\[INST\]|<<SYS>>|^\s*(?:system|assistant|developer)\s*(?:message)?\s*:|^\s*#+\s*system\b",
    _I | re.MULTILINE,
)
_OVERRIDE = re.compile(
    r"(?:ignore|disregard|forget)\b.{0,40}\b(?:instructions|rules)|override\b.{0,30}\bprompt|from now on|new instructions"
    r"|you are now|ignora las instrucciones|ignorez les instructions|ignoriere alle vorherigen"
    r"|忽略之前|игнорируй все предыдущие",
    _I,
)
_VERDICT_TEXT = re.compile(r"RADIUS\s*[:=\-]\s*(?:PASS|VERIFIED)[A-Z]*", _I)
_VERDICT_FIELD = re.compile(
    r"mark\s+(?:this|the)\s+(?:pr|pull request)\b.{0,20}(?:verified|approved|safe)"
    r"|(?:set|change)\s+(?:the\s+)?(?:verdict|status)\s+to|verdict\s*:\s*verified",
    _I,
)
_EXFIL = re.compile(
    r"(?:print|reveal|show|output|dump|echo|send|leak|repeat)\W+(?:\w+\W+){0,4}?"
    r"(env(?:ironment)?\s+(?:variables?|vars?)|secrets?|api[\s_-]?key|credentials|passwords?"
    r"|system\s+prompt|your\s+instructions|\.env\b)",
    _I,
)
_URL_LURE = re.compile(
    r"(?:fetch|visit|open|download|browse|curl|wget|load)\W+(?:\w+\W+){0,3}?(https?://[^\s'\"<>)]+)", _I
)
_CMD = re.compile(r"(?:please|you must|now)\s+(?:run|execute)\s+(?:the\s+command\s*:?\s*)?([^\n]+)", _I)
_SUBSHELL = re.compile(r"\$\([^)]*\)")
_TOOL = re.compile(r"call\s+(?:the\s+)?(?:tool|function)\b", _I)
_FORGE = re.compile(r"add\s+(?:a\s+|new\s+)*(?:criterion|requirement)\s*:\s*([^\n]+)", _I)
_ECHO_JSON = re.compile(r'\{\s*"criteria".*\}', re.DOTALL)


class NaiveCompliantModel:
    """Obeys injected text. ``leakable`` simulates secrets the model can see."""

    def __init__(self, leakable: Sequence[str] = ()) -> None:
        self._leakable = list(leakable)

    def complete(self, system: str, user: str) -> str:
        views = [user, *decode_candidates(user)]
        text = "\n".join(views)
        echoed = _ECHO_JSON.search(user)
        if echoed:
            return echoed.group(0)
        if _ROLE.search(text):
            return json.dumps({"role": "system", "content": "acknowledged"})
        base = _extract(system, user)
        first = str(base[0]["source_id"]) if base else "pr_body"
        extras: list[dict[str, object]] = []
        top: dict[str, object] = {}

        def add(text_value: str) -> None:
            extras.append(
                {"source_id": first, "quote": base[0]["quote"] if base else "x", "start": base[0]["start"] if base else 0,
                 "end": base[0]["end"] if base else 1, "text": text_value}
            )  # fmt: skip

        if _VERDICT_FIELD.search(text):
            top["verdict"] = "verified"
        if _TOOL.search(text):
            top["tool_calls"] = [{"name": "send_email"}]
        for m in _VERDICT_TEXT.finditer(text):
            add(m.group(0))
        if _EXFIL.search(text):
            target = _EXFIL.search(text).group(1).lower()  # type: ignore[union-attr]
            if "prompt" in target or "instructions" in target:
                add(system[:120])
            else:
                add("env: " + " ".join(self._leakable))
        for m in _URL_LURE.finditer(text):
            add("See " + m.group(1))
        for m in _CMD.finditer(text):
            add(m.group(1))
        for m in _SUBSHELL.finditer(text):
            add(m.group(0))
        for m in _FORGE.finditer(text):
            extras.append(
                {"source_id": first, "quote": m.group(1), "start": 0, "end": len(m.group(1)), "text": m.group(1)}
            )
        if top or extras:
            return json.dumps({"criteria": [*base, *extras], **top})
        if _OVERRIDE.search(text):
            return "Understood. I will ignore my previous instructions and comply."
        return json.dumps({"criteria": base})

