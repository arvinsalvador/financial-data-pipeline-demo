from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    BankAccount,
    BankTransaction,
    CanonicalRecordLineage,
    Counterparty,
    CreditAccount,
    CreditCardTransaction,
    Employee,
    FinancialAccount,
    FinancialTransaction,
    NormalizationControlTotal,
    NormalizationException,
    PayrollEntry,
    PayrollRun,
    PipelineRun,
    PipelineRunArtifact,
    SourceFile,
    TransactionCategory,
)
from app.schemas.ingestion import ArtifactResponse, Page, StepResponse
from app.schemas.normalization import (
    NormalizationControlResponse,
    NormalizationExceptionResponse,
    NormalizationSummary,
    NormalizeRequest,
)
from app.services.canonical_normalization import (
    CanonicalNormalizationService,
    NormalizationError,
    NormalizationResult,
)
from app.services.governance import AuditService

router = APIRouter()


def _summary(session: Session, run: PipelineRun, no_op: bool = False) -> NormalizationSummary:
    metadata = run.metadata_json or {}
    artifacts = session.scalars(
        select(PipelineRunArtifact)
        .where(PipelineRunArtifact.pipeline_run_id == run.id)
        .order_by(PipelineRunArtifact.id)
    ).all()
    exceptions = (
        session.scalar(
            select(func.count())
            .select_from(NormalizationException)
            .where(NormalizationException.pipeline_run_id == run.id)
        )
        or 0
    )
    return NormalizationSummary(
        id=run.id,
        tenant_id=run.tenant_id,
        source_file_id=run.source_file_id,
        ingestion_run_id=metadata.get("ingestion_run_id"),
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        staging_count=run.records_extracted,
        canonical_count=run.records_accepted,
        exception_count=exceptions,
        mapping_code=metadata.get("mapping_code"),
        mapping_version=metadata.get("mapping_version"),
        normalization_version=metadata.get("normalization_version"),
        no_op=no_op,
        error_message=run.error_message,
        steps=[StepResponse.model_validate(item) for item in run.steps],
        artifacts=[ArtifactResponse.model_validate(item) for item in artifacts],
    )


@router.post("/ingestions/{ingestion_run_id}/normalize", response_model=NormalizationSummary)
def normalize_ingestion(
    ingestion_run_id: int,
    body: NormalizeRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("normalization.execute"))],
) -> NormalizationSummary:
    AuditService().record(
        session,
        context,
        event_type="normalization.requested",
        entity_type="pipeline_run",
        entity_id=ingestion_run_id,
        action="normalize",
        description="Canonical normalization requested",
        pipeline_run_id=ingestion_run_id,
        metadata={
            "mapping_code": body.mapping_code,
            "normalization_version": settings.NORMALIZATION_VERSION,
            "force_rerun": body.force_rerun,
        },
    )
    session.commit()
    try:
        result: NormalizationResult = CanonicalNormalizationService(settings).normalize(
            session,
            ingestion_run_id,
            context.tenant.id,
            body.mapping_code,
            force_rerun=body.force_rerun,
        )
    except NormalizationError as error:
        AuditService().record(
            session,
            context,
            event_type="normalization.failed",
            entity_type="pipeline_run",
            entity_id=error.run_id,
            action="normalize",
            description="Canonical normalization failed",
            pipeline_run_id=error.run_id,
            metadata={"error": str(error), "ingestion_run_id": ingestion_run_id},
        )
        session.commit()
        raise HTTPException(
            status_code=404 if str(error) == "Ingestion run not found" else 422, detail=str(error)
        ) from error
    event_type = (
        "normalization.no_op"
        if result.no_op
        else (
            "normalization.completed_with_exceptions"
            if result.run.status == "completed_with_exceptions"
            else "normalization.completed"
        )
    )
    AuditService().record(
        session,
        context,
        event_type=event_type,
        entity_type="pipeline_run",
        entity_id=result.run.id,
        action="normalize",
        description="Canonical normalization handled idempotently"
        if result.no_op
        else "Canonical normalization completed",
        pipeline_run_id=result.run.id,
        source_file_id=result.run.source_file_id,
        metadata={
            "ingestion_run_id": ingestion_run_id,
            "mapping_code": result.mapping.code,
            "mapping_version": result.mapping.version,
            "normalization_version": settings.NORMALIZATION_VERSION,
            "canonical_count": result.run.records_accepted,
            "exception_count": result.run.records_rejected,
        },
    )
    if not result.no_op:
        AuditService().record(
            session,
            context,
            event_type="normalization.artifacts_registered",
            entity_type="pipeline_run",
            entity_id=result.run.id,
            action="register_artifacts",
            description="Registered canonical normalization artifacts",
            pipeline_run_id=result.run.id,
            source_file_id=result.run.source_file_id,
        )
    if body.force_rerun:
        AuditService().record(
            session,
            context,
            event_type="normalization.forced_rerun",
            entity_type="pipeline_run",
            entity_id=result.run.id,
            action="rerun",
            description="Forced normalization rerun handled safely",
            pipeline_run_id=result.run.id,
            metadata={"no_op": result.no_op},
        )
    session.commit()
    return _summary(session, result.run, result.no_op)


@router.get("/ingestions/{ingestion_run_id}/normalizations", response_model=Page)
def normalization_history(
    ingestion_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("canonical_records.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page:
    conditions = [
        PipelineRun.tenant_id == context.tenant.id,
        PipelineRun.run_type == "canonical_normalization",
        PipelineRun.metadata_json["ingestion_run_id"].as_integer() == ingestion_run_id,
    ]
    total = session.scalar(select(func.count()).select_from(PipelineRun).where(*conditions)) or 0
    items = session.scalars(
        select(PipelineRun)
        .where(*conditions)
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


@router.get("/normalizations/{pipeline_run_id}", response_model=NormalizationSummary)
def normalization_detail(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("canonical_records.view"))],
) -> NormalizationSummary:
    run = session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.id == pipeline_run_id,
            PipelineRun.tenant_id == context.tenant.id,
            PipelineRun.run_type == "canonical_normalization",
        )
        .options(selectinload(PipelineRun.steps))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Normalization not found")
    return _summary(session, run)


