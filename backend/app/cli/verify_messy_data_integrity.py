import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import MessyDatasetRun, Tenant
from app.services.messy_generation import MessyDatasetService, MessyGenerationError


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Verify controlled messy-data integrity")
    parser.add_argument("--messy-dataset-run-id", type=int, required=True)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        run = session.scalar(
            select(MessyDatasetRun).where(
                MessyDatasetRun.id == args.messy_dataset_run_id,
                MessyDatasetRun.tenant_id == (tenant.id if tenant else -1),
            )
        )
        if tenant is None or run is None:
            raise SystemExit("Tenant or messy dataset not found")
        try:
            result = MessyDatasetService(settings).verify(session, tenant.id, run.id)
        except MessyGenerationError as error:
            raise SystemExit(str(error)) from error
        print(
            f"messy data integrity verified: run={run.id} files={result['files']} "
            f"mutations={result['mutations']} expectations={result['expectations']} "
            f"controls={result['controls']} artifacts={result['artifacts']} "
            f"clean_integrity={(run.metadata_json or {}).get('clean_file_integrity')}"
        )


if __name__ == "__main__":
    main()
