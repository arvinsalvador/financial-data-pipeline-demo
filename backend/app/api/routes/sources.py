from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.exceptions import DuplicateSourceFile, UploadServiceError
from app.models import PipelineRun, SourceFile, SourceSystem
from app.schemas.sources import (
    PipelineRunPage,
    PipelineRunResponse,
    PipelineRunStepResponse,
    SourceFilePage,
    SourceFileResponse,
    SourceSystemPage,
    SourceSystemResponse,
    UploadDuplicateResponse,
    UploadErrorResponse,
    UploadSuccessResponse,
)
from app.services.source_registration import SourceFileRegistrationService

router = APIRouter()


def _source_file_response(source_file: SourceFile) -> SourceFileResponse:
    return SourceFileResponse(
        id=source_file.id,
        source_system_id=source_file.source_system_id,
        source_system_code=source_file.source_system.code,
        original_filename=source_file.original_filename,
        stored_filename=source_file.stored_filename,
        relative_path=source_file.relative_path,
        file_extension=source_file.file_extension,
        mime_type=source_file.mime_type,
        file_size_bytes=source_file.file_size_bytes,
        sha256_checksum=source_file.sha256_checksum,
        status=source_file.status,
        discovered_at=source_file.discovered_at,
        registered_at=source_file.registered_at,
        created_at=source_file.created_at,
        updated_at=source_file.updated_at,
    )


def _pipeline_run_response(run: PipelineRun) -> PipelineRunResponse:
    return PipelineRunResponse(
        id=run.id,
        run_type=run.run_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        source_file_id=run.source_file_id,
        records_extracted=run.records_extracted,
        records_accepted=run.records_accepted,
        records_rejected=run.records_rejected,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[PipelineRunStepResponse.model_validate(step) for step in run.steps],
    )


@router.post("/source-files/upload")
async def upload_source_file(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    source_system_code: Annotated[str, Form(min_length=1, max_length=100)],
) -> JSONResponse:
    service = SourceFileRegistrationService(settings)
    try:
        result = await service.register(session, file, source_system_code)
    except DuplicateSourceFile as error:
        duplicate_body = UploadDuplicateResponse(
            status="duplicate",
            message=error.message,
            existing_source_file_id=error.existing_source_file_id,
            sha256_checksum=error.sha256_checksum,
            pipeline_run_id=error.pipeline_run_id,
        )
        return JSONResponse(status_code=200, content=duplicate_body.model_dump())
    except UploadServiceError as error:
        response_status = "validation_error" if error.status_code < 500 else "failed"
        error_body = UploadErrorResponse(
            status=response_status,
            code=error.code,
            message=error.message,
            pipeline_run_id=error.pipeline_run_id,
        )
        return JSONResponse(status_code=error.status_code, content=error_body.model_dump())

    source_file = result.source_file
    success_body = UploadSuccessResponse(
        status="registered",
        source_file_id=source_file.id,
        original_filename=source_file.original_filename,
        stored_filename=source_file.stored_filename,
        sha256_checksum=source_file.sha256_checksum,
        file_size_bytes=source_file.file_size_bytes,
        pipeline_run_id=result.pipeline_run_id,
    )
    return JSONResponse(status_code=201, content=success_body.model_dump())


@router.get("/source-systems", response_model=SourceSystemPage)
def list_source_systems(
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SourceSystemPage:
    total = session.scalar(select(func.count()).select_from(SourceSystem)) or 0
    items = session.scalars(
        select(SourceSystem)
        .order_by(SourceSystem.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SourceSystemPage(
        items=[SourceSystemResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/source-files", response_model=SourceFilePage)
def list_source_files(
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SourceFilePage:
    total = session.scalar(select(func.count()).select_from(SourceFile)) or 0
    items = session.scalars(
        select(SourceFile)
        .options(selectinload(SourceFile.source_system))
        .order_by(SourceFile.registered_at.desc(), SourceFile.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SourceFilePage(
        items=[_source_file_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/source-files/{source_file_id}", response_model=SourceFileResponse)
def get_source_file(
    source_file_id: int, session: Annotated[Session, Depends(get_db)]
) -> SourceFileResponse:
    source_file = session.scalar(
        select(SourceFile)
        .where(SourceFile.id == source_file_id)
        .options(selectinload(SourceFile.source_system))
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found")
    return _source_file_response(source_file)


@router.get("/pipeline-runs", response_model=PipelineRunPage)
def list_pipeline_runs(
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PipelineRunPage:
    total = session.scalar(select(func.count()).select_from(PipelineRun)) or 0
    items = session.scalars(
        select(PipelineRun)
        .options(selectinload(PipelineRun.steps))
        .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PipelineRunPage(
        items=[_pipeline_run_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/pipeline-runs/{pipeline_run_id}", response_model=PipelineRunResponse)
def get_pipeline_run(
    pipeline_run_id: int, session: Annotated[Session, Depends(get_db)]
) -> PipelineRunResponse:
    run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.id == pipeline_run_id)
        .options(selectinload(PipelineRun.steps))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return _pipeline_run_response(run)
