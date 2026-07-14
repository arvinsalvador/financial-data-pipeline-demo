# Phase 2A: CSV source registration

Phase 2A accepts CSV files without interpreting their contents. Users select an active
source system in the React page, choose or drag a file, and receive a registered,
duplicate, validation, or failure result from the FastAPI endpoint.

## Storage and duplicate invariants

- Uploads stream in bounded chunks to `/data/raw/uploads`.
- SHA-256 is calculated during the stream; the whole file is never loaded into memory.
- Registered names are `<sha256>_<sanitized-original-name>`.
- Exclusive filesystem creation prevents overwrite; registered files are made read-only.
- PostgreSQL uniquely constrains the checksum, stored filename, and relative path.
- Exact duplicate bytes create another auditable pipeline run but no second source file.
- API responses and database rows contain relative paths only.

The host `data/` directory is mounted at `/data`, so registered files survive container
replacement. The seeded source-system code is `kaggle_small_business_finance`.

## Limits and current exclusions

The default maximum upload size is 10 MiB and only `.csv` is allowed. MIME validation
accepts common browser CSV MIME types and can be configured through `.env`. This phase does
not profile, parse, normalize, reconcile, calculate, or ingest CSV records. Authentication,
tenancy, orchestration, forecasting, and AI remain out of scope.

See the root README for browser and `curl` workflows, storage inspection, migrations,
tests, and troubleshooting.
