# Phase 10: payroll reconciliation

Phase 10 adds deterministic, tenant-scoped payroll reconciliation version `1.0.0`. It links
authoritative canonical payroll entries to their payroll run, eligible withdrawals from the
secondary payroll checking account, and payroll-related lines in the newest completed,
validated generated general ledger. It does not change canonical payroll values.

## Architecture and source precedence

The Phase 5 canonical payroll-detail normalization is authoritative. Payroll-run summaries are
batch controls and lineage evidence; they are not a second obligation. The engine loads canonical
entries once, aggregates them by payroll run, then compares those aggregates with the run totals.
Unavailable entry components remain unavailable and produce `unavailable` controls rather than
being silently converted to zero.

The processing order is internal payroll validation, bank and GL eligibility, deterministic
fingerprints, duplicate/reversal checks, candidate scoring, conflict resolution, exact acceptance,
partial/unmatched classification, allocations, controls, reports, integrity validation, and final
status. The persisted pipeline has 22 individually timed steps.

## Accounting formulas and signs

Where every component exists, the employee cash formula is:

```text
gross pay + reimbursements - employee taxes - employee deductions = net pay
```

Employer taxes and employer contributions are employer expenses and do not reduce employee net
pay. Bank eligibility uses the canonical bank detail: debit is an outflow, credit is an inflow, and
running-balance movement is the fallback for sources whose direction field is unreliable. GL
debits represent payroll expense and GL credits represent payroll liabilities/cash. Journals must
balance within the configured Decimal tolerance.

## Settlement models and matching

The supported bank settlement models are `net_pay_only`, `net_pay_plus_taxes`,
`full_payroll_cash_requirement`, `split_withdrawals`, and `configured_components`. The last model
requires an explicit `configured_cash_components` list in payroll-run metadata.

Payroll-to-bank candidates require an equal expected amount within tolerance and a date inside the
configured window. Exact normalized reference wins, followed by exact pay date, then the smallest
date difference and stable record ID. Competing equal candidates remain reviewable. Payroll-to-GL
matching uses explicit payroll-run IDs, a balanced journal, compatible payroll accounts, expected
expense totals, dates, and validation blockers. One run can be linked to multiple GL lines.

Exact, unique bank and balanced-GL evidence can be auto-accepted only when internal controls pass,
confidence is at least `0.98`, and no allocation conflict exists. Grouped, ambiguous, or incomplete
evidence remains suggested or partially matched. Split-bank grouping is bounded by five records and
GL grouping by twenty; non-unique groupings require review. Legitimate recurring payroll is kept
distinct by run ID/date. Duplicate employee/run combinations and likely equal-and-opposite,
close-date reversals are retained as exceptions and are never silently netted.

Candidate reasons store reference, amount, date, account, balance, and lineage evidence. No AI or
opaque scoring is used. Bank and GL allocations are Decimal values and are checked for duplicate or
over-allocation. Every partial match retains its unexplained amount as an exception.

## Controls and rates

Seventeen named controls cover employee count, gross pay, employee/employer taxes and deductions,
contributions, reimbursements, net pay, bank and GL totals, payroll-bank/GL differences, allocation
balance, and the reconciliation rate. The authoritative reconciliation rate is:

```text
fully reconciled eligible payroll runs / eligible payroll runs
```

Bank, GL, component, and employee validation rates remain separately labelled in API/report
metadata; incompatible rates are not combined.

The input fingerprint contains the selected period/account/model/version plus canonical payroll,
entry, bank, GL, and validation hashes. The ruleset fingerprint contains active ordered rules,
versions, confidence configuration, grouping limits, and settlement model. An identical completed
request verifies and returns the prior run without duplicating records or files. A force request is
audited and never overwrites a prior reconciliation.

## Review, permissions, and audit

`platform_admin`, `cfo_user`, and `finance_analyst` receive the Phase 10 execute, view, review,
candidate, exception, control, and report permissions. `client_viewer` receives summary view only.
All record lookups include tenant context and cross-tenant IDs return not found.

