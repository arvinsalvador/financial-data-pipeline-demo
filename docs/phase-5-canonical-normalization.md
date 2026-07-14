# Phase 5: canonical financial normalization

Phase 5 transforms accepted, source-specific staging rows into stable canonical records. Staging remains a faithful parsed representation of each source; canonical data applies deterministic account, currency, category, counterparty, sign, and payroll-precedence rules for reporting and later reconciliation. General-ledger journal entries, reconciliation, forecasting, Prefect orchestration, generated CRM/invoice data, and AI classification are not implemented.

## Canonical model and lineage

The model includes currencies, a tenant chart-of-accounts foundation, bank and credit accounts, counterparties/vendors/customers/employees, categories, common financial transactions with bank and card extensions, payroll runs and entries, normalization mappings, controls, exceptions, and immutable canonical lineage.

The complete drill-down path is:

```text
dashboard-ready canonical record
→ canonical_record_lineage
→ staging record
→ raw_source_row
→ source_file
→ original immutable registered bytes
```

Every financial transaction and payroll entry receives lineage containing tenant, source system, source file, ingestion run, raw row, staging type/ID, source row/record ID, mapping version, and normalization version. APIs expose safe IDs and relative artifact paths only.

## Bootstrap and mappings

Run `python -m app.cli.bootstrap_canonical`. The idempotent bootstrap creates USD and PHP; nine initial financial accounts; primary operating and secondary payroll bank accounts; a business credit account; ten deterministic categories; and these mappings:

- `bank_transaction_main_v1`
- `bank_transaction_secondary_v1`
- `credit_card_transaction_v1`
- `payroll_summary_v1`
- `payroll_detail_v1`

Accounts resolve from the normalization mapping plus tenant/source-system ownership—not from filenames. Full account numbers are never stored; seeded identifiers are masked and synthetic.

## Deterministic rules

Bank amounts use the staging amount when supplied, otherwise `credit - debit`. Positive canonical bank amounts are cash inflows; negative amounts are outflows. Exact deterministic transfer categories are marked as candidates without collapsing both sides.

Credit-card purchases with negative source signs become positive increases in canonical card liability. Positive source amounts become negative refunds unless the normalized description identifies a payment, which is classified separately. Original signed values and the conversion rule remain in transaction metadata.

Currency precedence is valid source currency, mapping default, then tenant default. An explicitly supplied invalid currency creates an exception instead of being silently replaced.

Counterparty names are case-normalized, safe punctuation is removed, and repeated whitespace is collapsed. Only exact normalized matches resolve automatically; no fuzzy merging is performed. Deterministic merchants may create a counterparty and vendor. Categories use explicit description/category rules with auditable uncategorized income/expense fallbacks—never AI.

## Payroll precedence

Payroll rows group by the source payroll-run ID, or a deterministic pay-period/pay-date key when no ID exists. Missing pay-period dates remain missing. Detail is authoritative at employee level. A summary normalized first creates an entry; matching detail enriches that same entry and adds lineage. A summary normalized after detail adds lineage without overwriting detail. Net-pay conflicts create `payroll_conflict` exceptions. Missing components remain null, not fabricated zeroes.

## Versioning, controls, and exceptions

Normalization version `1.0.0` is stored in pipeline metadata, canonical records/hashes, mappings, lineage, and artifacts. Tenant/source/staging/version constraints enforce idempotency. An identical completed request returns a safe no-op, including forced reruns, and previous canonical records are not silently deleted.

Controls compare staging and canonical record counts and mapping-specific economic totals using `Decimal`. Mismatches or row exceptions produce `completed_with_exceptions`; failed runs cannot be completed. Deterministic exception fingerprints prevent uncontrolled duplication.

The 15 pipeline steps validate context and staging, load mappings, resolve master data, normalize each source family, create lineage, calculate controls/exceptions, validate invariants, register artifacts, and finalize. Four checksum-protected JSON artifacts are written per run under `manifests/normalization`, `reports/normalization`, and `reports/normalization-exceptions`.

## API, CLI, and frontend

`POST /api/v1/ingestions/{id}/normalize` executes synchronously. History/details, all canonical collections, source/canonical lineage, normalization exceptions, and control totals are tenant-scoped and paginated. CFO users and analysts can execute; client viewers receive canonical read access but no normalization or raw lineage access.

```bash
docker compose exec backend python -m app.cli.bootstrap_canonical
docker compose exec backend python -m app.cli.normalize_ingestion --ingestion-run-id 1 --mapping-code bank_transaction_main_v1
docker compose exec backend python -m app.cli.normalize_ingestion --all-eligible
docker compose exec backend python -m app.cli.verify_canonical_integrity
```

The ingestion view provides Normalize, safe rerun, summary, controls, exceptions, steps, and artifacts. The Canonical page provides read-only master/transaction/payroll collections and lineage drill-down.

## Current limitations

Normalization is synchronous and mapping administration is seed-controlled. Transfer detection is category-level and deliberately conservative. Payroll matching currently uses source system, run key, employee ID, and normalization version. There are no journals, balancing entries, reconciliation matches, consolidated reporting calculations, or exception-resolution UI yet.
