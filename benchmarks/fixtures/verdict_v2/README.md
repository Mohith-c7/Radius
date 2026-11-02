# Verdict v2 fixture bundles

`<fixture>/inputs.json` are the Stage-A/Stage-B **input** bundles of the vertical slice (VS-01),
one per F-14 fixture in `../intent/`. They conform to the frozen contracts in
`packages/evidence/src/radius_evidence/domain/inputs.py` and are consumed by the VS-02
acceptance test and the Stage-B pipeline tasks via `loader.py`.

* `modes.gold` - links from `expected.json` (normative); `modes.auto` - links produced by the real
  LK-02/LK-03 code. Both share the real LK-01 symbols, the real EV-02 tamper findings and the
  hand-built assertion features.
* `stage_b.{base,head,head_with_probes}` - per-case CI outcomes copied from `expected.json`.
* `provenance` (per mode) labels every section `real`, `derived` or `hand_built`.
* `tamper_variants.no_registry` - the EV-02 result without a package registry (fixture 06).

Do not edit by hand. Regenerate with `python scripts/verdict_v2_make_fixtures.py`; CI drift check:
`python scripts/verdict_v2_make_fixtures.py --check`. `fixture_expectations.json` is VS-00's file.
