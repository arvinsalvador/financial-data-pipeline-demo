import argparse
import json

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.generation_eligibility import GeneratedDataEligibilityService


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Explain generated-data eligibility for a canonical normalization run"
    )
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--normalization-run-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit(f"Tenant not found: {args.tenant_code}")
        service = GeneratedDataEligibilityService()
        try:
            if args.normalization_run_id is not None:
                items = [service.evaluate(session, tenant.id, args.normalization_run_id)]
            else:
                items = service.candidates(session, tenant.id)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        if not items:
            raise SystemExit("No normalization runs found")
        for item in items:
            print(
                json.dumps(
                    {
                        "eligible": item.eligible,
                        "normalization_run_id": item.normalization_run_id,
                        "tenant_id": item.tenant_id,
                        "status": item.status,
                        "canonical_counts": item.canonical_counts.model_dump(),
                        "source_file_count": item.source_file_count,
                        "missing_prerequisites": item.missing_prerequisites,
                        "blocking_conditions": item.blocking_conditions,
                        "warnings": item.warnings,
                        "already_generated_run_id": item.already_generated_run_id,
                        "input_fingerprint": item.input_fingerprint,
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    main()
