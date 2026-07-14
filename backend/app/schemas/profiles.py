from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ColumnProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_file_profile_id: int
    column_name: str
    column_position: int
    inferred_data_type: str
    original_data_type: str
    row_count: int
    null_count: int
    non_null_count: int
    null_percentage: Decimal
    unique_count: int
    duplicate_value_count: int
    minimum_value: str | None
    maximum_value: str | None
    mean_value: Decimal | None
    median_value: Decimal | None
    standard_deviation: Decimal | None
    minimum_length: int | None
    maximum_length: int | None
    average_length: Decimal | None
    earliest_date: date | None
    latest_date: date | None
    sample_values_json: list[str] | None
    detected_formats_json: list[str] | None
    created_at: datetime
    updated_at: datetime


class IssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    source_file_id: int
    source_file_profile_id: int
    pipeline_run_id: int
    column_name: str | None
    row_number: int | None
    issue_code: str
    issue_type: str
    severity: str
    message: str
    observed_value: str | None
    expected_value: str | None
    status: str
    issue_fingerprint: str
    metadata_json: dict[str, Any] | None
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    source_file_id: int
    pipeline_run_id: int
    profile_version: str
    status: str
    encoding: str | None
    delimiter: str | None
    row_count: int
    column_count: int
    empty_row_count: int
    duplicate_row_count: int
    file_size_bytes: int
    date_range_start: date | None
    date_range_end: date | None
    total_null_count: int
    total_non_null_count: int
    total_numeric_columns: int
    total_date_columns: int
    total_text_columns: int
    total_boolean_columns: int
    monetary_total: Decimal | None
    debit_total: Decimal | None
    credit_total: Decimal | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    calculated_closing_balance: Decimal | None
    running_balance_valid: bool | None
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
    profile_metadata_json: dict[str, Any] | None
    issue_totals: dict[str, int] = {}


class ProfilePage(BaseModel):
    items: list[ProfileResponse]
    total: int
    page: int
    page_size: int


class ColumnProfilePage(BaseModel):
    items: list[ColumnProfileResponse]
    total: int
    page: int
    page_size: int


class IssuePage(BaseModel):
    items: list[IssueResponse]
    total: int
    page: int
    page_size: int
