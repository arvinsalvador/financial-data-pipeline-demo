# Phase 1 architecture

```text
Browser :5173  --->  Vite / React / TypeScript
                         |
                         | HTTP GET /api/v1/health
                         v
Host :8000     --->  FastAPI ---> SQLAlchemy 2.x + psycopg ---> PostgreSQL 16 :5432
                         |
                         +---- Alembic migrations at container startup
```

The frontend reports observed API data, not a hardcoded status. Liveness checks only the
backend process. Readiness performs `SELECT 1` and returns HTTP 503 when PostgreSQL is not
available. The aggregate health response reports both components without adding business
logic.

Configuration enters containers through environment variables. CORS permits only the
configured local frontend origin by default. Database schema ownership belongs to Alembic;
application startup runs committed migrations but never creates migrations or tables
directly. The initial `system_checks` table is intentionally empty and establishes the
typed model/migration pattern for future phases.
