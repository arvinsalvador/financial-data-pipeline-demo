# Phase 12.2: generated-data eligibility

Phase 12.2 stabilizes the path from uploaded source CSVs to clean generated business sources. It
does not implement cash forecasting.

## Workflow

1. Upload a CSV under `Kaggle Small Business Financial Dataset`.
2. Profile the file.
3. Ingest it with the matching source schema mapping.
4. Normalize the ingestion with the matching canonical mapping.
5. Open **Generated data** and select the newest eligible normalization snapshot.
6. Generate with a deterministic seed and date.
7. Inspect registered files, controls, lineage links, and generation history.
8. Use the successful clean run as the input to **Messy data** and reconciliation workflows.

The standard five-file demo set is:

| File | Ingestion mapping | Normalization mapping |
| --- | --- | --- |
| `checking_account_main.csv` | `checking_account_main_v1` | `bank_transaction_main_v1` |
| `checking_account_secondary.csv` | `checking_account_secondary_v1` | `bank_transaction_secondary_v1` |
| `credit_card_account.csv` | `credit_card_account_v1` | `credit_card_transaction_v1` |
| `gusto_payroll.csv` | `gusto_payroll_v1` | `payroll_summary_v1` |
| `gusto_payroll_bc.csv` | `gusto_payroll_bc_v1` | `payroll_detail_v1` |

Payroll detail supersedes payroll summary, so `gusto_payroll.csv` is optional when canonical payroll
detail exists. Credit-card and payroll history are optional generation enrichments and produce
warnings when absent. A completed snapshot is eligible when it contains a canonical bank inflow,
active financial accounts, canonical lineage, matched normalization controls, and no open critical
normalization exception.

Each candidate is a cumulative, tenant-scoped canonical snapshot ending at the selected
normalization run. Financial transactions use `normalization_run_id <= selected run`; payroll uses
`pipeline_run_id <= selected run`. This preserves all previously completed source types while
giving generation an explicit, auditable snapshot.

## API

`GET /api/v1/generated-datasets/eligible-inputs` requires `generated_datasets.view` and returns
newest-first candidates with:

- status and completion time;
- authoritative canonical counts and source-file count;
- missing prerequisites, blockers, and non-blocking warnings;
- existing generated run ID;
- stable canonical-input fingerprint.

`POST /api/v1/generated-datasets` requires `generated_datasets.execute`:

```json
{
  "normalization_run_id": 20,
  "random_seed": 20260714,
  "generation_date": "2026-07-14",
  "force_rerun": false
}
```

The backend resolves tenant and actor from the governed development headers, verifies run
ownership through the shared eligibility service, and rejects cross-tenant IDs as unavailable.
Identical canonical inputs, seed, date, and generator version return the existing completed run.

## Files, manifests, and reset safety

Clean files are stored under a relative path containing both the database run ID and input
fingerprint, for example:

```text
generated/clean/demo_coffee_group/run_00000005_385d00c3f7b5/customers.csv
```

The same directory key is used for manifests and reports. Including the fingerprint prevents a
database reset from reusing a run ID that already exists on disk. Existing output is never silently
overwritten.

Generation fails if all output collections are empty. Successful runs register ten CSV files,
generation controls, canonical links, a generation manifest, a relationship manifest, an inventory,
and control/exception reports.

## Permissions and tenant isolation

`platform_admin`, `cfo_user`, and `finance_analyst` have view and execute permissions.
`client_viewer` can view generated history but cannot execute generation. Backend permission and
tenant checks are authoritative; frontend button visibility is only a convenience.

Eligibility, history, files, records, controls, and links are tenant scoped. A normalization run
from another tenant cannot be resolved or generated.

## Clean reset and diagnostics

```bash
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli.bootstrap_demo_environment
docker compose exec backend python -m app.cli.verify_demo_environment
docker compose exec backend python -m app.cli.check_generation_eligibility
docker compose exec backend python -m app.cli.check_generation_eligibility --normalization-run-id 20
docker compose exec backend python -m app.cli.generate_demo_sources --normalization-run-id 20 --seed 20260714 --generation-date 2026-07-14
docker compose exec backend python -m app.cli.list_generated_datasets
docker compose exec backend python -m app.cli.verify_generated_data_integrity --run-id 5
```

Bootstrap is idempotent and must provide the demo tenant/users, roles, permissions, ingestion and
normalization mappings, pipeline definitions, and these source systems:

- `Kaggle Small Business Financial Dataset`;
- `Generated Demo Business Sources`;
- `Generated Demo Business Messy Sources`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Generated page has no candidates | No normalization run exists | Complete profiling, ingestion, and normalization |
| Normalization completed but canonical counts are zero | Mapping or ingestion did not persist supported staging rows | Inspect ingestion controls, staging rows, mapping identity, and normalization exceptions |
| Candidate is not eligible | Missing bank inflow, account, lineage, matched control, or critical exception blocker | Read the returned prerequisites and blockers; repair the upstream run |
| Eligible run is not shown | Wrong tenant/actor or stale page context | Switch to the correct governed context; the page remounts and reloads eligibility |
| Generate button is hidden | Actor lacks execute permission | Use `platform_admin`, `cfo_user`, or `finance_analyst` |
| Generation returns an existing run | Deterministic input already completed | Inspect the returned no-op run or change an intentional input |
| Generation produces zero output | Input resolver or generator defect | The run now fails with an explicit zero-output diagnostic |
| Generation collides after database reset | Legacy output used a reused numeric run directory | Phase 12.2 fingerprinted directories prevent new collisions |
| Messy Data is empty | No successful clean generated run | Generate a clean dataset first |

## Verification

Run the backend suite and static checks, frontend lint/type/build checks, then execute integrity
verification against the generated run. The integrity command exits nonzero for missing or
cross-tenant normalization linkage, zero canonical inputs/output, missing or invalid files,
checksum differences, source registration mismatch, duplicate IDs, unbalanced journals, failed
controls, cross-tenant links, or manifest inventory differences.
