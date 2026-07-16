import argparse
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.invoice_collections_reconciliation import (
    InvoiceCollectionsError,
    InvoiceCollectionsReconciliationEngine,
)
from app.services.invoice_collections_seed import seed_invoice_collections_data


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run Phase 11 invoice collections reconciliation")
    parser.add_argument("--bank-account-id", type=int, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--aging-as-of-date", type=date.fromisoformat, required=True)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_invoice_collections_data(session, settings)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        try:
            run, no_op = InvoiceCollectionsReconciliationEngine(settings).run(
                session,
                tenant,
                args.bank_account_id,
                args.date_from,
                args.date_to,
                args.aging_as_of_date,
                args.force_rerun,
            )
        except InvoiceCollectionsError as error:
            raise SystemExit(str(error)) from error
        print(
            f"reconciliation_run={run.id} status={run.status} version={run.reconciliation_version} "
            f"invoices={run.included_invoice_count} automatic={run.automatically_matched_count} "
            f"partial={run.partially_matched_count} exceptions={run.exception_count} "
            f"rate={run.reconciliation_rate} no_op={str(no_op).lower()}"
        )


if __name__ == "__main__":
    main()
