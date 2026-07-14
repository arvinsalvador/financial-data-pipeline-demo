import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import BankLedgerReconciliationRun
from app.services.bank_ledger_reconciliation import BankLedgerReconciliationEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Phase 9 reconciliation artifacts")
    parser.add_argument("--reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(BankLedgerReconciliationRun, args.reconciliation_run_id)
        if run is None:
            raise SystemExit("Reconciliation run not found")
        result = BankLedgerReconciliationEngine(get_settings()).verify_integrity(session, run)
        print(
            f"reconciliation_run={result['run_id']} "
            f"reports={result['report_count']} integrity={result['integrity']}"
        )


if __name__ == "__main__":
    main()
