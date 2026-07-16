# Phase 11: invoice and collections reconciliation

Phase 11 version `1.0.0` creates a deterministic audit trail from generated CRM deals and
invoices through payment applications, canonical operating-account deposits, accounts receivable,
cash GL entries, and accounts-receivable aging. The validated generated dataset remains immutable;
all matches, allocations, exceptions, controls, decisions, and report registrations are stored in
new tenant-scoped tables.

## Source precedence and controls

Payment applications are authoritative for invoice allocation. A generated payment's explicit
canonical bank-transaction identifier takes precedence over amount/date suggestions. Invoice GL is
limited to `customer_invoice` account `1100`; payment cash evidence is limited to
`customer_payment` account `1000`. Invoice lines are recalculated with Decimal arithmetic as
`quantity × unit price − line discount + line tax`. A chain is auto-accepted only when the invoice
and relationship controls pass, applications settle the invoice within tolerance, the deposit link
exists, and AR/cash postings reconcile.

All values use Decimal arithmetic. Invoice sign is positive for customer debt, payment and deposit
signs are positive cash received, AR debit increases receivables, AR credit reduces receivables,
cash debit increases cash, and cash credit reduces cash. Header controls validate
`subtotal + tax - discount = total`; line controls validate extended price, discount, tax, and line
totals. Missing header components remain unavailable and block automatic acceptance.

Explicit applications support one invoice to one or multiple payments and one payment to multiple
invoices without rewriting source rows. Group search for combined and split deposits uses stable
sorting, configured date windows and bounded subset sizes. Ambiguous groups remain reviewable and
are not auto-accepted by default. Excess applications are preserved as overpayment exceptions;
partial applications retain their remaining balance; unapplied cash remains separate from AR.

AR aging uses the requested as-of date and the persisted outstanding balance after valid
applications. Buckets are current, 1–30, 31–60, 61–90, and over 90 days. Paid invoices are omitted.
React renders these authoritative backend totals and does not recalculate aging.

The engine fingerprints source checksums, canonical deposit hashes, validation evidence, dates,
account, version, and all active rule configuration. Identical inputs return a report-integrity-
verified no-op. `--force-rerun` creates a separately fingerprinted run without modifying prior
evidence.

The persisted rate labels are: invoice application count divided by eligible invoice count; applied
payment amount divided by eligible payment amount; allocated customer-deposit amount divided by
eligible selected-account deposit amount; matched accounting amount divided by eligible AR/cash GL;
and auto-reconciled collection amount divided by eligible invoice total. The API returns these rates
from backend metadata; the frontend does not recompute them.

## API and permissions

The primary API is `/api/v1/reconciliations/invoice-collections`. It exposes execution, history,
eligible accounts, run detail, invoice/group detail, candidates, exceptions, unmatched views,
payment detail, controls, AR aging customer drill-down, and 15 registered reports. Review decisions
use `/api/v1/invoice-collections-groups/{id}/accept|reject|resolve|reopen`, validate state
transitions, create append-only decisions and audit events, and preserve the prior and new states.

Finance analysts and CFO users can execute, view, and review. Client viewers can see run summaries,
invoice results, and AR aging but cannot execute, access operational exception/control reports, or
submit decisions.

## CLI

```bash
docker compose exec backend python -m app.cli.reconcile_invoice_collections --bank-account-id 1 --date-from 2022-01-01 --date-to 2023-12-31 --aging-as-of-date 2023-12-31
docker compose exec backend python -m app.cli.list_invoice_collections_reconciliations
docker compose exec backend python -m app.cli.verify_invoice_collections_integrity --reconciliation-run-id 1
docker compose exec backend python -m app.cli.summarize_unmatched_invoice_collections --reconciliation-run-id 1
docker compose exec backend python -m app.cli.export_ar_aging --reconciliation-run-id 1
```

## Verification

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.seed_governance
docker compose exec backend ruff check app tests
docker compose exec backend mypy app
docker compose exec backend pytest
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

The integrity command verifies tenant ownership, source checksums, invoice formulas, application
references, payment/invoice/deposit allocation ceilings, group balances and policy, stable
fingerprints, all 19 controls, active ruleset fingerprint, all 15 report checksums and filenames,
summary-to-database totals, and customer/invoice aging invariants. Database constraints additionally
enforce run-scoped fingerprints, one report per type, one customer snapshot per run, and one aging
row per invoice.

The required artifact inventory is `invoice_collections_summary.json`,
`invoice_reconciliation.csv`, `customer_payment_reconciliation.csv`, `payment_applications.csv`,
`bank_deposit_matches.csv`, `invoice_collections_suggestions.csv`,
`invoice_collections_exceptions.csv`, the four unmatched CSVs, `accounts_receivable_aging.csv`,
`invoice_collections_controls.json`, `duplicate_invoices.csv`, and `duplicate_payments.csv`.
Artifacts use stable ordering, SHA-256 checksums and run/fingerprint-specific relative directories.

The acceptance run exercised 754 invoices, 754 payments and more than 4,000 relevant generated GL
rows without all-to-all scans. Candidate searches are capped by the configured record and group
limits; grouped matching is date-pruned before subset enumeration.

## Deliberate boundaries

Phase 11 does not implement Phase 12 workflow orchestration, collections forecasting, probabilistic
matching, or AI recommendations. Suggested and grouped relationships remain deterministic and
bounded by configured candidate/group limits; grouped matches are never auto-accepted unless the
explicit grouped-auto-accept policy is enabled.
