import argparse
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.bank_ledger_reconciliation import (
    BankLedgerReconciliationEngine,
    ReconciliationError,
)
from app.services.reconciliation_seed import seed_reconciliation_data


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run Phase 9 bank-to-ledger reconciliation")
    parser.add_argument("--bank-account-id", type=int, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--generated-dataset-run-id", type=int)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_reconciliation_data(session, settings)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        try:
            run, no_op = BankLedgerReconciliationEngine(settings).run(
                session,
                tenant,
                args.bank_account_id,
                args.date_from,
                args.date_to,
                args.generated_dataset_run_id,
                args.force_rerun,
            )
        except ReconciliationError as error:
            raise SystemExit(str(error)) from error
        print(
            f"reconciliation_run={run.id} status={run.status} "
            f"version={run.reconciliation_version} matched={run.total_matched_amount} "
            f"rate={run.reconciliation_rate} suggestions={run.suggested_match_count} "
            f"exceptions={run.exception_count} no_op={str(no_op).lower()}"
        )


if __name__ == "__main__":
    main()
