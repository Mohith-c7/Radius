# Operator documentation

For people who install, run and upgrade a self-hosted Radius stack. Radius is pre-1.0 (`0.1.0`, no
published releases or container images), so every procedure here builds from a source checkout.

Rule for this set: only behavior checked in the code or configuration is stated as fact. Anything
that was not run or not found in code is marked **Unverified**.

| Document | Use it to |
|---|---|
| [INSTALL.md](INSTALL.md) | Bring up the Docker Compose stack and reach a first verdict |
| [CONFIGURATION.md](CONFIGURATION.md) | Look up an environment variable (generated from the code, do not edit) |
| [UPGRADE.md](UPGRADE.md) | Apply a new version, migrate the database, roll back |
| [BACKUP_RESTORE.md](BACKUP_RESTORE.md) | Back up and restore PostgreSQL; what lives where |
| [HARDENING.md](HARDENING.md) | Checklist before exposing the stack to a network |
| [RUNBOOK.md](RUNBOOK.md) | Symptom to check to action for a running system |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Install-time and first-run problems |

Related, outside this folder: [Deployment guide](../DEPLOYMENT.md) (services, GitHub App setup),
[Observability](../OBSERVABILITY.md), [CI integration](../CI_INTEGRATION_GUIDE.md),
[GitHub App validation runbook](../github-app-validation/RUNBOOK.md) and the
[security notes](../security/HTTP_HARDENING.md).

Keeping the reference honest: `python scripts/gen_config_reference.py` rewrites
`CONFIGURATION.md`; `python scripts/gen_config_reference.py --check` (run by
`tests/test_config_reference.py`) fails when the file drifts or when a new environment variable
appears in the source without a description.