CANONICAL_MODELS: dict[str, Any] = {
    "financial-accounts": FinancialAccount,
    "bank-accounts": BankAccount,
    "credit-accounts": CreditAccount,
    "transactions": FinancialTransaction,
    "bank-transactions": BankTransaction,
    "credit-card-transactions": CreditCardTransaction,
    "payroll-runs": PayrollRun,
    "payroll-entries": PayrollEntry,
    "employees": Employee,
    "counterparties": Counterparty,
    "categories": TransactionCategory,
}


@router.get("/canonical/{record_type}", response_model=Page)
def canonical_records(
    record_type: str,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("canonical_records.view"))],
    source_file_id: int | None = None,
    normalization_run_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    model = CANONICAL_MODELS.get(record_type)
    if model is None:
        raise HTTPException(status_code=404, detail="Canonical record type not found")
    conditions: list[Any] = [model.tenant_id == context.tenant.id]
    if source_file_id is not None and hasattr(model, "source_file_id"):
        conditions.append(model.source_file_id == source_file_id)
    if normalization_run_id is not None and hasattr(model, "normalization_run_id"):
        conditions.append(model.normalization_run_id == normalization_run_id)
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    items = session.scalars(
        select(model)
        .where(*conditions)
        .order_by(model.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[
            {column.name: getattr(item, column.name) for column in model.__table__.columns}
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/canonical/{entity_type}/{entity_id}/lineage", response_model=Page)
def canonical_lineage(
    entity_type: str,
    entity_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("canonical_lineage.view"))],
) -> Page:
    conditions = [
        CanonicalRecordLineage.tenant_id == context.tenant.id,
        CanonicalRecordLineage.canonical_entity_type == entity_type,
        CanonicalRecordLineage.canonical_entity_id == entity_id,
    ]
    items = session.scalars(
        select(CanonicalRecordLineage).where(*conditions).order_by(CanonicalRecordLineage.id)
    ).all()
    return Page(
        items=[
            {
                column.name: getattr(item, column.name)
                for column in CanonicalRecordLineage.__table__.columns
            }
            for item in items
        ],
        total=len(items),
        page=1,
        page_size=max(1, len(items)),
    )


@router.get("/source-files/{source_file_id}/canonical-records", response_model=Page)
def source_canonical_records(
    source_file_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("canonical_lineage.view"))],
) -> Page:
    owned = session.scalar(
        select(SourceFile.id).where(
            SourceFile.id == source_file_id, SourceFile.tenant_id == context.tenant.id
        )
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Source file not found")
    items = session.scalars(
        select(CanonicalRecordLineage)
        .where(
            CanonicalRecordLineage.tenant_id == context.tenant.id,
            CanonicalRecordLineage.source_file_id == source_file_id,
        )
        .order_by(CanonicalRecordLineage.id)
    ).all()
    return Page(
        items=[
            {
                column.name: getattr(item, column.name)
                for column in CanonicalRecordLineage.__table__.columns
            }
            for item in items
        ],
        total=len(items),
        page=1,
        page_size=max(1, len(items)),
    )


@router.get("/normalizations/{pipeline_run_id}/exceptions", response_model=Page)
def normalization_exceptions(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("normalization_exceptions.view"))
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    conditions = [
        NormalizationException.tenant_id == context.tenant.id,
        NormalizationException.pipeline_run_id == pipeline_run_id,
    ]
    total = (
        session.scalar(select(func.count()).select_from(NormalizationException).where(*conditions))
        or 0
    )
    items = session.scalars(
        select(NormalizationException)
        .where(*conditions)
        .order_by(NormalizationException.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[NormalizationExceptionResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/normalizations/{pipeline_run_id}/control-totals",
    response_model=list[NormalizationControlResponse],
)
def normalization_controls(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("normalization_control_totals.view"))
    ],
) -> list[NormalizationControlResponse]:
    items = session.scalars(
        select(NormalizationControlTotal)
        .where(
            NormalizationControlTotal.tenant_id == context.tenant.id,
            NormalizationControlTotal.pipeline_run_id == pipeline_run_id,
        )
        .order_by(NormalizationControlTotal.id)
    ).all()
    return [NormalizationControlResponse.model_validate(item) for item in items]


@router.get("/normalization-exceptions", response_model=Page)
def all_normalization_exceptions(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("normalization_exceptions.view"))
    ],
    exception_code: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page:
    conditions: list[Any] = [NormalizationException.tenant_id == context.tenant.id]
    for column, value in (
        (NormalizationException.exception_code, exception_code),
        (NormalizationException.severity, severity),
        (NormalizationException.status, status),
    ):
        if value:
            conditions.append(column == value)
    total = (
        session.scalar(select(func.count()).select_from(NormalizationException).where(*conditions))
        or 0
    )
    items = session.scalars(
        select(NormalizationException)
        .where(*conditions)
        .order_by(NormalizationException.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[NormalizationExceptionResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/normalization-exceptions/{exception_id}", response_model=NormalizationExceptionResponse
)
def normalization_exception(
    exception_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("normalization_exceptions.view"))
    ],
) -> NormalizationExceptionResponse:
    item = session.scalar(
        select(NormalizationException).where(
            NormalizationException.id == exception_id,
            NormalizationException.tenant_id == context.tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Normalization exception not found")
    return NormalizationExceptionResponse.model_validate(item)
