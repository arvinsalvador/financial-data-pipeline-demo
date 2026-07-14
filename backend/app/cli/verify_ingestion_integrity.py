from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    PipelineRun,
    RawSourceRow,
    RejectedSourceRow,
    SourceFile,
    StagingBankTransaction,
    StagingCreditCardTransaction,
    StagingPayrollDetail,
    StagingPayrollSummary,
)
from app.services.checksum import calculate_sha256


def main() -> None:
    settings = get_settings()
    errors: list[str] = []
    staging_models = (
        StagingBankTransaction,
        StagingCreditCardTransaction,
        StagingPayrollSummary,
        StagingPayrollDetail,
    )
    with SessionLocal() as session:
        runs = session.scalars(
            select(PipelineRun).where(
                PipelineRun.run_type == "csv_ingestion",
                PipelineRun.status.in_(("completed", "completed_with_rejections")),
            )
        ).all()
        for run in runs:
            raw_count = (
                session.scalar(
                    select(func.count())
                    .select_from(RawSourceRow)
                    .where(RawSourceRow.pipeline_run_id == run.id)
                )
                or 0
            )
            rejected_rows = (
                session.scalar(
                    select(func.count(func.distinct(RejectedSourceRow.raw_source_row_id))).where(
                        RejectedSourceRow.pipeline_run_id == run.id
                    )
                )
                or 0
            )
            staging_count = sum(
                session.scalar(
                    select(func.count()).select_from(model).where(model.pipeline_run_id == run.id)
                )
                or 0
                for model in staging_models
            )
            if (
                raw_count != staging_count + rejected_rows
                or run.records_extracted != run.records_accepted + run.records_rejected
            ):
                errors.append(f"run {run.id}: row-count invariant failed")
            mismatched_raw = (
                session.scalar(
                    select(func.count())
                    .select_from(RawSourceRow)
                    .where(
                        RawSourceRow.pipeline_run_id == run.id,
                        RawSourceRow.tenant_id != run.tenant_id,
                    )
                )
                or 0
            )
            if mismatched_raw:
                errors.append(f"run {run.id}: cross-tenant raw lineage")
            for model in staging_models:
                broken = (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .join(RawSourceRow, RawSourceRow.id == model.raw_source_row_id)
                        .where(
                            model.pipeline_run_id == run.id,
                            (model.tenant_id != RawSourceRow.tenant_id)
                            | (model.source_file_id != RawSourceRow.source_file_id),
                        )
                    )
                    or 0
                )
                if broken:
                    errors.append(
                        f"run {run.id}: cross-tenant staging lineage in {model.__tablename__}"
                    )
        for source in session.scalars(select(SourceFile)).all():
            path = (settings.REGISTERED_RAW_DIRECTORY / source.stored_filename).resolve()
            root = settings.REGISTERED_RAW_DIRECTORY.resolve()
            if (
                path.parent != root
                or not path.is_file()
                or calculate_sha256(path) != source.sha256_checksum
            ):
                errors.append(f"source file {source.id}: immutable checksum/path failure")
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print(f"ingestion integrity verified: runs={len(runs)} errors=0")


if __name__ == "__main__":
    main()
