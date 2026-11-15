# Alembic Migration Guide

Radius uses [Alembic](https://alembic.sqlalchemy.org/) for PostgreSQL schema migrations.
All commands must be run from the **repository root** so that `alembic.ini` is found.

---

## Quick Reference

```bash
# Show current DB revision
uv run alembic -c alembic.ini current

# Show full migration history
uv run alembic -c alembic.ini history --verbose

# Show head(s)
uv run alembic -c alembic.ini heads

# Apply all pending migrations
uv run alembic -c alembic.ini upgrade head

# Roll back one migration
uv run alembic -c alembic.ini downgrade -1

# Roll back to a specific revision
uv run alembic -c alembic.ini downgrade 20261002_0004

# Generate a new migration (autogenerate)
uv run alembic -c alembic.ini revision --autogenerate -m "describe your change"
```

> [!NOTE]
> Always use `uv run alembic` (not `alembic` directly) so that the project's
> virtual environment is active and all workspace packages are on `sys.path`.

---

## How Package Discovery Works

Alembic's `env.py` injects all `packages/*/src` directories into `sys.path`
at startup, so `radius_shared` and sibling packages resolve correctly regardless
of how `alembic` is invoked:

```python
# infra/database/migrations/env.py (excerpt)
_repo_root = Path(__file__).resolve().parents[3]
for _src in sorted(_repo_root.glob("packages/*/src")):
    _src_str = str(_src)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)
```

If you see `ModuleNotFoundError: No module named 'radius_shared'` it means
Alembic was invoked outside the `uv run` context or from a directory where
the glob does not resolve. Always run from the **repo root**.

---

## Migration Chain

```text
20260729_0001  initial phase 1 schema
  └─ 20260729_0002  phase 1 artifact persistence
       └─ 20260729_0003  api idempotency keys
            └─ 20261002_0004  phase 3 decoupled confidence metrics
                 └─ 20261101_0005  repository-scoped test cases
                      └─ 20261101_0006  test result uploads
                           └─ 20261101_0007  test execution history
                                └─ 20261101_0008  test selection evidence
                                     └─ 20261101_0009  coverage tables
                                          └─ 20261029_0005  runtime coverage (no-op)
                                               └─ 20231101_0001  flaky classification + retry_index  (HEAD)
```

---

## Safely Testing Migrations

Create a disposable database, run all migrations from scratch, verify
downgrade/re-upgrade, then drop:

```bash
# 1. Create disposable database
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://radius:radius@localhost:5432/radius', autocommit=True)
conn.cursor().execute('CREATE DATABASE radius_test_migration OWNER radius')
conn.close()
print('Created')
"

# 2. Run all migrations on disposable DB
DATABASE_URL="postgresql+psycopg://radius:radius@localhost:5432/radius_test_migration" \
  uv run alembic -c alembic.ini upgrade head

# 3. Test downgrade/re-upgrade cycle
DATABASE_URL="postgresql+psycopg://radius:radius@localhost:5432/radius_test_migration" \
  uv run alembic -c alembic.ini downgrade -1
DATABASE_URL="postgresql+psycopg://radius:radius@localhost:5432/radius_test_migration" \
  uv run alembic -c alembic.ini upgrade head

# 4. Drop test database
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://radius:radius@localhost:5432/radius', autocommit=True)
conn.cursor().execute('DROP DATABASE IF EXISTS radius_test_migration')
conn.close()
print('Dropped')
"
```

---

## Writing New Migrations

1. Add or modify models in `packages/shared/src/radius_shared/database/`.
2. Autogenerate a migration:
   ```bash
   uv run alembic -c alembic.ini revision --autogenerate -m "short description"
   ```
3. Review the generated file in `infra/database/migrations/versions/`.
4. **Naming**: Use `YYYYMMDD_NNNN_short_name.py` and keep `revision = "YYYYMMDD_NNNN"` <= 32 chars (Alembic's `alembic_version.version_num` column limit).
5. **PostgreSQL enum types**: Always create them explicitly with an idempotent `DO $$` block and drop them in `downgrade()`:

   ```python
   def upgrade() -> None:
       op.execute("""
           DO $$ BEGIN
               IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'myenum') THEN
                   CREATE TYPE myenum AS ENUM ('a', 'b');
               END IF;
           END $$;
       """)
       op.create_table("mytable",
           sa.Column("kind", sa.Enum("a", "b", name="myenum", create_type=False), ...),
           ...
       )

   def downgrade() -> None:
       op.drop_table("mytable")
       op.execute("DROP TYPE IF EXISTS myenum")
   ```

6. Test on a disposable DB before applying to `radius`.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://radius:radius@localhost:5432/radius` | Override connection string |

The `DATABASE_URL` environment variable takes precedence over `sqlalchemy.url`
in `alembic.ini`. Scheme aliases `postgres://` and `postgresql://` are
automatically normalised to `postgresql+psycopg://`.

---

## Known Rules & Best Practices

| # | Rule | Rationale |
|---|------|-----------|
| 1 | Revision IDs **must be <= 32 characters** | Alembic's `alembic_version.version_num` column is constrained to `VARCHAR(32)`. Exceeding this causes `StringDataRightTruncation`. |
| 2 | PostgreSQL enum types are **schema-global** | Always guard enum creation with `DO $$ BEGIN IF NOT EXISTS ... END $$;` and drop via `DROP TYPE IF EXISTS` in downgrade. |
| 3 | Never alter `down_revision` of existing migrations | Breaks migration lineage on existing environments. |
| 4 | Run migrations from repository root | Ensures `alembic.ini` and package discovery paths resolve correctly. |
