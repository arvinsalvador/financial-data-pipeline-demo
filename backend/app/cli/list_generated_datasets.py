import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import GeneratedDatasetRun, Tenant


def main() -> None:
    parser = argparse.ArgumentParser(description="List generated demo datasets")
    parser.add_argument("--tenant-code", default=get_settings().DEFAULT_DEMO_TENANT_CODE)
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit(f"Tenant not found: {args.tenant_code}")
        runs = session.scalars(
            select(GeneratedDatasetRun)
            .where(GeneratedDatasetRun.tenant_id == tenant.id)
            .order_by(GeneratedDatasetRun.id.desc())
        ).all()
        for run in runs:
            print(
                f"id={run.id} date={run.generation_date} seed={run.random_seed} "
                f"status={run.status} files={run.file_count} records={run.record_count} "
                f"fingerprint={run.input_fingerprint}"
            )


if __name__ == "__main__":
    main()
