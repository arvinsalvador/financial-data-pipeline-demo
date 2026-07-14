# Phase 4: raw and staging CSV ingestion

Phase 4 begins only after immutable registration and successful profiling. Profiling describes a file and identifies quality risks; ingestion preserves every non-empty source row, parses it under a versioned mapping, and writes either a source-specific staging record or one or more rejection records. It does not create the canonical financial model.

## Architecture and lineage

The shared `CsvIngestionService` verifies tenant ownership, profile status, the registered path, and SHA-256 checksum. It then delegates parsing and staging construction to `MainCheckingConnector`, `SecondaryCheckingConnector`, `CreditCardConnector`, `PayrollSummaryConnector`, or `PayrollDetailConnector`. Connector choice requires a unique active mapping whose filename pattern and target type agree with the requested source. Profile headers are bound to configured aliases; missing required or ambiguous bindings stop ingestion.

`RawSourceRow.raw_data_json` preserves the original decoded field text. Source row numbers are physical CSV line numbers: the header is line 1 and the first data row is line 2. `raw_row_hash` hashes the ordered original field list using deterministic UTF-8 JSON. Accepted and rejected rows retain tenant, source system, source file, pipeline run, row number, and raw-row lineage.

Rejected rows may have multiple deterministic fingerprints—one per reason. Values are not silently corrected, invalid money never becomes zero, and API previews truncate displayed content. Raw/staging uniqueness on tenant, source file, physical row, and ingestion version prevents duplicate loads. An identical successful mapping/ingestion-version request returns a safe no-op, including a forced rerun request; old successful data is not deleted.

## Mappings and parsing

Run `python -m app.cli.seed_governance` after migration. It idempotently creates these tenant-scoped mappings:

- `checking_account_main_v1` → bank transaction
- `checking_account_secondary_v1` → bank transaction
- `credit_card_account_v1` → credit-card transaction
- `gusto_payroll_v1` → payroll summary
- `gusto_payroll_bc_v1` → payroll detail

The database was empty of uploaded profiles during implementation, so the mappings do not claim unobserved exact headers. Each column stores a preferred name plus explicit aliases. At runtime only aliases found in the latest successful profile are bound. This is deliberately fail-closed.

Dates accept ISO and supported unambiguous common formats. Financial values use `Decimal`, supporting currency symbols, commas, whitespace, signs, and parentheses negatives. Identifier text is trimmed but not numerically converted, preserving leading zeros.

Bank and credit-card `amount` keeps the parsed source sign. Where a source supplies separate debit and credit values, the control-total net is `credit - debit`; a missing authoritative amount is not fabricated. Credit-card signs are not reversed. Payroll tables populate only supplied fields, and control totals prefer source net pay when available.

## Controls, pipeline, and artifacts

Every completed run enforces `extracted = accepted + rejected`. Stored controls include extracted, accepted, rejected, and source-versus-accepted monetary totals; unavailable values remain null. The 13 recorded steps cover authorization/context validation, metadata, checksum, profile/mapping, CSV opening, extraction, parsing, staging, rejections, totals, invariants, artifacts, and finalization. A failed step leaves the run failed.

Four immutable, run-specific JSON artifacts are registered with relative paths and SHA-256 checksums: ingestion manifest, rejected-row report, control-total report, and ingestion summary. Current files are processed deterministically in a streaming CSV loop; the configured upload limit is 250 MiB and profiling is capped at 100,000 rows.

## API and UI

Execution and history: `POST /api/v1/source-files/{id}/ingest`, `GET /api/v1/source-files/{id}/ingestions`, and `GET /api/v1/ingestions/{run_id}`. Raw rows, rejections, controls, four staging collections, and read-only mappings have tenant-scoped endpoints under `/api/v1`. Lists are paginated and rejection/staging lists support the documented lineage filters.

The Sources page shows profile and latest ingestion status, counts, disabled reasons, Ingest/View/Rerun actions, and a detailed summary with controls, steps, artifacts, raw rows, and rejected rows. “Staging & mappings” provides four read-only staging views and mapping details.

Finance analysts and CFO users receive ingestion and all Phase 4 read permissions. Client viewers cannot execute ingestion or view raw/rejected/staging/control detail. Development actor headers remain a demo-only context mechanism.

## CLI

```bash
docker compose exec backend python -m app.cli.ingest_source_file --source-file-id 1 --mapping-code checking_account_main_v1
docker compose exec backend python -m app.cli.ingest_source_file --all-eligible
docker compose exec backend python -m app.cli.verify_ingestion_integrity
```

The integrity command returns non-zero for count, checksum, missing lineage, or cross-tenant lineage failures.

## Known limitations

Ingestion is synchronous. Mapping administration remains seed-controlled, structural line counting assumes ordinary CSV records (embedded newlines are parsed correctly but the recorded number is the reader record’s starting sequence rather than a byte offset), and control totals are currently row/net focused rather than source-specific statement certification. No canonical normalization, reconciliation, forecasting, Prefect orchestration, or AI behavior is implemented.
