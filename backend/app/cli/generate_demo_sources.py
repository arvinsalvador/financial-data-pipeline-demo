import argparse
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.canonical_seed import seed_canonical_data
from app.services.generated_sources import GeneratedSourceService, GenerationError


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Generate deterministic demo business CSV sources")
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--seed", type=int, default=settings.GENERATION_RANDOM_SEED)
    parser.add_argument("--generation-date", type=date.fromisoformat, default=date(2026, 7, 14))
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_canonical_data(session)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit(f"Tenant not found: {args.tenant_code}")
        try:
            result = GeneratedSourceService(settings).generate(
                session,
                tenant,
                args.seed,
                args.generation_date,
                args.force_rerun,
            )
        except GenerationError as error:
            raise SystemExit(str(error)) from error
        print(
            f"generated_dataset_run={result.run.id} status={result.run.status} "
            f"files={result.run.file_count} records={result.run.record_count} "
            f"no_op={str(result.no_op).lower()} fingerprint={result.run.input_fingerprint}"
        )


if __name__ == "__main__":
    main()
