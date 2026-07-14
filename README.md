# CFO Financial Data Pipeline Demo

A portfolio-oriented foundation for a future CFO financial data pipeline. Phase 1 proves
the local platform boundary: a React status interface, a FastAPI service, PostgreSQL
connectivity, repeatable Alembic migrations, tests, and static quality checks.

## Phase 1 scope

Included: containerized development, environment configuration, API health semantics, a
typed example table, and developer documentation. Excluded: ingestion, reconciliation,
forecasting, financial calculations or records, authentication, tenant management,
Prefect, and AI. The source dataset and any Kaggle archive are **not ingested or modified**
during Phase 1.

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
- If the frontend volume has stale dependencies, run `docker compose down -v` (noting the
  database deletion warning) or remove only the frontend node-modules volume explicitly.
- If migrations fail after editing schema code, do not rely on `create_all`; add and review
  an Alembic migration in a future change.
- Check container status with `docker compose ps` and exercise readiness directly with
  `curl -i http://localhost:8000/api/v1/health/ready`.

See [architecture](docs/architecture.md) and the [acceptance checklist](docs/phase-1-acceptance.md)
for the service boundaries and verification sequence.
