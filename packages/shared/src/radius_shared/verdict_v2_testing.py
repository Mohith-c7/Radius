"""Test support: a hand-built verdict v2 bundle (shared by shared/api/worker tests).

Shaped like ``VerdictV2.to_dict()`` (fixture 08, gold mode) without importing
the confidence package, so ``radius_shared`` stays dependency-free.
"""

from __future__ import annotations

import hashlib
from typing import Any

HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
SYMBOL = "python:src/validators.py::validate_password#function@981c887bac80"


def _item(evidence_id: str, test_id: str, term: float, *, status: str = "counted") -> dict:
    return {
        "evidence_id": evidence_id,
        "criterion_id": "c_2f6a11",
        "a_static": 1.0,
        "d_eff": 0.6,
        "cap_static": 0.6,
        "i": 0.8,
        "f": 1.0,
        "flaky_f": 1.0,
        "tamper_penalty": 0.0,
        "q": 0.48,
        "l_cs": 1.0,
        "l_st": 0.9,
        "r_ct": 1.0,
        "l": 0.9,
        "term": term,
        "status": status,
        "contribution": term,
        "path": {"symbol_id": SYMBOL, "test_id": test_id, "l_cs": 1.0, "l_st": 0.9, "r_ct": 1.0},
    }


def make_bundle(
    analysis_id: str,
    *,
    head_sha: str = HEAD,
    variant: str = "a",
    verdict: str = "insufficient_evidence",
    pending: bool = False,
    criterion_text: str = "a password needs at least one digit",
) -> dict[str, Any]:
    """Return a valid ``ok`` bundle; ``variant`` changes the inputs digest."""

    digest = hashlib.sha256(f"{analysis_id}|{head_sha}|{variant}".encode()).hexdigest()
    test_id = "tests/test_validators.py::test_rejects_missing_digit"
    justification = {
        "schema": "verdict-v2-justification-1",
        "verdict": verdict,
        "decided_by": "R2b",
        "rules": [
            {"id": "R2b", "label": "unproven intent mass", "fired": True, "inputs": {"uim": 0.5}}
        ],
        "thresholds": {"tau_support": 0.5, "uim_max": 0.2},
        "versions": {"verdict": "verdict-v2-alpha-1"},
        "config_digest": "sha256:" + "c" * 64,
        "profile": "alpha-static",
        "inputs_digest": "sha256:" + digest,
    }
    criteria = [
        {
            "criterion_id": "c_2f6a11",
            "text": criterion_text,
            "weight": 1.0,
            "testability": "behavioral_testable",
            "lifecycle": "confirmed",
            "state": "weak",
            "S": 0.432,
            "S_raw": 0.432,
            "reasons": [{"code": "below_threshold", "detail": "S 0.432 < tau_support 0.5", "ref": None}],
            "flags": ["static_only"],
            "provenance": "author_head_spec",
            "hints": [
                {"kind": "tests", "value": test_id, "provenance": "author_head_spec"},
            ],
            "items": [_item("ev_3e1fd047650b0683fb8b", test_id, 0.432)],
            "best_link": {"symbol_id": SYMBOL, "l_cs": 1.0, "l_st": 0.9, "r_ct": 1.0},
        },
        {
            "criterion_id": "c_d3a2f7",
            "text": "a password must not be on the common-password list",
            "weight": 1.0,
            "testability": "behavioral_testable",
            "lifecycle": "confirmed",
            "state": "unevidenced",
            "S": 0.0,
            "S_raw": 0.0,
            "reasons": [],
            "flags": ["static_only", "no_linked_test"],
            "items": [],
            "best_link": {},
        },
    ]
    verdict_dict = {
        "analysis_id": analysis_id,
        "head_sha": head_sha,
        "revision": 1,
        "verdict": verdict,
        "pending": pending,
        "reasons": [
            {"code": "unproven_intent_mass", "detail": "unproven intent mass 0.5 exceeds 0.20", "ref": None}
        ],
        "criteria": criteria,
        "uim": 0.5,
        "uim_numerator": 1.0,
        "uim_denominator": 2.0,
        "intent_coverage": 1.0,
        "unlinked_symbols": [],
        "tamper": [],
        "justification": justification,
        "config_digest": "sha256:" + "c" * 64,
        "inputs_digest": "sha256:" + digest,
        "algo_version": "verdict-v2-alpha-1",
        "profile": "alpha-static",
        "evidence_basis": "static_only",
    }
    return {
        "schema": "verdict-v2-bundle-1",
        "analysis_id": analysis_id,
        "head_sha": head_sha,
        "status": "ok",
        "inputs_digest": digest,
        "config_digest": "sha256:" + "c" * 64,
        "algo_version": "verdict-v2-alpha-1",
        "profile": "alpha-static",
        "verdict": verdict_dict,
        "evidence_items": [
            {"evidence_id": "ev_3e1fd047650b0683fb8b", "subject_id": test_id, "outcome": "passed"}
        ],
        "stage_a": {"analysis_id": analysis_id, "head_sha": head_sha, "criteria": []},
        "truncated": False,
    }


def make_error_bundle(analysis_id: str, *, head_sha: str = HEAD) -> dict[str, Any]:
    digest = hashlib.sha256(f"{analysis_id}|{head_sha}|error".encode()).hexdigest()
    return {
        "schema": "verdict-v2-bundle-1",
        "analysis_id": analysis_id,
        "head_sha": head_sha,
        "status": "error",
        "reason_code": "TimeoutError",
        "error_detail": "stage A exceeded 120s",
        "fallback": "v1",
        "inputs_digest": digest,
        "algo_version": "verdict-v2-alpha-1",
        "profile": "alpha-static",
        "config_digest": "sha256:" + "c" * 64,
        "verdict": None,
    }
