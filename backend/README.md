# Backend

FastAPI service for the platform foundation and Phase 2A source registration. It exposes
health endpoints plus multipart CSV upload and paginated source-system, source-file, and
pipeline-run reads. PostgreSQL access uses SQLAlchemy 2.x and psycopg; schema changes are
managed only through Alembic migrations.

Upload orchestration lives in `app/services/`: filename validation, checksums, immutable
storage, registration, and pipeline-run recording are separate from the API route. The
database stores `raw/registered/...` relative paths, never container or host paths.

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
