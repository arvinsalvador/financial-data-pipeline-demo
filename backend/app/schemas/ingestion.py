from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class IngestRequest(BaseModel):
    mapping_code: str | None = None
    force_rerun: bool = False


class StepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    step_name: str
    step_order: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    error_message: str | None


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    artifact_type: str
    name: str
    relative_path: str
    checksum: str | None
    mime_type: str | None
    file_size_bytes: int | None


class IngestionSummary(BaseModel):
    id: int
    tenant_id: int
    source_file_id: int | None
    source_filename: str | None = None
    source_system_code: str | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None
    records_extracted: int
    records_accepted: int
    records_rejected: int
    connector: str | None
    mapping_code: str | None
    mapping_version: str | None
    ingestion_version: str | None
    no_op: bool = False
    error_message: str | None
    steps: list[StepResponse] = []
    artifacts: list[ArtifactResponse] = []


class RawRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    source_system_id: int
    source_file_id: int
    pipeline_run_id: int
    source_row_number: int
    source_record_id: str | None
    raw_data_json: dict[str, str | None]
    raw_row_hash: str
    ingestion_version: str
    row_status: str
    created_at: datetime


class RejectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_file_id: int
    pipeline_run_id: int
    raw_source_row_id: int
    source_row_number: int
    rejection_code: str
    rejection_category: str
    severity: str
    field_name: str | None
    observed_value: str | None
    message: str
    rejection_fingerprint: str
    metadata_json: dict[str, Any] | None
    created_at: datetime


class ControlTotalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_file_id: int
    pipeline_run_id: int
    control_name: str
    source_value: Decimal | None
    loaded_value: Decimal | None
    difference_value: Decimal | None
    tolerance: Decimal | None
    status: str
    metadata_json: dict[str, Any] | None


class MappingColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_column_name: str
    canonical_field_name: str
    target_data_type: str
    is_required: bool
    parser_name: str | None
    transformation_config_json: dict[str, Any] | None
    column_order: int


class MappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    mapping_code: str
    mapping_name: str
    mapping_version: str
    source_file_pattern: str
    target_record_type: str
    is_active: bool
    columns: list[MappingColumnResponse]


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
