# Phase 10.5: responsive UI and safe demo reset

Phase 10.5 stabilizes the application before additional financial modules are added. It changes
presentation and development tooling only; backend permissions, tenant isolation, source-file
immutability, validation, and reconciliation contracts remain authoritative.

## Application shell

The shell separates a sticky desktop sidebar, compact context/health header, page header, and
bounded main-content region. Navigation is defined once in `frontend/src/navigation.ts` and grouped
as Data Foundation, Data Simulation, Data Quality, Reconciliation, and Governance. Only implemented
features appear. Active items and their parent groups are highlighted.

The sidebar expands to 264px, collapses to 78px, exposes labels as tooltips while collapsed, and
persists its preference in local storage. Below 820px it becomes a modal drawer. The drawer closes
after navigation, by its close/backdrop controls, or with Escape. Semantic `header`, `nav`, `aside`,
and `main` landmarks, text-labelled status states, visible focus outlines, ARIA state, and labelled
form controls improve accessibility.

Tenant and demo-user controls remain development-context headers, not authentication. Changing
either updates the existing request headers and remounts tenant-scoped content. Client viewers do
not receive staging, governance, or mutation navigation/actions; backend checks remain mandatory.

Tables scroll inside `.table-wrap`, use sticky headers, and cannot widen the application shell.
Forms stack at mobile widths, buttons retain a 42px target height, titles scale from laptop to phone,
and long financial values wrap within their container. Source Intake retains drag/drop, the 250 MiB
limit message, source selection, checksum behavior, recent files, and immutable-storage messaging.

The responsive breakpoints were designed for 1440, 1280, 1024, 768, and 390px widths.

## Development bootstrap

The consolidated bootstrap is development/test-only and calls the existing idempotent governance
bootstrap, which also seeds source systems, ingestion mappings, canonical master data, defect
scenarios, validation rules, reconciliation rules, permissions, and pipeline definitions. It does
not upload, ingest, normalize, generate, validate, or reconcile files.

```bash
docker compose exec backend python -m app.cli.bootstrap_demo_environment
```

Running it repeatedly must not create duplicates.

## Environment verification

The read-only verifier checks stored relative paths, missing registered/generated/artifact files,
orphan registered files, duplicate checksums, required bootstrap records, and Alembic head state.
It exits non-zero when inconsistencies are found and never deletes data.

```bash
docker compose exec backend python -m app.cli.verify_demo_environment
```

For a database/file mismatch, first run the verifier, restore missing immutable files when possible,
or use a selective dry-run/reset followed by bootstrap. Never fabricate checksum records.

## Safe selective reset

Reset is CLI-only, refuses non-development/test environments, performs no work by default, requires
`--confirm` for deletion, validates every resolved path beneath `/data`, protects `.env`, source
code, `.git` paths, and `.gitkeep`, and never manipulates Docker volumes.

```bash
docker compose exec backend python -m app.cli.reset_demo_environment --all-demo-data --dry-run
docker compose exec backend python -m app.cli.reset_demo_environment --database-records --reports --confirm
```

Selective file modes are `--uploaded-files`, `--generated-clean`, `--generated-messy`, `--reports`,
and `--manifests`. `--all-demo-data` combines database and file cleanup. The command prints all
affected record counts and every file before deletion. Generated-clean cleanup excludes nested
messy, manifest, and report roots.

## Full Docker reset

For a completely fresh local PostgreSQL volume:

```bash
docker compose down -v
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.bootstrap_demo_environment
docker compose exec backend python -m app.cli.verify_demo_environment
```

`docker compose down -v` permanently deletes the PostgreSQL Docker volume. Host-mounted `/data`
files may remain, so inspect the verification output and use the reset CLI dry-run before removing
them.

## Known limitations

The app still uses lightweight in-memory page selection rather than a URL router, so browser deep
links are not yet available. Frontend role visibility is intentionally based on the configured demo
actors and is not a substitute for backend authorization. The reset targets the configured local
data roots and is not a production retention tool. Invoice reconciliation, exception management,
forecasting, Prefect, deployment, and AI features remain outside this phase.
