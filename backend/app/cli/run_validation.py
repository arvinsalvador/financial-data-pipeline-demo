import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.validation_engine_service import ValidationEngine, ValidationEngineError
from app.services.validation_seed import seed_validation_data


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the Phase 8 validation engine")
    parser.add_argument(
        "--target-type",
        choices=("tenant", "source_file", "pipeline", "generated_dataset", "messy_dataset"),
        default="tenant",
    )
    parser.add_argument("--target-id", type=int)
    parser.add_argument("--rule-set-code", default=settings.DEFAULT_VALIDATION_RULE_SET)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_validation_data(session)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit("Tenant not found")
        try:
            run, no_op = ValidationEngine(settings).run(
                session,
                tenant,
                args.target_type,
                args.target_id,
                args.rule_set_code,
                args.force_rerun,
            )
        except ValidationEngineError as error:
            raise SystemExit(str(error)) from error
        print(
            f"validation_run={run.id} status={run.status} target={run.target_type}:{run.target_id} "
            f"version={run.validation_version} rules={run.total_rules} issues={run.total_issues} "
            f"critical={run.critical_count} error={run.error_count} warning={run.warning_count} "
            f"no_op={str(no_op).lower()} fingerprint={run.input_fingerprint}"
        )


if __name__ == "__main__":
    main()
