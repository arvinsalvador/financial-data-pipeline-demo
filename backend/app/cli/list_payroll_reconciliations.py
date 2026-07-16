import argparse

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PayrollReconciliationRun, Tenant


def main() -> None:
    parser = argparse.ArgumentParser(description="List payroll reconciliation runs")
    parser.add_argument("--tenant-code", default="demo_coffee_group")
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        for run in session.scalars(
            select(PayrollReconciliationRun)
            .where(PayrollReconciliationRun.tenant_id == tenant.id)
            .order_by(PayrollReconciliationRun.id.desc())
        ):
            print(
                f"id={run.id} status={run.status} period={run.date_from}:{run.date_to} "
                f"settlement={run.settlement_model} rate={run.reconciliation_rate} "
                f"exceptions={run.exception_count}"
            )


if __name__ == "__main__":
    main()
