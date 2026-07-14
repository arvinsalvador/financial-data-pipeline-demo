from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    IngestionControlTotal,
    PipelineRun,
    PipelineRunArtifact,
    RawSourceRow,
    RejectedSourceRow,
    SourceFile,
    SourceSchemaMapping,
    StagingBankTransaction,
    StagingCreditCardTransaction,
    StagingPayrollDetail,
    StagingPayrollSummary,
)
from app.schemas.ingestion import (
    ArtifactResponse,
    ControlTotalResponse,
    IngestionSummary,
    IngestRequest,
    MappingResponse,
    Page,
    RawRowResponse,
    RejectionResponse,
    StepResponse,
)
from app.services.csv_ingestion import CsvIngestionService, IngestionError, IngestionResult
from app.services.governance import AuditService

router = APIRouter()


def _summary(session: Session, run: PipelineRun, *, no_op: bool = False) -> IngestionSummary:
    source = session.get(SourceFile, run.source_file_id) if run.source_file_id else None
    artifacts = session.scalars(
        select(PipelineRunArtifact)
        .where(PipelineRunArtifact.pipeline_run_id == run.id)
        .order_by(PipelineRunArtifact.id)
    ).all()
    metadata = run.metadata_json or {}
    return IngestionSummary(
        id=run.id,
        tenant_id=run.tenant_id,
        source_file_id=run.source_file_id,
        source_filename=source.original_filename if source else None,
        source_system_code=source.source_system.code if source else None,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        records_extracted=run.records_extracted,
        records_accepted=run.records_accepted,
        records_rejected=run.records_rejected,
        connector=metadata.get("connector"),
        mapping_code=metadata.get("mapping_code"),
        mapping_version=metadata.get("mapping_version"),
        ingestion_version=metadata.get("ingestion_version"),
        no_op=no_op,
        error_message=run.error_message,
        steps=[StepResponse.model_validate(item) for item in run.steps],
        artifacts=[ArtifactResponse.model_validate(item) for item in artifacts],
    )


@router.post("/source-files/{source_file_id}/ingest", response_model=IngestionSummary)
def ingest_source_file(
    source_file_id: int,
    body: IngestRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("source_files.ingest"))],
) -> IngestionSummary:
    AuditService().record(
        session,
        context,
        event_type="ingestion.requested",
        entity_type="source_file",
        entity_id=source_file_id,
        action="ingest",
        description="CSV ingestion requested",
        source_file_id=source_file_id,
        metadata={
            "mapping_code": body.mapping_code,
            "ingestion_version": settings.INGESTION_VERSION,
            "force_rerun": body.force_rerun,
        },
    )
    session.commit()
    try:
        result: IngestionResult = CsvIngestionService(settings).ingest(
            session,
            source_file_id,
            context.tenant.id,
            body.mapping_code,
            force_rerun=body.force_rerun,
        )
    except IngestionError as error:
        event_type = (
            "ingestion.checksum_mismatch"
            if "checksum" in str(error).lower()
            else "ingestion.failed"
        )
        AuditService().record(
            session,
            context,
            event_type=event_type,
            entity_type="pipeline_run",
            entity_id=error.run_id,
            action="ingest",
            description="CSV ingestion failed",
            pipeline_run_id=error.run_id,
            source_file_id=source_file_id,
            metadata={
                "error": str(error),
                "mapping_code": body.mapping_code,
                "ingestion_version": settings.INGESTION_VERSION,
            },
        )
        session.commit()
        raise HTTPException(
            status_code=404 if str(error) == "Source file not found" else 422, detail=str(error)
        ) from error
    event_type = (
        "ingestion.no_op"
        if result.no_op
        else (
            "ingestion.completed_with_rejections"
            if result.run.records_rejected
            else "ingestion.completed"
        )
    )
    AuditService().record(
        session,
        context,
        event_type=event_type,
        entity_type="pipeline_run",
        entity_id=result.run.id,
        action="ingest",
        description="CSV ingestion did not create duplicates"
        if result.no_op
        else "CSV ingestion completed",
        pipeline_run_id=result.run.id,
        source_file_id=source_file_id,
        metadata={
            "connector": result.connector,
            "mapping_code": result.mapping_code,
            "mapping_version": result.mapping_version,
            "ingestion_version": result.ingestion_version,
            "extracted": result.run.records_extracted,
            "accepted": result.run.records_accepted,
            "rejected": result.run.records_rejected,
            "forced": body.force_rerun,
        },
    )
    AuditService().record(
        session,
        context,
        event_type="ingestion.mapping_selected",
        entity_type="source_schema_mapping",
        entity_id=result.mapping_code,
        action="select",
        description="Selected a versioned source schema mapping",
        pipeline_run_id=result.run.id,
        source_file_id=source_file_id,
        metadata={
            "mapping_code": result.mapping_code,
            "mapping_version": result.mapping_version,
            "connector": result.connector,
        },
    )
    if not result.no_op:
        AuditService().record(
            session,
            context,
            event_type="ingestion.artifacts_registered",
            entity_type="pipeline_run",
            entity_id=result.run.id,
            action="register_artifacts",
            description="Registered ingestion reports and manifest",
            pipeline_run_id=result.run.id,
            source_file_id=source_file_id,
            metadata={"ingestion_version": result.ingestion_version},
        )
    if body.force_rerun:
        AuditService().record(
            session,
            context,
            event_type="ingestion.forced_rerun",
            entity_type="pipeline_run",
            entity_id=result.run.id,
            action="rerun",
            description="Forced rerun request was handled idempotently",
            pipeline_run_id=result.run.id,
            source_file_id=source_file_id,
            metadata={"no_op": result.no_op},
        )
    session.commit()
    return _summary(session, result.run, no_op=result.no_op)


