import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import PipelineRun, Tenant
from app.services.canonical_normalization import CanonicalNormalizationService, NormalizationError
from app.services.canonical_seed import seed_canonical_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize accepted staging records into canonical finance records"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ingestion-run-id", type=int)
    group.add_argument("--all-eligible", action="store_true")
    parser.add_argument("--mapping-code")
    parser.add_argument("--tenant-code", default="demo_coffee_group")
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    failures = 0
    with SessionLocal() as session:
        seed_canonical_data(session)
        tenant = session.scalar(
            select(Tenant).where(Tenant.code == args.tenant_code, Tenant.status == "active")
        )
        if tenant is None:
            raise SystemExit("Active tenant not found")
        ids = (
            [args.ingestion_run_id]
            if args.ingestion_run_id
            else list(
                session.scalars(
                    select(PipelineRun.id)
                    .where(
                        PipelineRun.tenant_id == tenant.id,
                        PipelineRun.run_type == "csv_ingestion",
                        PipelineRun.status.in_(("completed", "completed_with_rejections")),
                    )
                    .order_by(PipelineRun.id)
                ).all()
            )
        )
        for ingestion_id in ids:
            try:
                result = CanonicalNormalizationService(get_settings()).normalize(
                    session,
                    ingestion_id,
                    tenant.id,
                    args.mapping_code,
                    force_rerun=args.force_rerun,
                )
                print(
                    f"ingestion_run_id={ingestion_id} "
                    f"normalization_run_id={result.run.id} status={result.run.status} "
                    f"canonical={result.run.records_accepted} "
                    f"exceptions={result.run.records_rejected} no_op={result.no_op}"
                )
            except NormalizationError as error:
                failures += 1
                print(f"ingestion_run_id={ingestion_id} failed={error}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
