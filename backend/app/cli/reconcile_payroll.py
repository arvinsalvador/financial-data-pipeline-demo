import argparse
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.payroll_reconciliation import (
    SETTLEMENT_MODELS,
    PayrollReconciliationEngine,
    PayrollReconciliationError,
)
from app.services.payroll_reconciliation_seed import seed_payroll_reconciliation_data


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run Phase 10 payroll reconciliation")
    parser.add_argument("--payroll-bank-account-id", type=int, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--settlement-model",
        choices=sorted(SETTLEMENT_MODELS),
        default=settings.PAYROLL_RECONCILIATION_DEFAULT_SETTLEMENT_MODEL,
    )
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_payroll_reconciliation_data(session, settings)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        try:
            run, no_op = PayrollReconciliationEngine(settings).run(
                session,
                tenant,
                args.payroll_bank_account_id,
                args.date_from,
                args.date_to,
                args.settlement_model,
                args.force_rerun,
            )
        except PayrollReconciliationError as error:
            raise SystemExit(str(error)) from error
        print(
            f"payroll_reconciliation_run={run.id} status={run.status} "
            f"version={run.reconciliation_version} "
            f"payroll_runs={run.included_payroll_run_count} "
            f"automatic={run.automatically_matched_count} "
            f"partial={run.partially_matched_count} exceptions={run.exception_count} "
            f"rate={run.reconciliation_rate} no_op={str(no_op).lower()}"
        )


if __name__ == "__main__":
    main()
