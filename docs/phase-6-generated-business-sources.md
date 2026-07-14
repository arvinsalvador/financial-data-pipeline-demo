# Phase 6: deterministic generated business sources

Phase 6 turns canonical bank, credit-card, and payroll history into clean, related business-system CSVs for Demo Coffee Group. The fictional company is a multi-location coffee and hospitality operator with catering, wholesale, events, subscriptions, suppliers, rent, utilities, software, maintenance, and biweekly payroll.

This phase generates source data only. It does **not** perform reconciliation, calculate forecasts, inject hostile data, use Prefect, or add AI features.

## Reproducibility

Generator version `1.0.0` uses default seed `20260714` and an explicit generation date. The input fingerprint is SHA-256 over tenant ID, generator version, generation-ruleset identifier, seed, generation date, and the stably ordered canonical hashes for bank transactions, credit-card transactions, and payroll runs. CSVs use UTF-8, LF endings, fixed headers, stable row ordering, stable identifiers, and `Decimal` values rounded half-up to two places. Current time never appears in generated records.

The same tenant, canonical hashes, version, seed, and generation date returns the existing completed run. `--force-rerun` verifies its physical checksums and still returns a no-op. A changed seed deterministically changes controlled descriptive attributes.

## Files and relationships

Each run writes these stable filenames beneath `data/generated/clean/<tenant>/run_<id>/`:

- `customers.csv`: synthetic organizations and `.invalid` contacts, with `CUST-0001` identifiers.
- `crm_deals.csv`: a stable mix of won, lost, and open opportunities using `DEAL-YYYY-NNNN`.
- `invoices.csv` and `invoice_lines.csv`: won deals and exact deposit-backed paid invoices plus clean open/overdue invoices. Every invoice equals its lines.
- `customer_payments.csv` and `customer_payment_applications.csv`: exact one-to-one clean applications linked to positive canonical bank activity.
- `vendors.csv`: deterministic synthetic vendors derived from bank withdrawals and card merchants.
- `accounts_payable.csv`: paid bills linked to canonical withdrawals or card purchases. Card expenses are treated as already-paid vendor expenses and credit card payable is credited once, avoiding double-counting.
- `general_ledger.csv`: balanced journal lines for invoices, collections, AP bills/payments, card purchases, payroll, and payroll cash movements.
- `forecast_assumptions.csv`: base, conservative, and optimistic collection, vendor-payment, and payroll assumptions derived from canonical averages. These are assumptions only; no forecast is calculated.

Human-readable IDs include `CUST-0001`, `DEAL-2023-0001`, `INV-2023-0001`, `PAY-2023-0001`, `VEND-0001`, `AP-2023-0001`, `JE-2023-000001`, `JL-2023-000001-01`, and `ASM-0001`.

`GeneratedRecordLink` rows connect generated payments and invoices to canonical bank transactions, AP bills to canonical bank/card transactions, and payroll journals to payroll runs. All queries and links are tenant-scoped.

## Accounting treatments and controls

- Invoice: debit Accounts Receivable `1100`, credit Sales Revenue `4000`.
- Collection: debit main cash `1000`, credit Accounts Receivable `1100`.
- AP bill: debit operating expense `5100`, credit Accounts Payable `2010`.
- AP payment: debit Accounts Payable `2010`, credit the applicable cash account.
- Card purchase: debit operating expense `5100`, credit Credit Card Payable `2000`.
- Payroll run: debit Payroll Expense `5000`, credit Payroll Deductions Payable `2020`; identifiable bank payroll withdrawals clear the liability to payroll cash `1010`.

Phase 6 bootstraps Accounts Receivable `1100`, Accounts Payable `2010`, Sales Tax Payable `2030`, and Sales Revenue `4000`. Controls prove invoice/line equality, payment/application equality, AP settlement math, global GL debit/credit equality, exact linked cash inflows and outflows, and payroll-journal equality. Critical invariant violations stop completion. Prerequisite failures are stored as `GenerationException`; clean successful runs normally have no exceptions.

## Registration, pipeline, and artifacts

Every CSV is registered in `source_files` under tenant source system `generated_demo_business`. The registered immutable copy and generated copy share a SHA-256 checksum. Only relative paths are stored or returned.

Pipeline `demo_source_generation` records 18 steps from permission/prerequisite validation through finalization. It writes:

- `generation_manifest.json`
- `relationship_manifest.json`
- `control_totals.json`
- `generation_exceptions.json`
- `generated_file_inventory.json`

Artifacts live under tenant/run-specific `data/generated/manifests/` and `data/generated/reports/` paths and are registered as pipeline artifacts.

## API and permissions

- `POST /api/v1/generated-datasets`
- `GET /api/v1/generated-datasets`
- `GET /api/v1/generated-datasets/{id}`
- `GET /api/v1/generated-datasets/{id}/files`
- `GET /api/v1/generated-source-files/{id}`
- `GET /api/v1/generated-source-files/{id}/records`
- `GET /api/v1/generated-datasets/{id}/links`
- `GET /api/v1/generated-datasets/{id}/control-totals`
- `GET /api/v1/generated-datasets/{id}/exceptions`

Permissions are `generated_datasets.execute`, `generated_datasets.view`, `generated_files.view`, `generated_links.view`, `generation_controls.view`, and `generation_exceptions.view`. Platform admin, CFO, and finance analyst receive all six. Client viewer receives safe dataset/file views but cannot execute generation.

The Generated Data frontend page includes the generation form, busy/result state, history, summary metrics, file inventory, a server-backed GL preview, authoritative controls, and a canonical relationship explorer. React displays backend totals and does not calculate accounting results.

## Commands

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.seed_governance
docker compose exec backend python -m app.cli.bootstrap_canonical
docker compose exec backend python -m app.cli.generate_demo_sources --tenant-code demo_coffee_group --seed 20260714 --generation-date 2026-07-14
docker compose exec backend python -m app.cli.generate_demo_sources
docker compose exec backend python -m app.cli.list_generated_datasets
docker compose exec backend python -m app.cli.verify_generated_data_integrity
```

Run the fixed-seed command twice: the second result must print `no_op=true`. The integrity command verifies physical and registered checksums, manifests, invoice math, applications, unique IDs, journal balance, controls, and tenant-safe links. To see controlled changes, run with `--seed 20260715` and compare the inventories.

## Known limitations

Phase 6 uses intentionally straightforward one-to-one clean payment relationships. It does not model split deposits, combined payments, AP payment allocations, card settlements that cannot be identified, taxes beyond the available clean source facts, reconciliation decisions, or forecast calculations. These are appropriate inputs for a later reconciliation and controlled messy-data phase.
