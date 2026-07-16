import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import InvoiceCollectionsReconciliationRun, InvoiceCollectionsReport


def main() -> None:
    parser = argparse.ArgumentParser(description="Export reconciled AR aging")
    parser.add_argument("--reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(InvoiceCollectionsReconciliationRun, args.reconciliation_run_id)
        if run is None:
            raise SystemExit("Invoice collections reconciliation run not found")
        report = session.scalar(
            select(InvoiceCollectionsReport).where(
                InvoiceCollectionsReport.reconciliation_run_id == run.id,
                InvoiceCollectionsReport.report_type == "accounts_receivable_aging",
            )
        )
        if report is None:
            raise SystemExit("AR aging report not found")
        print((get_settings().GENERATED_DATA_DIRECTORY.parent / report.relative_path).resolve())


if __name__ == "__main__":
    main()
