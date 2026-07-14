import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant, ValidationRun
from app.services.validation_engine_service import ValidationEngine, ValidationEngineError


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Verify validation results and reports")
    parser.add_argument("--validation-run-id", type=int, required=True)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    args = parser.parse_args()
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        run = session.scalar(
            select(ValidationRun).where(
                ValidationRun.id == args.validation_run_id,
                ValidationRun.tenant_id == (tenant.id if tenant else -1),
            )
        )
        if tenant is None or run is None:
            raise SystemExit("Tenant or validation run not found")
        try:
            result = ValidationEngine(settings).verify(session, tenant.id, run.id)
        except ValidationEngineError as error:
            raise SystemExit(str(error)) from error
        print(
            f"validation integrity verified: run={run.id} rules={result['rules']} "
            f"issues={result['issues']} reports={result['reports']} "
            f"statistics={result['statistics']} version={run.validation_version}"
        )


if __name__ == "__main__":
    main()
