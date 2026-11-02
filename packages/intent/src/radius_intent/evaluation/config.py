"""Experiment configuration for the extraction harness (JSON, no YAML dependency).

Example::

    {
      "name": "synthetic-smoke",
      "seed": 20261102,
      "gold": {"path": "benchmarks/fixtures/intent", "adapter": "f14-fixtures"},
      "matching": {"iou_threshold": 0.5, "text_threshold": 0.8},
      "bootstrap": {"resamples": 1000, "confidence": 0.95},
      "rate_testability": true,
      "extractors": [
        {"id": "deterministic", "kind": "deterministic"},
        {"id": "llm-fake", "kind": "llm", "provider": {"type": "fake-lines"}},
        {"id": "combined-fake", "kind": "combined", "provider": {"type": "fake-lines"}}
      ]
    }

Defaults follow the preregistration: IoU 0.5, 10,000 resamples, 95% percentile
intervals, master seed 20261102.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .metrics import MatchConfig
from .stats import DEFAULT_CONFIDENCE, DEFAULT_RESAMPLES

MASTER_SEED = 20261102  # PREREGISTRATION 2 (initial guess, fixed at freeze)
EXTRACTOR_KINDS = ("deterministic", "llm", "combined", "oracle", "null")


class ConfigError(ValueError):
    """The experiment configuration is invalid."""


@dataclass(frozen=True)
class ExtractorSpec:
    """One extractor to run: ``kind`` plus free-form ``options``."""

    extractor_id: str
    kind: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.extractor_id, "kind": self.kind, **dict(self.options)}


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    extractors: tuple[ExtractorSpec, ...]
    seed: int = MASTER_SEED
    gold_path: str | None = None
    gold_adapter: str = "native"
    matching: MatchConfig = field(default_factory=MatchConfig)
    resamples: int = DEFAULT_RESAMPLES
    confidence: float = DEFAULT_CONFIDENCE
    rate_testability: bool = True
    price_per_mtok: tuple[float, float] | None = None  # (input, output) USD, optional

    def as_dict(self) -> dict[str, Any]:
        """Canonical plain-data form (hashed into the manifest)."""
        return {
            "name": self.name,
            "seed": self.seed,
            "gold": {"path": self.gold_path, "adapter": self.gold_adapter},
            "matching": self.matching.as_dict(),
            "bootstrap": {"resamples": self.resamples, "confidence": self.confidence},
            "rate_testability": self.rate_testability,
            "price_per_mtok": list(self.price_per_mtok) if self.price_per_mtok else None,
            "extractors": [e.as_dict() for e in self.extractors],
        }

    @property
    def sha256(self) -> str:
        return config_hash(self.as_dict())


def config_hash(data: object) -> str:
    """SHA-256 of the canonical JSON of ``data``."""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _section(doc: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = doc.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key!r} must be an object")
    return value


def parse_config(doc: object) -> ExperimentConfig:
    """Validate a decoded config document."""
    if not isinstance(doc, Mapping):
        raise ConfigError("config must be a JSON object")
    known = {
        "name", "seed", "gold", "matching", "bootstrap", "rate_testability",
        "price_per_mtok", "extractors",
    }  # fmt: skip
    extra = sorted(set(doc) - known)
    if extra:
        raise ConfigError(f"unknown config keys: {extra}")
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("'name' must be a non-empty string")
    seed = doc.get("seed", MASTER_SEED)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigError("'seed' must be an integer")
    gold = _section(doc, "gold")
    matching = _section(doc, "matching")
    boot = _section(doc, "bootstrap")
    try:
        match_cfg = MatchConfig(**{k: matching[k] for k in matching})
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"matching: {exc}") from exc
    resamples = boot.get("resamples", DEFAULT_RESAMPLES)
    confidence = boot.get("confidence", DEFAULT_CONFIDENCE)
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 1:
        raise ConfigError("bootstrap.resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or not 0 < confidence < 1:
        raise ConfigError("bootstrap.confidence must be in (0, 1)")
    rate = doc.get("rate_testability", True)
    if not isinstance(rate, bool):
        raise ConfigError("'rate_testability' must be a boolean")
    price = doc.get("price_per_mtok")
    if price is not None:
        if not (
            isinstance(price, list)
            and len(price) == 2
            and all(isinstance(p, (int, float)) and p >= 0 for p in price)
        ):
            raise ConfigError("'price_per_mtok' must be [input_usd, output_usd]")
        price = (float(price[0]), float(price[1]))
    raw = doc.get("extractors")
    if not isinstance(raw, list) or not raw:
        raise ConfigError("'extractors' must be a non-empty list")
    specs: list[ExtractorSpec] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ConfigError(f"extractors[{i}] must be an object")
        opts = dict(item)
        eid, kind = opts.pop("id", None), opts.pop("kind", None)
        if not isinstance(eid, str) or not eid.strip():
            raise ConfigError(f"extractors[{i}].id must be a non-empty string")
        if eid in seen:
            raise ConfigError(f"duplicate extractor id {eid!r}")
        if kind not in EXTRACTOR_KINDS:
            raise ConfigError(
                f"extractors[{i}].kind must be one of {EXTRACTOR_KINDS}, got {kind!r}"
            )
        seen.add(eid)
        specs.append(ExtractorSpec(eid, kind, opts))
    gold_path = gold.get("path")
    if gold_path is not None and not isinstance(gold_path, str):
        raise ConfigError("gold.path must be a string")
    adapter = gold.get("adapter", "native")
    if not isinstance(adapter, str):
        raise ConfigError("gold.adapter must be a string")
    return ExperimentConfig(
        name=name,
        extractors=tuple(specs),
        seed=seed,
        gold_path=gold_path,
        gold_adapter=adapter,
        matching=match_cfg,
        resamples=resamples,
        confidence=float(confidence),
        rate_testability=rate,
        price_per_mtok=price,
    )
