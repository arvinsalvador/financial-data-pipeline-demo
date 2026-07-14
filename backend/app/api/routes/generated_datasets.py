import csv
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    GeneratedDatasetRun,
    GeneratedRecordLink,
    GeneratedSourceFile,
    GenerationControlTotal,
    GenerationException,
)
from app.schemas.generation import (
    GenerateDatasetRequest,
    GeneratedDatasetResponse,
    GeneratedPage,
    GeneratedRecordLinkResponse,
    GeneratedSourceFileResponse,
    GenerationControlResponse,
    GenerationExceptionResponse,
)
from app.services.generated_sources import GeneratedSourceService, GenerationError
from app.services.governance import AuditService

router = APIRouter()


def _run_response(run: GeneratedDatasetRun, no_op: bool = False) -> GeneratedDatasetResponse:
    response = GeneratedDatasetResponse.model_validate(run)
    return response.model_copy(update={"no_op": no_op})


def _owned_run(session: Session, tenant_id: int, run_id: int) -> GeneratedDatasetRun:
    run = session.scalar(
        select(GeneratedDatasetRun).where(
            GeneratedDatasetRun.id == run_id,
            GeneratedDatasetRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Generated dataset not found")
    return run


def _page(
    session: Session,
    model: Any,
    conditions: list[Any],
    page: int,
    page_size: int,
    schema: Any,
) -> GeneratedPage:
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    items = session.scalars(
        select(model)
        .where(*conditions)
        .order_by(model.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GeneratedPage(
        items=[schema.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/generated-datasets", response_model=GeneratedDatasetResponse)
def generate_dataset(
    body: GenerateDatasetRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("generated_datasets.execute"))],
) -> GeneratedDatasetResponse:
    AuditService().record(
        session,
        context,
        event_type="generation.requested",
        entity_type="generated_dataset",
        entity_id=None,
        action="generate",
        description="Deterministic demo source generation requested",
        metadata={
            "random_seed": body.random_seed or settings.GENERATION_RANDOM_SEED,
            "generation_date": body.generation_date.isoformat() if body.generation_date else None,
            "force_rerun": body.force_rerun,
        },
    )
    session.commit()
    try:
        result = GeneratedSourceService(settings).generate(
            session,
            context.tenant,
            body.random_seed,
            body.generation_date,
            body.force_rerun,
        )
    except GenerationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    AuditService().record(
        session,
        context,
        event_type="generation.no_op" if result.no_op else "generation.completed",
        entity_type="generated_dataset",
        entity_id=result.run.id,
        action="generate",
        description=(
            "Existing deterministic dataset returned"
            if result.no_op
            else "Deterministic demo source generation completed"
        ),
        pipeline_run_id=result.run.pipeline_run_id,
        metadata={"input_fingerprint": result.run.input_fingerprint},
    )
    session.commit()
    return _run_response(result.run, result.no_op)


@router.get("/generated-datasets", response_model=GeneratedPage)
def generated_datasets(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generated_datasets.view"))],
    status: str | None = None,
    random_seed: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> GeneratedPage:
    conditions: list[Any] = [GeneratedDatasetRun.tenant_id == context.tenant.id]
    if status:
        conditions.append(GeneratedDatasetRun.status == status)
    if random_seed is not None:
        conditions.append(GeneratedDatasetRun.random_seed == random_seed)
    total = (
        session.scalar(select(func.count()).select_from(GeneratedDatasetRun).where(*conditions))
        or 0
    )
    items = session.scalars(
        select(GeneratedDatasetRun)
        .where(*conditions)
        .order_by(GeneratedDatasetRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GeneratedPage(
        items=[_run_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/generated-datasets/{run_id}", response_model=GeneratedDatasetResponse)
def generated_dataset(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generated_datasets.view"))],
) -> GeneratedDatasetResponse:
    return _run_response(_owned_run(session, context.tenant.id, run_id))


@router.get("/generated-datasets/{run_id}/files", response_model=GeneratedPage)
def generated_files(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generated_files.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned_run(session, context.tenant.id, run_id)
    return _page(
        session,
        GeneratedSourceFile,
        [
            GeneratedSourceFile.tenant_id == context.tenant.id,
            GeneratedSourceFile.generated_dataset_run_id == run_id,
        ],
        page,
        page_size,
        GeneratedSourceFileResponse,
    )


@router.get("/generated-source-files/{file_id}", response_model=GeneratedSourceFileResponse)
def generated_file(
    file_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generated_files.view"))],
) -> GeneratedSourceFileResponse:
    item = session.scalar(
        select(GeneratedSourceFile).where(
            GeneratedSourceFile.id == file_id, GeneratedSourceFile.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Generated source file not found")
    return GeneratedSourceFileResponse.model_validate(item)


@router.get("/generated-source-files/{file_id}/records", response_model=GeneratedPage)
def generated_file_records(
    file_id: int,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("generated_files.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    item = session.scalar(
        select(GeneratedSourceFile).where(
            GeneratedSourceFile.id == file_id,
            GeneratedSourceFile.tenant_id == context.tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Generated source file not found")
    root = settings.GENERATED_DATA_DIRECTORY.resolve()
    try:
        relative = Path(item.relative_path).relative_to("generated")
        path = (root / relative).resolve()
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Generated source path is invalid") from error
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Generated source bytes not found")
    with path.open(encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    start = (page - 1) * page_size
    return GeneratedPage(
        items=records[start : start + page_size],
        total=len(records),
        page=page,
        page_size=page_size,
    )


@router.get("/generated-datasets/{run_id}/links", response_model=GeneratedPage)
def generated_links(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generated_links.view"))],
    relationship_type: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned_run(session, context.tenant.id, run_id)
    conditions: list[Any] = [
        GeneratedRecordLink.tenant_id == context.tenant.id,
        GeneratedRecordLink.generated_dataset_run_id == run_id,
    ]
    if relationship_type:
        conditions.append(GeneratedRecordLink.relationship_type == relationship_type)
    return _page(
        session, GeneratedRecordLink, conditions, page, page_size, GeneratedRecordLinkResponse
    )


@router.get("/generated-datasets/{run_id}/control-totals", response_model=GeneratedPage)
def generation_controls(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generation_controls.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned_run(session, context.tenant.id, run_id)
    return _page(
        session,
        GenerationControlTotal,
        [
            GenerationControlTotal.tenant_id == context.tenant.id,
            GenerationControlTotal.generated_dataset_run_id == run_id,
        ],
        page,
        page_size,
        GenerationControlResponse,
    )


@router.get("/generated-datasets/{run_id}/exceptions", response_model=GeneratedPage)
def generation_exceptions(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("generation_exceptions.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned_run(session, context.tenant.id, run_id)
    return _page(
        session,
        GenerationException,
        [
            GenerationException.tenant_id == context.tenant.id,
            GenerationException.generated_dataset_run_id == run_id,
        ],
        page,
        page_size,
        GenerationExceptionResponse,
    )
