# Phase 1 architecture

```text
Browser :5173  --->  Vite / React / TypeScript
                         |
                         | HTTP GET /api/v1/health
                         v
Host :8000     --->  FastAPI ---> registration services ---> /data/raw/registered
                         |                 |
                         |                 +---- SHA-256 / validation / immutable storage
                         v
                  SQLAlchemy + psycopg ---> PostgreSQL 16 :5432
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

Phase 11 adds a read-only reconciliation layer over validated generated CRM/invoice/payment/GL
sources and canonical operating-account deposits. It never rewrites source applications. The
service persists deterministic candidates, groups, component matches, controlled allocations,
exceptions, 19 controls, append-only decisions, AR-aging snapshots, and 15 checksum-registered
artifacts. The API and CLI share the same engine and integrity verifier; React only renders
authoritative backend totals and aging buckets.

Phase 2A introduces `source_systems`, `source_files`, `pipeline_runs`, and
`pipeline_run_steps`. The API streams multipart bytes to temporary storage and calculates
SHA-256 incrementally. A checksum uniqueness constraint provides the database invariant;
exclusive hard-link creation provides the filesystem no-overwrite invariant. Every handled
attempt creates a pipeline run and one receive/register step. No CSV content inspection
occurs beyond filename, MIME type, byte size, and checksum.
