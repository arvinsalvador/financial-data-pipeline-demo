import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import InvoiceCollectionsReconciliationRun
from app.services.invoice_collections_reconciliation import (
    InvoiceCollectionsReconciliationEngine,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify invoice collections integrity")
    parser.add_argument("--reconciliation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(InvoiceCollectionsReconciliationRun, args.reconciliation_run_id)
        if run is None:
            raise SystemExit("Invoice collections reconciliation run not found")
        result = InvoiceCollectionsReconciliationEngine(get_settings()).verify_integrity(
            session, run
        )
        print(
            f"reconciliation_run={run.id} reports={result['reports']} "
            f"aging_snapshots={result['aging_snapshots']} integrity={result['status']}"
        )


if __name__ == "__main__":
    main()
