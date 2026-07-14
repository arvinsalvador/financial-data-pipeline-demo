# Backend

FastAPI service for the Phase 1 platform foundation. It exposes root, liveness,
readiness, and aggregate health endpoints. PostgreSQL access uses SQLAlchemy 2.x and
psycopg; schema changes are managed only through Alembic migrations.

From the repository root, run migrations with `docker compose exec backend alembic
upgrade head`. Run tests and quality checks with:

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend mypy app
```

The container applies existing migrations before Uvicorn starts. It never generates
new migration files automatically.
