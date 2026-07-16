import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import PayrollReconciliationRun
from app.services.payroll_reconciliation import PayrollReconciliationEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify payroll reconciliation integrity")
    parser.add_argument("--payroll-reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(PayrollReconciliationRun, args.payroll_reconciliation_run_id)
        if run is None:
            raise SystemExit("Payroll reconciliation run not found")
        result = PayrollReconciliationEngine(get_settings()).verify_integrity(session, run)
        print(
            "payroll_reconciliation_run="
            f"{result['payroll_reconciliation_run_id']} reports={result['reports']} "
            f"integrity={result['integrity']}"
        )


if __name__ == "__main__":
    main()
