# Phase 2B: CSV profiling and data-quality summary

## Purpose and workflow

Registration preserves and identifies raw bytes. Profiling reads a registered CSV into
bounded analysis structures, records descriptive metrics and issues, and never writes to
the source. Future ingestion will normalize records into a canonical model; that remains
out of scope. The workflow is: registered source → audited `csv_profile` run → encoding
and delimiter inspection → schema and statistics → rules and balance validation → atomic
persistence → API and React display.

Each attempt records nine `pipeline_run_steps`, including useful metadata and errors. A
failed attempt stays auditable and cannot be marked complete. The configured profile
version defaults to `1.0.0`. One derived result exists per source/version; a rerun replaces
that version's columns and issues in a transaction while preserving every pipeline run.
Issue fingerprints are SHA-256 values derived from source, version, rule, column, and row.

## Supported analysis

The inspector supports comma, semicolon, tab, and pipe detection; RFC-style quoted fields;
UTF-8 and UTF-8 BOM; blank lines; whitespace trimming in memory; malformed row widths;
duplicate rows and headers; and safe representative samples. Raw bytes are never changed.
Types include integer, decimal, currency, date, datetime, boolean, identifier, and text.
Numeric statistics, date ranges, and text lengths are populated only for applicable types.

Financial aliases live in `app/services/profiling_config.py` for transaction date, amount,
debit, credit, balance, and identifier concepts. Money parsing accepts plain decimals,
thousands separators, `$`, `PHP`, signs, and accounting parentheses. Invalid values remain
invalid—never zero. ISO dates and unambiguous slash dates are parsed; ambiguous slash dates
produce warnings instead of guessed values. Mixed recognized formats produce a warning.

When movement and balance columns align, the validator derives opening balance, applies
movements, compares each reported balance and the closing balance using the default `0.01`
tolerance, and reports negative balances. Insufficient data produces a warning and a null
validity result, not a fabricated success.

## Rules and severity

Rules cover empty files, unusable/blank/duplicate headers, duplicate and empty rows,
missing financial movement columns, invalid dates and money, inconsistent date formats,
missing or duplicate identifiers, all-null/constant/high-null columns, invalid/negative
running balances, unsupported encoding, safety limits, and too many/few fields. `info`
records observations, `warning` marks suspicious but processable data, `error` identifies
invalid records or calculations, and `critical` blocks reliable profiling.

## API and frontend

- `POST /api/v1/source-files/{id}/profile`
- `GET /api/v1/source-files/{id}/profiles`
- `GET /api/v1/source-files/{id}/profiles/latest`
- `GET /api/v1/profiles/{id}`
- `GET /api/v1/profiles/{id}/columns`
- `GET /api/v1/profiles/{id}/issues`
- `GET /api/v1/data-quality-issues`
- `GET /api/v1/data-quality-issues/{id}`

The React source list starts profiling and opens saved results. The profile view shows
source metrics, inferred columns and samples, financial control totals, balance status,
severity totals, and issue filters. All authoritative values come from FastAPI.

## Configuration and CLI

Defaults are `PROFILING_VERSION=1.0.0`, `CSV_READ_CHUNK_SIZE=1000`,
`MAX_SAMPLED_VALUES_PER_COLUMN=5`, `NULL_PERCENTAGE_WARNING_THRESHOLD=50`,
`RUNNING_BALANCE_TOLERANCE=0.01`, `SUPPORTED_ENCODINGS=utf-8-sig,utf-8`, and
`MAX_PROFILING_ROW_COUNT=100000`.

```bash
docker compose exec backend python -m app.cli.profile_source_file --source-file-id 1
docker compose exec backend python -m app.cli.profile_source_file --all-unprofiled
```

## Known limitations

Only CSV and UTF-8 variants are supported. Delimiter inference uses a bounded sample.
Locale-specific decimal separators, arbitrary encodings, and fully streaming aggregate
statistics are not implemented. Control totals are not authoritative reporting. Canonical
ingestion, reconciliation, forecasting, authentication, tenancy, Prefect, and AI remain
out of scope.
