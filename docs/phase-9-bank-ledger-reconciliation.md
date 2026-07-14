# Phase 9 — bank-to-ledger reconciliation

Phase 9 version `1.0.0` reconciles canonical bank transactions to cash-account lines in a
completed generated general ledger. It is deterministic, tenant-scoped, auditable, and requires a
completed Phase 8 validation run for the selected generated dataset.

## Accounting conventions

- Bank inflows are positive and outflows are negative. Debit/credit columns are authoritative;
  running-balance movement is the fallback, followed by a conservative description heuristic.
- Cash-ledger movement is `debit - credit`.
- Matching never crosses economic direction. Exact amount uses the configured `0.01` tolerance;
  dates use a three-day tolerance by default.
- Critical Phase 8 issues block affected records from automatic matching. Warnings remain visible
  evidence and do not silently remove records.

## Matching and review

The seeded rule set covers exact reference and amount, exact amount and date, date-tolerant and
description-assisted candidates, one-bank-to-many-ledger, many-bank-to-one-ledger, duplicates,
reversals, partial coverage, and unmatched classifications. Only unique, conflict-free candidates
whose rule permits automatic acceptance are allocated automatically. Grouped and partial matches
remain suggestions.

Review decisions are append-only records. `accept`, `reject`, `resolve`, and `reopen` have explicit
status transitions, record the actor and reason, and emit audit events. Existing allocations block
conflicting acceptance.

## Persistence and outputs

The migration adds reconciliation runs, versioned rules, candidates, match groups, matches,
allocations, exceptions, controls, decisions, and reports. Every pipeline run records 19 ordered
steps. A completed run registers nine checksum-protected artifacts:

1. `reconciliation_summary.json`
2. `matched_records.csv`
3. `suggested_matches.csv`
4. `unmatched_bank.csv`
5. `unmatched_ledger.csv`
6. `reconciliation_exceptions.csv`
7. `reconciliation_controls.json`
8. `duplicate_records.csv`
9. `reversal_candidates.csv`

The reports live below `RECONCILIATION_REPORT_ROOT`. Identical bank, ledger, validation, date,
version, and rule-set inputs return the existing checksum-verified run.

## API and UI

The `/api/v1/reconciliations/bank-ledger` API exposes account prerequisites, execution and history,
candidates, groups, decisions, exceptions, controls, unmatched records, and reports. Governance
permissions separate execution, summary viewing, review, candidate detail, exceptions, controls,
and reports. The frontend **Reconciliation** workbench shows run controls, suggested groups,
operator actions, exceptions, and registered reports.

## CLI

```bash
docker compose exec backend python -m app.cli.reconcile_bank_ledger \
  --bank-account-id 1 --date-from 2022-01-01 --date-to 2023-12-31
docker compose exec backend python -m app.cli.list_bank_reconciliations
docker compose exec backend python -m app.cli.verify_bank_reconciliation_integrity \
  --reconciliation-run-id 1
docker compose exec backend python -m app.cli.summarize_unmatched_bank_ledger \
  --reconciliation-run-id 1
```

## Verification

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.seed_governance
docker compose exec backend pytest -q
docker compose exec backend ruff check app tests
docker compose exec backend ruff format --check app tests
docker compose exec backend mypy app
docker compose exec frontend npm run lint
docker compose exec frontend npm run type-check
docker compose exec frontend npm run build
```

## Deliberate boundaries

Phase 9 does not reconcile payroll or invoices, calculate forecasts, orchestrate Prefect flows, or
use probabilistic/AI matching. Ledger rows remain immutable CSV records with stable journal-line
identifiers because the current canonical model has no journal-line table.
