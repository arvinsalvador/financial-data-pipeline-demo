import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant
from app.services.messy_generation import MessyDatasetService, MessyGenerationError
from app.services.messy_seed import seed_messy_data


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Generate a controlled deterministic messy dataset"
    )
    parser.add_argument("--clean-generated-dataset-run-id", type=int, required=True)
    parser.add_argument("--scenario-code", default=settings.DEFAULT_DEFECT_SCENARIO)
    parser.add_argument("--seed", type=int, default=settings.MESSY_GENERATION_RANDOM_SEED)
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        seed_messy_data(session)
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit(f"Tenant not found: {args.tenant_code}")
        try:
            result = MessyDatasetService(settings).generate(
                session,
                tenant,
                args.clean_generated_dataset_run_id,
                args.scenario_code,
                args.seed,
                args.force_rerun,
            )
        except MessyGenerationError as error:
            raise SystemExit(str(error)) from error
        run = result.run
        print(
            f"messy_dataset_run={run.id} status={run.status} scenario={args.scenario_code} "
            f"requested={run.requested_defect_count} applied={run.applied_defect_count} "
            f"skipped={run.skipped_defect_count} failed={run.failed_defect_count} "
            f"expected={run.expected_exception_count} no_op={str(result.no_op).lower()} "
            f"input={run.input_fingerprint} plan={run.defect_plan_fingerprint} "
            f"output={run.output_fingerprint}"
        )


if __name__ == "__main__":
    main()
