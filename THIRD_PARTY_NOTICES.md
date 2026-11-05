# Third-party notices

Radius itself is Apache-2.0 (`LICENSE`, `NOTICE`). It depends on third-party packages that keep their own licenses. This file explains where the authoritative inventory comes from; it deliberately does not hand-copy a package list that would go stale.

## Authoritative inventory

The CI job `sbom-licenses` in `.github/workflows/security.yml` produces, on every run, and uploads for 90 days as the artifact `sbom-and-licenses`:

- `sbom-python.cdx.json`: CycloneDX SBOM of the Python environment.
- `licenses-python.json` and `licenses-node.json`: license reports (`pip-licenses`, `pnpm licenses list`).

Policy (`scripts/ci/license_check.py`, `docs/security/CI_CHECKS.md`): the job fails on AGPL, SSPL or GPL; LGPL and MPL are reported and allowed.

## Checked on 2026-11-02 (Python, runtime plus `llm` and `observability` extras)

138 installed distributions; the gate passed. No AGPL, SSPL or GPL. Weak-copyleft packages present, with the obligation that applies:

| Package | License | Obligation as used by Radius |
|---|---|---|
| psycopg, psycopg-binary | LGPL-3.0-only | Used as an unmodified, dynamically imported library installed from PyPI. Allowed. If a container image or release bundle ships psycopg-binary (it bundles libpq and other native libraries), include the LGPL text and keep it replaceable (a normal `pip install` layer satisfies this). Do not modify and relicense it. |
| certifi, pathspec, fqdn, tqdm | MPL-2.0 (tqdm: MPL-2.0 AND MIT) | File-level copyleft. Unmodified use has no effect on Radius' license. Do not copy their files into this repo. |

Permissive licenses (MIT, BSD, Apache-2.0, ISC, PSF and similar) make up the rest, including `tree-sitter` (MIT), the `tree-sitter-*` grammars (MIT), `anthropic` (Apache-2.0), `google-genai` (Apache-2.0), `fastapi`, `pydantic`, `sqlalchemy`. They permit redistribution inside an Apache-2.0 project. Where a dependency is Apache-2.0 and ships a NOTICE file, preserve it when redistributing a bundle.

Node dependencies (`pnpm licenses list`) were not inventoried in this check because `pnpm` was not available in the environment; the CI job covers them.

## Code or rules from other projects

None is copied into this repository. Related tools and their licenses are tracked in `docs/research/literature/related-work.md`. Mutahunter is AGPL-3.0: do not copy or link it. Verik is Apache-2.0 (would be allowed with attribution in `NOTICE`). AgentProof, ScopeProof and SlopGate have no usable license: treat as all rights reserved.

## Data

Third-party datasets are not redistributed; see `docs/research/datasets/INVENTORY.md` for the license verdict of each.
