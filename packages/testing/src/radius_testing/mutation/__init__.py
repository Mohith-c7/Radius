"""Mutation-evidence prototype (EV-04/05/09/10 spike). Library only, flag-gated.

The worker's Stage A ``mutation`` producer (flag ``RADIUS_FEATURE_MUTATION``, default OFF)
calls :func:`measure_mutation` with the sandbox backend only; the library
functions themselves are pure and testable without it.

SAFETY MODEL (full text in docs/research/design/MUTATION_EVIDENCE.md):

* A mutant is generated code derived from an untrusted repository. It must only
  ever execute inside the F-07 hardened container sandbox
  (:class:`SandboxMutantRunner`). Mutants are never applied to the user's checkout
  and never run on the worker host.
* :class:`SubprocessLocalRunner` is for development and tests on code we wrote
  ourselves (for example the F-14 fixtures). It is refused unless the environment
  variable ``RADIUS_MUTATION_ALLOW_LOCAL=1`` is set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from radius_testing.mutation.budget import MutationBudget, cache_key, sample_mutants
from radius_testing.mutation.equivalence import EquivalenceVerdict, detect_equivalent
from radius_testing.mutation.matrix import (
    CriterionDetection,
    KillMatrix,
    MutantRecord,
    TestDetection,
    aggregate_criterion,
    d_mut_per_test,
    wilson_interval,
)
from radius_testing.mutation.measure import (
    ENGINE_VERSION,
    MeasureConfig,
    MeasuredMutant,
    Measurement,
    Stage2Summary,
    SymbolTarget,
    collapse_results,
    context_hash,
    discover_wide_test_files,
    is_test_path,
    measure_mutation,
)
from radius_testing.mutation.operators import (
    EXPERIMENTAL_OPERATOR_IDS,
    OPERATOR_IDS,
    Mutant,
    generate_mutants,
)
from radius_testing.mutation.runner import (
    LocalRunnerRefusedError,
    MutantOutcome,
    MutantRunner,
    MutationRun,
    RunOutcome,
    SandboxMutantRunner,
    SubprocessLocalRunner,
    run_mutants,
)

FLAG_ENV_NAME = "RADIUS_FEATURE_MUTATION"


def mutation_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True only when ``RADIUS_FEATURE_MUTATION`` is explicitly truthy (default OFF)."""

    env = os.environ if environ is None else environ
    return env.get(FLAG_ENV_NAME, "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ENGINE_VERSION",
    "MeasureConfig",
    "MeasuredMutant",
    "Measurement",
    "Stage2Summary",
    "SymbolTarget",
    "collapse_results",
    "context_hash",
    "discover_wide_test_files",
    "is_test_path",
    "measure_mutation",
    "EXPERIMENTAL_OPERATOR_IDS",
    "FLAG_ENV_NAME",
    "OPERATOR_IDS",
    "CriterionDetection",
    "EquivalenceVerdict",
    "KillMatrix",
    "LocalRunnerRefusedError",
    "Mutant",
    "MutantOutcome",
    "MutantRecord",
    "MutantRunner",
    "MutationBudget",
    "MutationRun",
    "RunOutcome",
    "SandboxMutantRunner",
    "SubprocessLocalRunner",
    "TestDetection",
    "aggregate_criterion",
    "cache_key",
    "d_mut_per_test",
    "detect_equivalent",
    "generate_mutants",
    "mutation_enabled",
    "run_mutants",
    "sample_mutants",
    "wilson_interval",
]
