# Database Migrations

Radius uses Alembic for PostgreSQL schema migrations.

Common commands:

```bash
pnpm db:migrate
pnpm db:revision -- -m "describe change"
```

The Alembic environment imports SQLAlchemy metadata from `radius_shared.database`.
