from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SourceSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    source_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceSystemPage(BaseModel):
    items: list[SourceSystemResponse]
    total: int
    page: int
    page_size: int


class SourceFileResponse(BaseModel):
    id: int
    source_system_id: int
    source_system_code: str
    original_filename: str
    stored_filename: str
    relative_path: str
    file_extension: str
    mime_type: str
    file_size_bytes: int
    sha256_checksum: str
    status: str
    discovered_at: datetime
    registered_at: datetime
    created_at: datetime
    updated_at: datetime


class SourceFilePage(BaseModel):
    items: list[SourceFileResponse]
    total: int
    page: int
    page_size: int


class PipelineRunStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_name: str
    step_order: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    error_message: str | None


class PipelineRunResponse(BaseModel):
    id: int
    run_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    source_file_id: int | None
    records_extracted: int
    records_accepted: int
    records_rejected: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[PipelineRunStepResponse]


class PipelineRunPage(BaseModel):
    items: list[PipelineRunResponse]
    total: int
    page: int
    page_size: int


class UploadSuccessResponse(BaseModel):
    status: Literal["registered"]
    source_file_id: int
    original_filename: str
    stored_filename: str
    sha256_checksum: str
    file_size_bytes: int
    pipeline_run_id: int


class UploadDuplicateResponse(BaseModel):
    status: Literal["duplicate"]
    message: str
    existing_source_file_id: int
    sha256_checksum: str
    pipeline_run_id: int


class UploadErrorResponse(BaseModel):
    status: Literal["validation_error", "failed"]
    code: str
    message: str
    pipeline_run_id: int | None