@router.get("/source-files/{source_file_id}/ingestions", response_model=Page)
def source_ingestions(
    source_file_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page:
    condition = (
        (PipelineRun.tenant_id == context.tenant.id)
        & (PipelineRun.source_file_id == source_file_id)
        & (PipelineRun.run_type == "csv_ingestion")
    )
    total = session.scalar(select(func.count()).select_from(PipelineRun).where(condition)) or 0
    items = session.scalars(
        select(PipelineRun)
        .where(condition)
        .options(selectinload(PipelineRun.steps))
        .order_by(PipelineRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[_summary(session, item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/ingestions/{pipeline_run_id}", response_model=IngestionSummary)
def ingestion_detail(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
) -> IngestionSummary:
    run = session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.id == pipeline_run_id,
            PipelineRun.tenant_id == context.tenant.id,
            PipelineRun.run_type == "csv_ingestion",
        )
        .options(selectinload(PipelineRun.steps))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return _summary(session, run)


def _page(
    session: Session, model: type[Any], conditions: list[Any], page: int, page_size: int
) -> tuple[list[Any], int]:
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    items = session.scalars(
        select(model)
        .where(*conditions)
        .order_by(model.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


@router.get("/ingestions/{pipeline_run_id}/raw-rows", response_model=Page)
def raw_rows(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("raw_rows.view"))],
    row_status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    conditions: list[Any] = [
        RawSourceRow.tenant_id == context.tenant.id,
        RawSourceRow.pipeline_run_id == pipeline_run_id,
    ]
    if row_status:
        conditions.append(RawSourceRow.row_status == row_status)
    items, total = _page(session, RawSourceRow, conditions, page, page_size)
    return Page(
        items=[RawRowResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/raw-source-rows/{raw_row_id}", response_model=RawRowResponse)
def raw_row(
    raw_row_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("raw_rows.view"))],
) -> RawRowResponse:
    item = session.scalar(
        select(RawSourceRow).where(
            RawSourceRow.id == raw_row_id, RawSourceRow.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Raw source row not found")
    return RawRowResponse.model_validate(item)


@router.get("/ingestions/{pipeline_run_id}/rejections", response_model=Page)
def rejections(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("rejected_rows.view"))],
    rejection_code: str | None = None,
    rejection_category: str | None = None,
    severity: str | None = None,
    field_name: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    conditions: list[Any] = [
        RejectedSourceRow.tenant_id == context.tenant.id,
        RejectedSourceRow.pipeline_run_id == pipeline_run_id,
    ]
    for column, value in (
        (RejectedSourceRow.rejection_code, rejection_code),
        (RejectedSourceRow.rejection_category, rejection_category),
        (RejectedSourceRow.severity, severity),
        (RejectedSourceRow.field_name, field_name),
    ):
        if value:
            conditions.append(column == value)
    items, total = _page(session, RejectedSourceRow, conditions, page, page_size)
    return Page(
        items=[RejectionResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/rejected-source-rows/{rejection_id}", response_model=RejectionResponse)
def rejection(
    rejection_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("rejected_rows.view"))],
) -> RejectionResponse:
    item = session.scalar(
        select(RejectedSourceRow).where(
            RejectedSourceRow.id == rejection_id, RejectedSourceRow.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Rejected source row not found")
    return RejectionResponse.model_validate(item)


@router.get(
    "/ingestions/{pipeline_run_id}/control-totals", response_model=list[ControlTotalResponse]
)
def control_totals(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("ingestion_control_totals.view"))
    ],
) -> list[ControlTotalResponse]:
    items = session.scalars(
        select(IngestionControlTotal)
        .where(
            IngestionControlTotal.tenant_id == context.tenant.id,
            IngestionControlTotal.pipeline_run_id == pipeline_run_id,
        )
        .order_by(IngestionControlTotal.id)
    ).all()
    return [ControlTotalResponse.model_validate(item) for item in items]


STAGING_MODELS: dict[str, Any] = {
    "bank-transactions": StagingBankTransaction,
    "credit-card-transactions": StagingCreditCardTransaction,
    "payroll-summaries": StagingPayrollSummary,
    "payroll-details": StagingPayrollDetail,
}


@router.get("/staging/{record_type}", response_model=Page)
def staging_records(
    record_type: str,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("staging_records.view"))],
    source_file_id: int | None = None,
    pipeline_run_id: int | None = None,
    source_system_id: int | None = None,
    source_record_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    model = STAGING_MODELS.get(record_type)
    if model is None:
        raise HTTPException(status_code=404, detail="Staging record type not found")
    conditions: list[Any] = [model.tenant_id == context.tenant.id]
    for column, value in (
        (model.source_file_id, source_file_id),
        (model.pipeline_run_id, pipeline_run_id),
        (model.source_system_id, source_system_id),
        (model.source_record_id, source_record_id),
    ):
        if value is not None:
            conditions.append(column == value)
    items, total = _page(session, model, conditions, page, page_size)
    rendered = [
        {column.name: getattr(item, column.name) for column in model.__table__.columns}
        for item in items
    ]
    return Page(items=rendered, total=total, page=page, page_size=page_size)


@router.get("/schema-mappings", response_model=list[MappingResponse])
def schema_mappings(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("staging_records.view"))],
) -> list[MappingResponse]:
    mappings = session.scalars(
        select(SourceSchemaMapping)
        .where(SourceSchemaMapping.tenant_id == context.tenant.id)
        .options(selectinload(SourceSchemaMapping.columns))
        .order_by(SourceSchemaMapping.mapping_code)
    ).all()
    return [MappingResponse.model_validate(item) for item in mappings]
