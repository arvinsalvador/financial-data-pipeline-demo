import argparse
from collections import Counter

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import InvoiceCollectionsException, InvoiceCollectionsReconciliationRun


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize unmatched invoice collections")
    parser.add_argument("--reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(InvoiceCollectionsReconciliationRun, args.reconciliation_run_id)
        if run is None:
            raise SystemExit("Invoice collections reconciliation run not found")
        values = list(
            session.scalars(
                select(InvoiceCollectionsException).where(
                    InvoiceCollectionsException.reconciliation_run_id == run.id,
                    InvoiceCollectionsException.status == "open",
                )
            )
        )
        counts = Counter(item.exception_code for item in values)
        print(
            f"reconciliation_run={run.id} unmatched_invoices={run.unmatched_invoice_count} "
            f"unmatched_payments={run.unmatched_payment_count} "
            f"unmatched_deposits={run.unmatched_deposit_count} "
            f"unmatched_gl={run.unmatched_gl_count} "
            f"exceptions={dict(sorted(counts.items()))}"
        )


if __name__ == "__main__":
    main()
