import argparse
from collections import Counter
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import BankLedgerReconciliationRun, ReconciliationException


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize unmatched Phase 9 records")
    parser.add_argument("--reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(BankLedgerReconciliationRun, args.reconciliation_run_id)
        if run is None:
            raise SystemExit("Reconciliation run not found")
        exceptions = list(
            session.scalars(
                select(ReconciliationException).where(
                    ReconciliationException.reconciliation_run_id == run.id,
                    ReconciliationException.status == "open",
                )
            )
        )
        counts = Counter(item.exception_code for item in exceptions)
        total = run.total_unmatched_bank_amount + run.total_unmatched_ledger_amount
        print(
            f"reconciliation_run={run.id} unmatched_bank={run.unmatched_bank_count} "
            f"unmatched_ledger={run.unmatched_ledger_count} "
            f"unmatched_amount={Decimal(total)} exceptions={dict(sorted(counts.items()))}"
        )


if __name__ == "__main__":
    main()
