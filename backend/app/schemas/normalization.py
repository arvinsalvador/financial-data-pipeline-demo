from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.ingestion import ArtifactResponse, StepResponse


class NormalizeRequest(BaseModel):
    mapping_code: str | None = None
    force_rerun: bool = False


class NormalizationSummary(BaseModel):
    id: int
    tenant_id: int
    source_file_id: int | None
    ingestion_run_id: int | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    staging_count: int
    canonical_count: int
    exception_count: int
    mapping_code: str | None
    mapping_version: str | None
    normalization_version: str | None
    no_op: bool = False
    error_message: str | None
    steps: list[StepResponse] = []
    artifacts: list[ArtifactResponse] = []


class NormalizationExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    source_file_id: int
    staging_entity_type: str
    staging_entity_id: int
    exception_code: str
    exception_type: str
    severity: str
    field_name: str | None
    observed_value: str | None
    expected_value: str | None
    message: str
    status: str
    exception_fingerprint: str
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class NormalizationControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    source_file_id: int
    control_name: str
    staging_value: Decimal | None
    canonical_value: Decimal | None
    difference_value: Decimal | None
    tolerance: Decimal | None
    status: str
    metadata_json: dict[str, Any] | None
