from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerateDatasetRequest(BaseModel):
    random_seed: int | None = None
    generation_date: date | None = None
    force_rerun: bool = False


class GeneratedDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    pipeline_run_id: int
    input_fingerprint: str
    generator_version: str
    random_seed: int
    generation_date: date
    base_date_start: date | None
    base_date_end: date | None
    status: str
    file_count: int
    record_count: int
    source_bank_transaction_count: int
    source_credit_card_transaction_count: int
    source_payroll_run_count: int
    generated_customer_count: int
    generated_vendor_count: int
    generated_deal_count: int
    generated_invoice_count: int
    generated_payment_count: int
    generated_ap_bill_count: int
    generated_gl_entry_count: int
    metadata_json: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    no_op: bool = False


class GeneratedSourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generated_dataset_run_id: int
    source_file_id: int
    file_type: str
    filename: str
    relative_path: str
    sha256_checksum: str
    file_size_bytes: int
    record_count: int
    column_count: int
    metadata_json: dict[str, Any] | None


class GeneratedRecordLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generated_dataset_run_id: int
    generated_file_type: str
    generated_record_key: str
    relationship_type: str
    related_entity_type: str
    related_entity_id: str
    metadata_json: dict[str, Any] | None


class GenerationControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    control_name: str
    expected_value: Decimal
    actual_value: Decimal
    difference: Decimal
    status: str
    details_json: dict[str, Any] | None


class GenerationExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generated_dataset_run_id: int | None
    input_fingerprint: str
    exception_code: str
    severity: str
    message: str
    details_json: dict[str, Any] | None


class GeneratedPage(BaseModel):
    items: list[Any]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
