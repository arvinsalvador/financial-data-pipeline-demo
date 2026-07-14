# Phase 1 acceptance checklist

- [ ] `docker compose up --build` starts all three services.
- [ ] PostgreSQL, backend, and frontend become healthy.
- [ ] Alembic reports revision `20260714_0001` at head.
- [ ] The frontend displays health data from FastAPI.
- [ ] Root, live, ready, and aggregate health endpoints respond as documented.
- [ ] Backend pytest, Ruff checks, Ruff format check, and mypy pass.
- [ ] Frontend ESLint, TypeScript check, and production build pass.
- [ ] A restart applies no duplicate migration and inserts no records.
- [ ] A clean start after `docker compose down -v` succeeds.
- [ ] `.env` and raw data remain ignored.
- [ ] No ingestion, financial calculation, authentication, tenant, orchestration, or AI
      feature is present.

The commands in the root README are the executable acceptance procedure.
