"""Pure rendering of a ``VerdictV2View`` to GitHub Markdown (VD-06, VD-08).

Everything here is a deterministic function of the view: no clock, no network,
no randomness. It produces

* ``render_comment``: the single PR comment (hidden markers, matrix, next steps,
  collapsible details), at most ``MAX_COMMENT_CHARS`` characters;
* ``render_check_run``: Check Run title, summary, text and conclusion;
* ``explain_criterion``: a compact text explanation of one criterion.

Honesty rules: the evidence basis is always labelled "static assertion
strength only"; thresholds are called uncalibrated; the wording never claims
more than the verdict and the evidence show (the internal ``proven`` state is
shown as SUPPORTED, ``verified`` as "Supported by static evidence (alpha)");
the Check Run conclusion is advisory (``neutral``) unless the operator opts into
``strict``; every untrusted string goes through ``radius_github.verdict_v2.escape``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_github.verdict_v2 import escape
from radius_github.verdict_v2.view import (
    CriterionView,
    ItemView,
    NextActionView,
    TamperView,
    VerdictV2View,
)

#: Marker shared with v1 (``radius_github.publisher.COMMENT_MARKER``) so one
#: comment per PR is updated in place when v1 and v2 alternate (decision D10).
COMMENT_MARKER_V1 = "<!-- radius-confidence-report -->"
#: Distinct v2 marker: ``<!-- radius-verdict-v2 rev=N digest=xxxxxxxx -->``.
V2_MARKER_PREFIX = "<!-- radius-verdict-v2"
_V2_MARKER = re.compile(r"<!-- radius-verdict-v2 rev=(\d+) digest=([0-9a-f]{8}) -->")

#: GitHub rejects comment bodies and check-run texts above 65,536 characters.
GITHUB_LIMIT = 65_536
MAX_COMMENT_CHARS = 60_000
TRUNCATION_MARKER = (
    "\n\n_[Radius: this comment was shortened to fit GitHub's size limit; "
    "the dashboard has the full result.]_"
)
MAX_TABLE_ROWS = 100
MAX_LIST_ITEMS = 20
MAX_EVIDENCE_CRITERIA = 30
MAX_ITEMS_PER_CRITERION = 8
MAX_NEXT_ACTIONS = 10
CHECK_TITLE_MAX = 255

STATIC_LABEL = "evidence: static assertion strength only (no mutation testing)"
FOOTER_TEXT = "Computed deterministically from validated evidence; no language model judged correctness."

#: One-line banner at the top of every comment and Check Run summary.
DISCLAIMER = (
    "**Alpha - static evidence only - uncalibrated.** Support is static assertion "
    "strength with thresholds fitted to a few fixtures. It is not a proof of "
    "correctness; do not treat it as a merge gate on its own."
)
LEGEND = "supported = static assertion strength above threshold; not a proof of correctness"
#: Check Run title prefix; the caveat is part of the title, not only of the body.
CHECK_TITLE_PREFIX = "Radius v2 alpha - static evidence only - uncalibrated"

#: Presentation mapping: the internal state values stay in the JSON contract.
STATE_LABELS = {
    "proven": "SUPPORTED",
    "weak": "WEAK",
    "unevidenced": "UNSUPPORTED",
    "contradicted": "CONTRADICTED",
    "excluded": "EXCLUDED",
}
VERDICT_LABELS = {
    "verified": "Supported by static evidence (alpha)",
    "failed": "Failed",
    "insufficient_evidence": "Not verified - insufficient evidence",
    "needs_review": "Needs human review",
}
PENDING_LABEL = "Awaiting CI test results"
UNAVAILABLE_LABEL = "Verdict unavailable"
#: Check Run conclusion by verdict. ``advisory`` (default): nothing is green; ``failed``
#: is a failure only when the deciding rule is R1a/R1b/R1c (see ``check_conclusion``).
#: ``strict`` (operator opt-in, ``RADIUS_VERDICT_V2_CHECK_CONCLUSIONS=strict``): ``verified``
#: is ``success``.
CHECK_CONCLUSIONS_ADVISORY = {
    "verified": "neutral",
    "failed": "failure",
    "insufficient_evidence": "neutral",
    "needs_review": "neutral",
}
CHECK_CONCLUSIONS_STRICT = {**CHECK_CONCLUSIONS_ADVISORY, "verified": "success"}
CHECK_CONCLUSIONS = CHECK_CONCLUSIONS_ADVISORY
#: Deciding rules for which a ``failed`` verdict may be a red check (hard evidence:
#: a failing linked test, failing CI cases, a high-severity tamper finding).
FAILURE_RULES = frozenset({"R1a", "R1b", "R1c"})
CONCLUSION_MODES = ("advisory", "strict")
#: Flags shown as short tags beside the state (others are implied by the text).
FLAG_TAGS = {
    "tampered": "tampered",
    "flaky_evidence": "flaky",
    "stale_evidence": "stale evidence",
    "unconfirmed": "unconfirmed",
    "pending_results": "awaiting CI",
    "low_link_confidence": "weak link",
    "needs_typed_evidence": "needs typed evidence",
    "author_supplied_hint": "author-supplied hint",
}
_STRONG = 0.8
_PARTIAL = 0.3


# ----------------------------------------------------------------- small helpers

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _f2(value: float) -> str:
    return f"{value:.2f}"


def _pct(value: float) -> str:
    return f"{math.floor(max(0.0, min(1.0, value)) * 100 + 0.5)}%"


def _thresholds(view: VerdictV2View) -> Mapping[str, Any]:
    raw = view.justification.get("thresholds")
    return raw if isinstance(raw, Mapping) else {}


def _tau(view: VerdictV2View) -> float | None:
    return _num(_thresholds(view).get("tau_support"))


def _rules(view: VerdictV2View) -> dict[str, Mapping[str, Any]]:
    raw = view.justification.get("rules")
    if not isinstance(raw, list):
        return {}
    return {str(r.get("id")): r for r in raw if isinstance(r, Mapping)}


def _decided_by(view: VerdictV2View) -> str | None:
    value = view.justification.get("decided_by")
    return value if isinstance(value, str) else None


def _labels(view: VerdictV2View) -> dict[str, str]:
    """Criterion id -> short positional label (C1, C2, ...)."""

    out: dict[str, str] = {}
    for n, c in enumerate(view.criteria, start=1):
        out.setdefault(c.criterion_id, f"C{n}")
    return out


def _label_list(ids: Sequence[Any], labels: Mapping[str, str]) -> str:
    return ", ".join(labels.get(i, escape.code(i, 24)) if isinstance(i, str) else "?" for i in ids)


def _ok(view: VerdictV2View) -> bool:
    return view.status == "ok" and view.verdict in VERDICT_LABELS


def verdict_label(view: VerdictV2View) -> str:
    if not _ok(view):
        return UNAVAILABLE_LABEL
    if view.pending:
        return PENDING_LABEL
    return VERDICT_LABELS[str(view.verdict)]


# --------------------------------------------------------------- criterion texts

def _counted(c: CriterionView) -> list[ItemView]:
    return [i for i in c.items if i.status == "counted"]


def _strength_word(a_static: float) -> str:
    if a_static >= _STRONG:
        return "strong"
    if a_static >= _PARTIAL:
        return "partial"
    if a_static > 0:
        return "weak"
    return "none"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _evidence_cell(c: CriterionView, tau: float | None) -> str:
    if c.state == "excluded":
        why = escape.token(c.reasons[0].code if c.reasons else "", 40, fallback="")
        return f"not scored ({why.replace('_', ' ')})" if why else "not scored"
    if not c.items:
        return "no linked test"
    counted = _counted(c)
    failing = [i for i in c.items if i.outcome in ("failed", "error")]
    parts: list[str] = []
    if counted:
        best = max(i.a_static for i in counted)
        parts.append(
            f"{_plural(len(counted), 'test')}, strongest assertion strength "
            f"{_f2(best)} ({_strength_word(best)})"
        )
        if (
            c.state == "weak"
            and len(counted) == 1
            and best >= _STRONG
            and tau is not None
            and c.S < tau
        ):
            parts[-1] += "; one test alone stays under the threshold"
    else:
        parts.append("no test counted")
    if failing:
        parts.append(f"{len(failing)} failing")
    skipped = len(c.items) - len(counted) - len(failing)
    if skipped > 0:
        parts.append(f"{skipped} not counted")
    return "; ".join(parts)


def _tags(c: CriterionView) -> str:
    tags = [FLAG_TAGS[f] for f in c.flags if f in FLAG_TAGS]
    return f" ({', '.join(sorted(set(tags)))})" if tags else ""


def explain_criterion(
    criterion: CriterionView, *, label: str = "This criterion", tau: float | None = None
) -> str:
    """Compact, template-based explanation of one criterion (VD-08).

    Each sentence is derived from one field: state, ``S``, the threshold, the
    items, or a flag. Nothing is inferred beyond those fields.
    """

    c = criterion
    state = STATE_LABELS.get(c.state, "UNKNOWN").lower()
    sentences: list[str] = []
    s_txt = _f2(c.S)
    tau_txt = _f2(tau) if tau is not None else None
    if c.state == "excluded":
        sentences.append(f"{label} is excluded from scoring.")
    elif c.state == "contradicted":
        sentences.append(f"{label} is contradicted: a linked test failed.")
    elif c.state == "proven":
        meets = f"support {s_txt} meets the threshold {tau_txt}" if tau_txt else f"support {s_txt}"
        sentences.append(f"{label} is supported by static evidence: {meets}.")
    else:
        below = f"support {s_txt} is below the threshold {tau_txt}" if tau_txt else f"support {s_txt}"
        if c.state == "weak" and "no_strong_assertion" in c.flags:
            below = f"support {s_txt}, but no linked test has a strong assertion"
        sentences.append(f"{label} is {state}: {below}.")
    counted = _counted(c)
    if c.state != "excluded":
        if not c.items:
            sentences.append("No test is linked to it.")
        elif counted:
            best = max(i.a_static for i in counted)
            sentences.append(
                f"{_plural(len(counted), 'linked test')} counted; strongest assertion strength "
                f"{_f2(best)} ({_strength_word(best)})."
            )
        else:
            sentences.append("No linked test counted as evidence.")
    if "tampered" in c.flags:
        sentences.append("A tamper finding touches its evidence.")
    if "flaky_evidence" in c.flags:
        sentences.append("Part of its evidence is flaky.")
    if "stale_evidence" in c.flags:
        sentences.append("Part of its evidence is not bound to this commit and was ignored.")
    if "unconfirmed" in c.flags:
        sentences.append("The criterion itself is not confirmed by a human.")
    if "low_link_confidence" in c.flags:
        sentences.append("The link between the criterion and the code is weak.")
    if "needs_typed_evidence" in c.flags:
        sentences.append("It needs typed evidence (for example a benchmark) that is not collected yet.")
    return " ".join(sentences)


# ------------------------------------------------------------------ comment parts

def _stats_line(view: VerdictV2View) -> str:
    s = view.summary
    uim_max = _num(_thresholds(view).get("uim_max"))
    limit = f" (limit {_f2(uim_max)})" if uim_max is not None else ""
    basis = (
        STATIC_LABEL
        if s.evidence_basis == "static_only"
        else f"evidence basis: {escape.token(s.evidence_basis, 32)}"
    )
    min_cov = _num(_thresholds(view).get("min_intent_coverage"))
    low = (
        f" (below the minimum {_pct(min_cov)}: the criteria cover too little of the changed behavior)"
        if min_cov is not None and s.intent_coverage < min_cov
        else ""
    )
    return (
        f"**{s.proven} of {s.criteria_total} stated criteria supported** | "
        f"unsupported intent mass **{_f2(s.uim)}**{limit} | "
        f"intent coverage **{_pct(s.intent_coverage)}**{low} | {basis}"
    )


def author_hint_count(view: VerdictV2View) -> int:
    """Criteria whose counted tests rely on an unconfirmed, author-supplied hint."""

    n = sum(1 for c in view.criteria if "author_supplied_hint" in c.flags)
    return max(n, view.summary.author_hint_criteria)


def _author_hint_line(view: VerdictV2View) -> str:
    n = author_hint_count(view)
    if not n:
        return ""
    noun = "criterion relies" if n == 1 else "criteria rely"
    return (
        f"**{n} {noun} on author-supplied test hints** (from this PR's own `.radius/intent.yml` "
        "or description): their link strength is capped. Confirm the criteria in the intent "
        "panel or keep `.radius/intent.yml` on the base branch to lift the cap."
    )


def _tamper_rule_ids(view: VerdictV2View, finding_ids: Sequence[Any]) -> str:
    wanted = {f for f in finding_ids if isinstance(f, str)}
    rules = sorted({escape.token(t.rule_id, 16) for t in view.tamper_findings if t.finding_id in wanted})
    return ", ".join(rules)


def _why(view: VerdictV2View, labels: Mapping[str, str]) -> str:
    if not _ok(view):
        detail = (view.error or {}).get("detail") if isinstance(view.error, Mapping) else None
        base = "The v2 verdict could not be computed for this commit"
        if view.status == "skipped":
            base = "The v2 verdict was skipped for this commit"
        return f"{base}{': ' + escape.plain(detail, 200) if detail else '.'}"
    decided = _decided_by(view)
    rule = _rules(view).get(decided or "", {})
    inputs = rule.get("inputs") if isinstance(rule.get("inputs"), Mapping) else {}
    refs = rule.get("refs") if isinstance(rule.get("refs"), Mapping) else {}
    tau = _tau(view)
    tau_txt = _f2(tau) if tau is not None else "the threshold"
    crit_refs = refs.get("criterion_ids") if isinstance(refs.get("criterion_ids"), list) else []
    if decided == "R1a":
        return f"Failing tests contradict criteria {_label_list(crit_refs, labels)}."
    if decided == "R1b":
        n = _num(inputs.get("failed_cases")) or 0
        return f"{int(n)} CI test case(s) failed for this commit."
    if decided == "R1c":
        ids = refs.get("finding_ids") if isinstance(refs.get("finding_ids"), list) else []
        rules = _tamper_rule_ids(view, ids)
        tail = f" ({rules})" if rules else ""
        return (
            f"{len(ids)} tamper finding(s) at severity {escape.token(inputs.get('threshold'), 16)} "
            f"or above{tail}. Radius treats changes like these as failures because they can hide a "
            "defect; see the tamper findings below."
        )
    if decided == "R2p":
        return (
            "No CI test results have been uploaded for this commit yet, so no criterion has been "
            "scored. This comment is updated when results arrive."
        )
    if decided == "R2a":
        return (
            "No behavioral, testable criterion was found while behavioral code changed. "
            "Add or confirm acceptance criteria for this change."
        )
    if decided == "R2b":
        total = len(inputs.get("criteria", [])) if isinstance(inputs.get("criteria"), list) else 0
        uim = _num(inputs.get("uim")) or 0.0
        uim_max = _num(inputs.get("uim_max")) or 0.0
        return (
            f"{len(crit_refs)} of {total} criteria are below the support threshold {tau_txt} "
            f"({_label_list(crit_refs, labels)}), so the unsupported intent mass {_f2(uim)} exceeds "
            f"{_f2(uim_max)}. Passing tests alone are not enough: an unsupported criterion is checked "
            "weakly or not at all."
        )
    if decided == "R2c":
        cov = _num(inputs.get("intent_coverage")) or 0.0
        low = _num(inputs.get("min")) or 0.0
        return (
            f"Only {_pct(cov)} of the behavioral changes are accounted for by a stated criterion "
            f"(minimum {_pct(low)}). See the changed code without a criterion below."
        )
    if decided == "R2d":
        marks = inputs.get("blocking") if isinstance(inputs.get("blocking"), list) else []
        listed = ", ".join(escape.code(m, 40) for m in marks[:5])
        return f"The analysis was incomplete ({listed}), so no verdict can be given."
    if decided == "R3a":
        ids = refs.get("finding_ids") if isinstance(refs.get("finding_ids"), list) else []
        rules = _tamper_rule_ids(view, ids)
        tail = f" ({rules})" if rules else ""
        return f"Tamper finding(s) at severity medium or above{tail} need a human review."
    if decided == "R3b":
        return (
            f"Criteria counted as supported ({_label_list(crit_refs, labels)}) depend on a flaky test; "
            "a human should review."
        )
    if decided == "R3c":
        return (
            f"Criteria counted as supported ({_label_list(crit_refs, labels)}) rest on a weak link "
            "between the criterion and the code; a human should review."
        )
    if decided == "R4":
        if view.summary.criteria_total == 0:
            return "No behavioral change was detected and no criteria were stated."
        return (
            "No rule found a problem. This rests on static assertion strength only; no mutation "
            "testing was run."
        )
    first = view.reasons[0].detail if view.reasons else ""
    return escape.plain(first, 240) or "See the justification in the dashboard."


def _table(view: VerdictV2View) -> tuple[list[str], int]:
    tau = _tau(view)
    tau_txt = _f2(tau) if tau is not None else "-"
    rows = [
        "| # | Criterion | State | Support | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    shown = view.criteria[:MAX_TABLE_ROWS]
    for n, c in enumerate(shown, start=1):
        support = f"{_f2(c.S)} / {tau_txt}" if c.state != "excluded" else "-"
        rows.append(
            f"| C{n} | {escape.code(c.text)} | "
            f"{STATE_LABELS.get(c.state, 'UNKNOWN')}{_tags(c)} | {support} | "
            f"{_evidence_cell(c, tau)} |"
        )
    return rows, len(view.criteria) - len(shown)


def _next_steps(view: VerdictV2View, labels: Mapping[str, str]) -> str:
    actions: Sequence[NextActionView] = view.next_actions
    if not actions:
        return ""
    lines = ["### What to do next"]
    for n, a in enumerate(actions[:MAX_NEXT_ACTIONS], start=1):
        who = labels.get(a.criterion_id or "", escape.code(a.criterion_id, 24) if a.criterion_id else "")
        prefix = f"**{who}**: " if who else ""
        lines.append(f"{n}. {prefix}{escape.plain(a.text, 400)}")
    if len(actions) > MAX_NEXT_ACTIONS:
        lines.append(f"{MAX_NEXT_ACTIONS + 1}. +{len(actions) - MAX_NEXT_ACTIONS} more, see the dashboard.")
    return "\n".join(lines)


def _tamper_line(t: TamperView) -> str:
    where = escape.code(t.path, 100)
    if t.symbol:
        where += f" ({escape.code(t.symbol, 80)})"
    line = f"- {escape.code(t.rule_id, 16)} **{escape.token(t.severity, 16)}** in {where}: {escape.plain(t.reason, 200)}"
    if t.old_snippet or t.new_snippet:
        before = escape.code(t.old_snippet, 100) if t.old_snippet else "(none)"
        after = escape.code(t.new_snippet, 100) if t.new_snippet else "(none)"
        line += f" (before: {before}; after: {after})"
    return line


def _details(summary: str, body_lines: Sequence[str]) -> str:
    return "<details><summary>" + summary + "</summary>\n\n" + "\n".join(body_lines) + "\n\n</details>"


def _tamper_section(view: VerdictV2View) -> str:
    findings = view.tamper_findings
    if not findings:
        return ""
    lines = [_tamper_line(t) for t in findings[:MAX_LIST_ITEMS]]
    if len(findings) > MAX_LIST_ITEMS:
        lines.append(f"- +{len(findings) - MAX_LIST_ITEMS} more, see the dashboard.")
    return _details(f"Tamper findings ({len(findings)})", lines)


def _unlinked_section(view: VerdictV2View) -> str:
    symbols = view.unlinked_symbols
    if not symbols:
        return ""
    lines = [f"- {escape.code(s, 120)}" for s in symbols[:MAX_LIST_ITEMS]]
    if len(symbols) > MAX_LIST_ITEMS:
        lines.append(f"- +{len(symbols) - MAX_LIST_ITEMS} more, see the dashboard.")
    return _details(f"Changed code with no stated criterion ({len(symbols)})", lines)


def _item_line(i: ItemView) -> str:
    name = i.test_id.rsplit("::", 1)[-1] if i.test_id else ""
    parts = [f"outcome {escape.token(i.outcome, 16)}"]
    strength = f"assertion strength {_f2(i.a_static)}"
    if i.d_eff < i.a_static:
        strength += f" capped at {_f2(i.d_eff)}"
    parts += [strength, f"independence {_f2(i.i)}", f"freshness {i.f:.1f}"]
    if i.flaky_f < 1.0:
        parts.append(f"flaky factor {_f2(i.flaky_f)}")
    if i.tamper_penalty > 0:
        parts.append(f"tamper penalty {_f2(i.tamper_penalty)}")
    parts.append(f"link strength {_f2(i.l)}")
    if i.status == "counted":
        contribution = i.contribution if i.contribution is not None else i.term
        parts.append(f"contribution {contribution:.3f}")
    else:
        parts.append(f"not counted ({escape.token(i.status, 40)})")
    return f"- {escape.code(name, 80)}: " + "; ".join(parts)


def _evidence_section(view: VerdictV2View) -> str:
    tau = _tau(view)
    blocks: list[str] = []
    candidates = [(n, c) for n, c in enumerate(view.criteria, start=1) if c.items]
    for n, c in candidates[:MAX_EVIDENCE_CRITERIA]:
        label = f"C{n}"
        head = f"**{label}** support {c.S:.3f} = {_plural(len(c.items), 'item')}. "
        head += explain_criterion(c, label=label, tau=tau)
        lines = [head, ""]
        lines += [_item_line(i) for i in c.items[:MAX_ITEMS_PER_CRITERION]]
        if len(c.items) > MAX_ITEMS_PER_CRITERION:
            lines.append(f"- +{len(c.items) - MAX_ITEMS_PER_CRITERION} more items, see the dashboard.")
        blocks.append("\n".join(lines))
    if len(candidates) > MAX_EVIDENCE_CRITERIA:
        blocks.append(f"+{len(candidates) - MAX_EVIDENCE_CRITERIA} more criteria, see the dashboard.")
    if not blocks:
        return ""
    return "<details><summary>Per-criterion evidence</summary>\n\n" + "\n\n".join(blocks) + "\n\n</details>"


def _v1_section(view: VerdictV2View) -> str:
    v1 = view.v1
    if not v1:
        return ""
    status = escape.token(v1.get("verification_status"), 32, fallback="unknown")
    score = _num(v1.get("confidence_score"))
    risk = escape.token(v1.get("risk_level"), 16, fallback="unknown")
    score_txt = f"heuristic confidence score {score:.1f}" if score is not None else "no heuristic score"
    body = (
        f"Verification status `{status}`; {score_txt} "
        f"(uncalibrated, not a probability); risk level `{risk}`."
    )
    return _details("Legacy v1 signals (file-level selection, uncalibrated heuristic score)", [body])


def _footer(view: VerdictV2View) -> str:
    algo = escape.token(view.algo_version, 40, fallback="verdict-v2")
    profile = escape.token(view.profile, 32, fallback="")
    prof = f" | profile {profile} (thresholds uncalibrated)" if profile else ""
    url = escape.safe_url(view.dashboard_url)
    link = f" | [details]({url})" if url else ""
    return f"_{FOOTER_TEXT} algo {algo}{prof} | head `{escape.short_sha(view.head_sha)}`{link}_"


# --------------------------------------------------------------- markers / digest

def _strip_markers(body: str) -> str:
    return "\n".join(
        line for line in body.split("\n") if not line.startswith(V2_MARKER_PREFIX)
    )


def comment_digest(body: str) -> str:
    """SHA-256 (hex) of the body without the v2 marker line (revision-independent)."""

    return hashlib.sha256(_strip_markers(body).encode("utf-8")).hexdigest()


def parse_v2_marker(body: object) -> tuple[int, str] | None:
    """Return ``(rev, digest8)`` from a comment body, or ``None``."""

    if not isinstance(body, str):
        return None
    match = _V2_MARKER.search(body)
    return (int(match.group(1)), match.group(2)) if match else None


def _marker_line(view: VerdictV2View, digest8: str) -> str:
    return f"{V2_MARKER_PREFIX} rev={max(1, view.revision)} digest={digest8} -->"


def _assemble(view: VerdictV2View, core: Sequence[str], optional: Sequence[str], footer: str) -> str:
    """Join sections, dropping optional ones (in reverse priority) that do not fit."""

    marker_room = len(_marker_line(view, "0" * 8)) + 1
    budget = MAX_COMMENT_CHARS - marker_room - len(TRUNCATION_MARKER) - 2
    kept = list(core)
    used = sum(len(s) + 2 for s in kept) + len(footer) + 2
    omitted = 0
    for section in optional:
        if not section:
            continue
        if used + len(section) + 2 <= budget:
            kept.append(section)
            used += len(section) + 2
        else:
            omitted += 1
    if omitted:
        kept.append(
            f"_{omitted} detail section(s) omitted to fit GitHub's size limit; see the dashboard._"
        )
    kept.append(footer)
    return "\n\n".join(kept)


def render_comment(view: VerdictV2View) -> str:
    """Render the PR comment for ``view`` (at most ``MAX_COMMENT_CHARS`` characters)."""

    labels = _labels(view)
    heading = f"## Radius verdict (v2 alpha): {verdict_label(view)}"
    core = [DISCLAIMER, heading]
    if _ok(view):
        core.append(_stats_line(view))
        hint_line = _author_hint_line(view)
        if hint_line:
            core.append(hint_line)
    core.append(f"**Why:** {_why(view, labels)}")
    rows_omitted = 0
    if _ok(view) and view.criteria:
        rows, rows_omitted = _table(view)
        core.append("\n".join(rows))
        if rows_omitted:
            core.append(f"+{rows_omitted} more criteria, see the dashboard.")
        core.append(f"_Legend: {LEGEND}._")
    steps = _next_steps(view, labels) if _ok(view) else ""
    optional = [
        steps,
        _tamper_section(view) if _ok(view) else "",
        _unlinked_section(view) if _ok(view) else "",
        _evidence_section(view) if _ok(view) else "",
        _v1_section(view),
    ]
    body = _assemble(view, core, optional, _footer(view))
    if len(body) > MAX_COMMENT_CHARS - 200:
        # Core sections alone are over budget (extreme input): cut deterministically.
        cut = MAX_COMMENT_CHARS - 200 - len(TRUNCATION_MARKER)
        body = body[:cut].rsplit("\n", 1)[0] + TRUNCATION_MARKER
    placeholder = _marker_line(view, "0" * 8)
    draft = f"{COMMENT_MARKER_V1}\n{placeholder}\n{body}\n"
    digest = comment_digest(draft)
    return draft.replace(placeholder, _marker_line(view, digest[:8]), 1)


# --------------------------------------------------------------------- check run

@dataclass(frozen=True, slots=True)
class CheckRunPayload:
    """What to send to the Check Runs API (always a completed run)."""

    title: str
    summary: str
    text: str
    conclusion: str
    details_url: str | None


def check_conclusion(view: VerdictV2View, *, mode: str = "advisory") -> str:
    """Check Run conclusion (alpha: advisory, never green by default).

    ``advisory`` (default): ``neutral`` for every verdict including ``verified``;
    ``failure`` only for ``failed`` decided by R1a/R1b/R1c (a failing linked test,
    failing CI cases, a high-severity tamper finding). ``strict``: ``verified`` is
    ``success``. Unavailable and pending results are always ``neutral``.
    """

    if not _ok(view) or view.pending:
        return "neutral"
    table = CHECK_CONCLUSIONS_STRICT if mode == "strict" else CHECK_CONCLUSIONS_ADVISORY
    conclusion = table.get(str(view.verdict), "neutral")
    if conclusion == "failure" and _decided_by(view) not in FAILURE_RULES:
        return "neutral"
    return conclusion


def check_title(view: VerdictV2View) -> str:
    if not _ok(view):
        title = f"{CHECK_TITLE_PREFIX}: verdict unavailable"
    elif view.pending:
        title = f"{CHECK_TITLE_PREFIX}: awaiting CI test results"
    else:
        s = view.summary
        title = (
            f"{CHECK_TITLE_PREFIX}: {VERDICT_LABELS[str(view.verdict)]} "
            f"({s.proven}/{s.criteria_total} criteria supported)"
        )
    return title[:CHECK_TITLE_MAX]


def render_check_run(view: VerdictV2View, *, conclusions: str = "advisory") -> CheckRunPayload:
    """Check Run title, summary (disclaimer + stats + why) and text (the comment body)."""

    labels = _labels(view)
    summary_lines = [DISCLAIMER]
    if _ok(view):
        summary_lines.append(_stats_line(view))
        hint_line = _author_hint_line(view)
        if hint_line:
            summary_lines.append(hint_line)
    summary_lines.append(f"**Why:** {_why(view, labels)}")
    text = render_comment(view)
    return CheckRunPayload(
        title=check_title(view),
        summary="\n\n".join(summary_lines)[: GITHUB_LIMIT - 1],
        text=text[: GITHUB_LIMIT - 1],
        conclusion=check_conclusion(view, mode=conclusions),
        details_url=escape.safe_url(view.dashboard_url),
    )


def explain_all(view: VerdictV2View) -> dict[str, str]:
    """Criterion id -> compact explanation (VD-08), in view order."""

    tau = _tau(view)
    return {
        c.criterion_id: explain_criterion(c, label=f"C{n}", tau=tau)
        for n, c in enumerate(view.criteria, start=1)
    }


# ------------------------------------------------------------------ idempotent upsert

@dataclass(frozen=True, slots=True)
class UpsertPlan:
    """What the publisher should do with the PR comment: create, update or skip."""

    action: str  # "create" | "update" | "skip"
    comment_id: int | None = None


def _is_bot(comment: Mapping[str, Any]) -> bool:
    user = comment.get("user")
    if user is None:
        return True
    return isinstance(user, Mapping) and str(user.get("type", "")).lower() == "bot"


def find_existing_comment(comments: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Find the Radius comment like the v1 publisher does (bot-authored, has a marker).

    A comment carrying the v2 marker wins over one that only has the v1 marker,
    so a stray old v1 comment never captures the update.
    """

    v1_match: Mapping[str, Any] | None = None
    for comment in comments:
        body = str(comment.get("body", ""))
        if comment.get("id") is None or not _is_bot(comment):
            continue
        if parse_v2_marker(body) is not None:
            return comment
        if COMMENT_MARKER_V1 in body and v1_match is None:
            v1_match = comment
    return v1_match


def plan_upsert(comments: Sequence[Mapping[str, Any]], new_body: str) -> UpsertPlan:
    """Idempotent upsert: ``skip`` when the existing body has the same content digest."""

    existing = find_existing_comment(comments)
    if existing is None:
        return UpsertPlan("create")
    marker = parse_v2_marker(existing.get("body"))
    new_marker = parse_v2_marker(new_body)
    if marker and new_marker and marker[1] == new_marker[1] and existing.get("body") is not None:
        return UpsertPlan("skip", int(existing["id"]))
    return UpsertPlan("update", int(existing["id"]))


class MarkdownRenderer:
    """``ports.VerdictRenderer`` implementation backed by the pure functions above."""

    def render_comment(self, view: VerdictV2View) -> str:
        return render_comment(view)

    def render_check_summary(self, view: VerdictV2View) -> str:
        return render_check_run(view).summary
