import argparse

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ValidationRun, ValidationSummary


def main() -> None:
    parser = argparse.ArgumentParser(description="Show a validation summary")
    parser.add_argument("--validation-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.get(ValidationRun, args.validation_run_id)
        summary = session.scalar(
            select(ValidationSummary).where(
                ValidationSummary.validation_run_id == args.validation_run_id
            )
        )
        if run is None or summary is None:
            raise SystemExit("Validation run or summary not found")
        print(
            f"validation_run={run.id} status={summary.overall_status} issues={summary.issue_count} "
            f"severity={summary.counts_by_severity_json} rules={summary.counts_by_rule_json} "
            f"files={summary.counts_by_file_json} entities={summary.counts_by_entity_json} "
            f"summary_fingerprint={summary.summary_fingerprint}"
        )


if __name__ == "__main__":
    main()
