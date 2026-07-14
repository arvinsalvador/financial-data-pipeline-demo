# Phase 8: validation and data quality engine

Phase 8 introduces validation version `1.0.0` as the shared source of truth for downstream reconciliation, forecasting, dashboards, and AI. It validates raw source files, pipeline/staging inputs, canonical records and lineage, clean generated datasets, and controlled messy datasets. It detects issues only; it does not reconcile records or implement issue-resolution workflow.

## Architecture and lifecycle

`ValidationEngine` loads a tenant-owned target and its checksums, resolves an active `ValidationRuleSet`, calculates a fingerprint over the target, validation version, rule configuration, and rule implementation, and executes rules through `ValidationRuleRegistry`. Each plug-in returns a `ValidationRuleOutcome` containing deterministic findings and evaluated counts. Results become immutable `ValidationRunResult`, `ValidationIssue`, `ValidationSummary`, `ValidationStatistic`, and `ValidationReport` records.

The `validation_engine` pipeline records 13 steps: schema, required fields, identifiers, dates, amounts, duplicates, relationships, financial rules, business rules, controls, summary, reports, and finalization. Identical inputs return the completed run; `--force-rerun` verifies persisted counts and physical report checksums before returning a no-op.

## Rule configuration and severity

The seeded `financial_data_quality_v1` rule set contains 26 ordered, independently enabled rules. Every rule stores its code, description, group, target entity, severity, version, execution order, and JSON configuration.

Groups cover schema, required fields, identifiers, dates, monetary values, duplicates, relationships and canonical lineage, invoice/payment/AP/payroll/GL/running-balance checks, ingestion/generated/messy controls, invoice/payment/deal business rules, and cross-file payment/vendor/forecast relationships.

Severity values are `information`, `warning`, `error`, and `critical`. New findings have status `open`; the schema reserves `acknowledged`, `ignored`, and `resolved` for a later workflow, which Phase 8 intentionally does not implement.

## Control totals

Validation consumes existing authoritative ingestion, normalization, generated-data, and messy-data controls instead of recalculating competing totals. Rules verify accepted plus rejected versus extracted rows through ingestion controls, generated source invariants, expected-exception versus applied-mutation counts, invoice lines, payment applications, AP totals, payroll entries, GL journal balance, and opening/closing cash movement consistency.

## Reports

Every completed run writes seven immutable UTF-8 JSON reports under `data/generated/reports/validation/<tenant>/run_<fingerprint>/`:

- `validation_summary.json`
- `validation_report.json`
- `validation_statistics.json`
- `validation_by_severity.json`
- `validation_by_rule.json`
- `validation_by_file.json`
- `validation_by_entity.json`

Each contains validation version, target, input fingerprint, and summary fingerprint. Files are registered both as validation reports and pipeline artifacts with SHA-256 checksums.

## API

- `POST /api/v1/validation/run`
- `GET /api/v1/validation/runs` and `/validation/runs/{id}`
- `GET /api/v1/validation/runs/{id}/results`
- `GET /api/v1/validation/issues` and `/validation/issues/{id}`
- `GET /api/v1/validation/summary`
- `GET /api/v1/validation/statistics`
- `GET /api/v1/validation/reports`
- `GET /api/v1/validation/rules`

Run and issue queries support tenant-enforced filters for pipeline, file, source-file ID, severity, rule, entity, status, target, and date. Tenant is derived from governed request context and cannot be overridden by query input.

## CLI and manual verification

These commands were exercised against the demo database; IDs remain deployment-specific:

```bash
docker compose exec backend python -m app.cli.list_validation_rules
docker compose exec backend python -m app.cli.run_validation --target-type messy_dataset --target-id 1
docker compose exec backend python -m app.cli.validation_summary --validation-run-id 9
docker compose exec backend python -m app.cli.verify_validation_integrity --validation-run-id 9
docker compose exec backend python -m app.cli.run_validation --target-type messy_dataset --target-id 1 --force-rerun
```

Use `source_file`, `pipeline`, `generated_dataset`, or `tenant` as alternate target types. To inspect issues and reports through the API:

```bash
curl -H "X-Tenant-Code: demo_coffee_group" -H "X-Demo-User: analyst@demo.local" "http://localhost:8000/api/v1/validation/issues?run_id=9&severity=critical"
curl -H "X-Tenant-Code: demo_coffee_group" -H "X-Demo-User: analyst@demo.local" "http://localhost:8000/api/v1/validation/reports?run_id=9"
curl -H "X-Tenant-Code: demo_coffee_group" -H "X-Demo-User: analyst@demo.local" "http://localhost:8000/api/v1/validation/summary?run_id=9"
```

Repeat a request with another authorized tenant header to verify isolation; IDs owned by Demo Coffee Group return no data or `404` in another tenant context.

## Frontend

The **Validation** workspace provides Dashboard, Runs, Issues, Statistics, Reports, Rules, and Summary views. Analysts can choose a target, run or force-verify validation, inspect rule execution and duration, filter issues, compare severity/file/entity statistics, and view report checksums. Viewers receive read-only access and cannot execute validation.

## Audit events

The API records validation started, completed, failed, rule failed/skipped/disabled, and report generated events with tenant, actor, pipeline, and target context.

## Known limitations

- Phase 8 does not acknowledge, ignore, resolve, assign, or reconcile issues.
- Generic raw files without a versioned generated schema receive datatype and row-level checks but no invented expected-column contract.
- Expected-exception coverage is reported through controls; issue-to-expectation scoring and false-positive/negative analysis belongs to reconciliation.
- Rule execution is synchronous and intentionally does not use Prefect.
- Dates use deterministic parsing and future boundaries; tenant-specific fiscal-period calendars can be added through later rule configuration.

The recommended next phase is reconciliation consuming `ValidationIssue`, summaries, and immutable report fingerprints rather than recreating validation logic.
