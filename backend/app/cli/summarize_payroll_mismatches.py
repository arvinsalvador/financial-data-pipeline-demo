import argparse
from collections import Counter

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PayrollReconciliationException, PayrollReconciliationRun


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize payroll reconciliation mismatches")
    parser.add_argument("--payroll-reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(PayrollReconciliationRun, args.payroll_reconciliation_run_id)
        if run is None:
            raise SystemExit("Payroll reconciliation run not found")
        values = list(
            session.scalars(
                select(PayrollReconciliationException).where(
                    PayrollReconciliationException.payroll_reconciliation_run_id == run.id,
                    PayrollReconciliationException.status == "open",
                )
            )
        )
        counts = Counter(item.exception_code for item in values)
        print(
            f"payroll_reconciliation_run={run.id} "
            f"unmatched_payroll={run.unmatched_payroll_count} "
            f"unmatched_bank={run.unmatched_bank_count} "
            f"unmatched_gl={run.unmatched_gl_count} "
            f"exceptions={dict(sorted(counts.items()))}"
        )


if __name__ == "__main__":
    main()
