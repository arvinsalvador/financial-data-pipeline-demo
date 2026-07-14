import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import SourceFile, Tenant
from app.services.csv_ingestion import CsvIngestionService, IngestionError
from app.services.ingestion_seed import seed_ingestion_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest registered CSV files into raw and staging tables"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-file-id", type=int)
    group.add_argument("--all-eligible", action="store_true")
    parser.add_argument("--mapping-code")
    parser.add_argument("--tenant-code", default="demo_coffee_group")
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    failures = 0
    with SessionLocal() as session:
        seed_ingestion_data(session)
        tenant = session.scalar(
            select(Tenant).where(Tenant.code == args.tenant_code, Tenant.status == "active")
        )
        if tenant is None:
            raise SystemExit("Active tenant not found")
        ids = (
            [args.source_file_id]
            if args.source_file_id
            else list(
                session.scalars(
                    select(SourceFile.id)
                    .where(SourceFile.tenant_id == tenant.id)
                    .order_by(SourceFile.id)
                ).all()
            )
        )
        for source_file_id in ids:
            try:
                result = CsvIngestionService(settings).ingest(
                    session,
                    source_file_id,
                    tenant.id,
                    args.mapping_code,
                    force_rerun=args.force_rerun,
                )
                print(
                    f"source_file_id={source_file_id} run_id={result.run.id} "
                    f"status={result.run.status} extracted={result.run.records_extracted} "
                    f"accepted={result.run.records_accepted} "
                    f"rejected={result.run.records_rejected} no_op={result.no_op}"
                )
            except IngestionError as error:
                failures += 1
                print(f"source_file_id={source_file_id} failed={error}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
