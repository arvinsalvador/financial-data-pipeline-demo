import argparse

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import BankLedgerReconciliationRun, Tenant


def main() -> None:
    parser = argparse.ArgumentParser(description="List Phase 9 reconciliation runs")
    parser.add_argument("--tenant-code", default="demo_coffee_group")
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        for run in session.scalars(
            select(BankLedgerReconciliationRun)
            .where(BankLedgerReconciliationRun.tenant_id == tenant.id)
            .order_by(BankLedgerReconciliationRun.id.desc())
        ):
            print(
                f"id={run.id} status={run.status} account={run.bank_account_id} "
                f"period={run.date_from}:{run.date_to} rate={run.reconciliation_rate} "
                f"exceptions={run.exception_count}"
            )


if __name__ == "__main__":
    main()