Accept, reject, resolve, and reopen actions validate status transitions, append a
`PayrollReconciliationDecision`, update only reconciliation state, and write an audit event. Prior
decisions remain visible. Audit metadata contains identifiers and outcomes, not employee payroll
details.

## API and frontend

The API root is `/api/v1/reconciliations/payroll`. `POST` starts a run and `GET` lists history;
`/{run_id}` returns the summary. Nested endpoints expose payroll-run summaries/details,
filterable candidates, groups, exceptions, controls, unmatched payroll/bank/GL records, and reports.
Review endpoints are `/api/v1/payroll-reconciliation-groups/{group_id}/{accept|reject|resolve|reopen}`.
Only relative report paths are returned.

The **Payroll reconciliation** frontend page provides account, period, settlement-model, and force
controls; server-calculated summary values; payroll groups; control totals; report links; and
permission-protected review actions. React does not calculate authoritative payroll values.

## CLI

```bash
docker compose exec backend python -m app.cli.reconcile_payroll --payroll-bank-account-id 2 --date-from 2023-01-01 --date-to 2023-12-31 --settlement-model net_pay_only
docker compose exec backend python -m app.cli.list_payroll_reconciliations
docker compose exec backend python -m app.cli.verify_payroll_reconciliation_integrity --payroll-reconciliation-run-id 1
docker compose exec backend python -m app.cli.summarize_payroll_mismatches --payroll-reconciliation-run-id 1
```

## Reports

Each run creates twelve stable, checksum-protected files beneath
`data/reports/reconciliation/payroll/<tenant>/run_<id>/`: summary JSON, run controls, bank matches,
GL matches, suggestions, unmatched runs/bank/GL, exceptions, controls JSON, duplicates, and
reversals. Database rows and pipeline artifacts store relative paths, SHA-256, MIME type, size,
tenant, and run lineage. Existing paths are never overwritten.

## Configuration and tested limits

Defaults are version `1.0.0`, amount tolerance `0.01`, date tolerance three days,
`net_pay_only`, auto-accept `0.98`, suggestion `0.65`, bank groups five, GL groups twenty,
twenty candidates per payroll run, duplicate-date tolerance zero, reversal window seven days,
employee mismatch tolerance `0.01`, and report root `/data/reports/reconciliation/payroll`.
Candidate generation is bounded per payroll run and uses preloaded summaries. The demo verification
covered 37 payroll runs, 178 entries, 12 eligible bank withdrawals, and 74 GL lines. Larger volumes
should be load-tested before production use.

## Manual verification

```bash
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.reconcile_payroll --payroll-bank-account-id 2 --date-from 2023-01-01 --date-to 2023-12-31 --settlement-model net_pay_only
docker compose exec backend python -m app.cli.list_payroll_reconciliations
docker compose exec backend python -m app.cli.summarize_payroll_mismatches --payroll-reconciliation-run-id 1
docker compose exec backend python -m app.cli.verify_payroll_reconciliation_integrity --payroll-reconciliation-run-id 1
```

In the frontend, inspect internal controls, exact and grouped GL evidence, partial groups, and all
three unmatched lists. Accept and reject reviewable groups with documented reasons, inspect their
decision/audit history, rerun the first command to confirm `no_op=true`, then repeat with
`--force-rerun` to confirm a force request is audited.

## Known limitations

The synchronous engine is intended for demo-scale workloads. It does not resolve exceptions as a
standalone case-management system, match employee bank accounts, infer missing payroll components,
or use AI. Sparse source components limit internal formula verification. Split withdrawals and
reversals remain review-oriented unless explicit source metadata makes them unique. Invoice,
collections, and full AP reconciliation are not implemented. A sensible next phase is controlled
invoice/payment and collections reconciliation with the same tenant, allocation, and evidence
model.
