# CFO Financial Data Pipeline Demo

A portfolio-oriented foundation for a future CFO financial data pipeline. Phase 1 proves
the local platform boundary. Phase 2A adds CSV upload, source registration, checksum-based
duplicate detection, immutable raw storage, and auditable pipeline history.

## Phase 1 scope

Included: containerized development, API health semantics, CSV-only source-file intake,
source-system selection, immutable raw bytes, and pipeline-run audit records. Excluded:
CSV profiling, ingestion, normalization, reconciliation, forecasting, financial
calculations, authentication, tenant management, Prefect, and AI. The source dataset and
any Kaggle archive are **not ingested or modified**.

## Prerequisites and assumptions

- WSL2 Ubuntu
- Docker Desktop with WSL integration enabled for that distribution
- Docker Compose v2 (`docker compose`)
- Optional host tools: Python 3.12, Node.js LTS, and GNU Make

Run all commands from the repository directory inside WSL. Docker supplies the required
Python, Node.js, and PostgreSQL runtimes, so host installations are not required for the
normal workflow.

## Configure and start

```bash
cp .env.example .env
docker compose up --build
```

The example credentials are only for local development. Do not reuse them elsewhere.
The `.env` file is ignored and must not be committed.

Service URLs:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

The backend waits for healthy PostgreSQL, applies committed migrations with `alembic
upgrade head`, then starts Uvicorn. Startup never generates migration files.

## CSV upload flow

Open the frontend, select the seeded **Kaggle Small Business Financial Dataset** source
system, choose or drop a `.csv` file, and select **Upload and register**. The backend:

1. validates the source system, filename, extension, MIME type, and configured size limit;
2. streams the request into `data/raw/uploads/` while calculating SHA-256;
3. returns a duplicate response without another `source_files` row when that checksum is
   already registered;
4. atomically links new bytes into `data/raw/registered/` under
   `<checksum>_<sanitized-filename>` without overwriting an existing file; and
5. writes the source-file, pipeline-run, and pipeline-run-step history.

The default maximum is 10 MiB (`MAX_UPLOAD_SIZE_BYTES=10485760`). Allowed MIME types and
extensions are configurable in `.env`. Original names remain in database metadata, while
only relative storage paths are returned by the API. Registered raw files persist through
container restarts because `./data` is mounted at `/data` in the backend.

Example API upload:

```bash
curl -X POST http://localhost:8000/api/v1/source-files/upload \
  -F "source_system_code=kaggle_small_business_finance" \
  -F "file=@./sample.csv;type=text/csv"
```

Read-only endpoints support `page` and `page_size`:

- `GET /api/v1/source-systems`
- `GET /api/v1/source-files`
- `GET /api/v1/source-files/{id}`
- `GET /api/v1/pipeline-runs`
- `GET /api/v1/pipeline-runs/{id}`

Inspect registered filenames with `find data/raw/registered -maxdepth 1 -type f`. Database
metadata can be inspected with the PostgreSQL instructions below. **CSV rows are not
profiled, parsed, transformed, or ingested in Phase 2A.**

## Database and migrations

Apply existing migrations or inspect the current revision:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

Inspect PostgreSQL:

```bash
docker compose exec postgres psql -U pipeline -d financial_pipeline
```

Inside `psql`, use `\dt`, `\d system_checks`, and `\q`. Substitute values from `.env` if
you changed the defaults.

## Tests and quality checks

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend mypy app
docker compose exec frontend npm run lint
docker compose exec frontend npm run type-check
docker compose exec frontend npm run build
```

The shorter aliases are `make test` and `make lint`. Other helpers include `make up`,
`make up-detached`, `make logs`, `make ps`, `make migrate`, `make backend-shell`, and
`make frontend-shell`.

## Stop, restart, or clean rebuild

```bash
docker compose down
docker compose up --build -d
```

For a completely clean rebuild:

```bash
docker compose down -v
docker compose build --no-cache
docker compose up
```

**Warning:** `docker compose down -v` permanently deletes the local PostgreSQL volume and
all database data in it.

## Troubleshooting

- If a port is occupied, change `POSTGRES_PORT`, `BACKEND_PORT`, or `FRONTEND_PORT` in
  `.env`, then recreate the services. Keep `VITE_API_BASE_URL` aligned with the browser-
  accessible backend port.
- If Docker is unavailable in WSL, open Docker Desktop and enable WSL integration for the
  Ubuntu distribution, then verify with `docker compose version`.
- If the backend is unhealthy, run `docker compose logs backend postgres` and confirm the
  database credentials in `.env` are consistent.
- If an upload is rejected, inspect its structured API response and the corresponding row
  in `pipeline_runs`; validation failures are intentionally auditable.
- If the frontend volume has stale dependencies, run `docker compose down -v` (noting the
  database deletion warning) or remove only the frontend node-modules volume explicitly.
- If migrations fail after editing schema code, do not rely on `create_all`; add and review
  an Alembic migration in a future change.
- Check container status with `docker compose ps` and exercise readiness directly with
  `curl -i http://localhost:8000/api/v1/health/ready`.

See [architecture](docs/architecture.md) and the [acceptance checklist](docs/phase-1-acceptance.md)
for the service boundaries and verification sequence.
