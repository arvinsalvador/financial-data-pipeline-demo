# Phase 7: controlled messy data and expected exceptions

Phase 7 creates deterministic, deliberately defective copies of completed Phase 6 datasets. Clean CSVs are read-only prerequisites: every messy file is written beneath `data/generated/messy/`, linked to its clean `GeneratedSourceFile`, registered as a normal immutable `SourceFile`, and checksum-verified before and after mutation.

This phase creates test inputs and ground truth. It does **not** run validation, matching, reconciliation, exception resolution, or forecast calculation.

## Reproducibility and scenarios

Messy generator version `1.0.0` defaults to seed `20260714`. Its input fingerprint covers the tenant, clean-run fingerprint and file checksums, generator version, scenario code/version, and seed. Stable row sampling, explicit rule order, and conflict policy `skip_later` produce a deterministic plan. The output fingerprint covers the plan, ordered expectation fingerprints, and every messy checksum.

Built-in, versioned scenarios are:

- `light_messy_v1`: six focused rules for a quick smoke dataset.
- `standard_messy_v1`: 30 rules spanning 36 requested operations on the full demo dataset. The normal Phase 6 files apply 35 and explicitly skip `invalid_running_balance`, because the clean ledger intentionally has no running-balance column.
- `hostile_messy_v1`: the standard rules at doubled requested counts.

Rules cover duplicate and near-duplicate records, missing identifiers, mixed or invalid dates, invalid monetary formats, customer/vendor typos, invoice/AP duplication and amount mismatch, split/combined/missing/overpayments, payroll mismatches, unbalanced/missing/invalid ledger data, stale assumptions, invalid scenarios, and relationship breaks. Ineligible or conflicting requests are retained as skipped mutations with reasons; they are never silently discarded.

## Ground truth, controls, and artifacts

Every attempted operation creates a `DataMutation`. Every applied mutation has one linked `ExpectedException`, including the expected code, severity, location, record key, column, message pattern, relationship metadata, and a deterministic fingerprint. These records are expectations, not detected production issues.

Controls compare clean and messy file/row counts, applied mutations and expectations, clean checksums, duplicate and missing-ID deltas, and intentional relationship deltas. Generation writes five immutable JSON artifacts:

- `mutation_plan.json`
- `mutation_manifest.json`
- `expected_exceptions.json`
- `messy_file_inventory.json`
- `messy_generation_summary.json`

The integrity verifier rechecks tenant ownership, clean and messy physical checksums, registered source checksums, file and mutation counts, expectation links and uniqueness, controls, all artifact checksums/metadata, and the recomputed output fingerprint.

## API and permissions

Core endpoints are:

- `POST /api/v1/messy-datasets`
- `GET /api/v1/messy-datasets` and `GET /api/v1/messy-datasets/{id}`
- `GET /api/v1/messy-datasets/{id}/files`
- `GET /api/v1/messy-datasets/{id}/mutations`
- `GET /api/v1/messy-datasets/{id}/expected-exceptions`
- `GET /api/v1/messy-datasets/{id}/control-totals`
- `GET /api/v1/data-mutations/{id}` and `GET /api/v1/expected-exceptions/{id}`
- `GET /api/v1/defect-scenarios` and `GET /api/v1/defect-scenarios/{id}`

Mutation and exception lists support server-side filters. Admin, CFO, and analyst roles can execute and inspect. The viewer can inspect messy datasets and expectations but cannot execute generation or inspect scenario configuration.

The **Messy data** frontend page provides scenario selection, clean-run selection, seed and force-verification controls, run history, fingerprints, file inventory, mutation and expectation filters, controls, and pipeline/artifact status. Displayed controls remain backend-authoritative.

## Commands

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.seed_governance
docker compose exec backend python -m app.cli.list_defect_scenarios
docker compose exec backend python -m app.cli.generate_messy_dataset --clean-generated-dataset-run-id 7 --scenario-code standard_messy_v1 --seed 20260714
docker compose exec backend python -m app.cli.generate_messy_dataset --clean-generated-dataset-run-id 7 --scenario-code standard_messy_v1 --seed 20260714 --force-rerun
docker compose exec backend python -m app.cli.verify_messy_data_integrity --messy-dataset-run-id 1
docker compose exec backend python -m app.cli.summarize_expected_exceptions --messy-dataset-run-id 1
```

The identical forced command returns the verified existing run with `no_op=true`. Change the seed to obtain a different deterministic selection, or change the scenario to compare defect density. Run IDs are deployment-specific; select a completed clean run from `list_generated_datasets`.

## Known limitations

- Phase 7 intentionally does not detect whether downstream logic found an expected issue.
- Mutations operate on generated CSV semantics and do not simulate arbitrary binary corruption.
- Unsupported encoding corruption is skipped by design to keep registered CSV artifacts safe and portable.
- Small clean datasets can make rules ineligible; the manifest records each skip and reason.
- Later phases should ingest these CSVs, reconcile actual results against expected exceptions, and track false positives/negatives without modifying Phase 7 ground truth.
