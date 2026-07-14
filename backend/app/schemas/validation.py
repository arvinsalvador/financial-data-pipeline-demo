from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class RunValidationRequest(BaseModel):
    target_type: Literal["tenant", "source_file", "pipeline", "generated_dataset", "messy_dataset"]
    target_id: int | None = None
    rule_set_code: str = "financial_data_quality_v1"
    force_rerun: bool = False


class ValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    rule_set_id: int
    validation_version: str
    target_type: str
    target_id: int | None
    input_fingerprint: str
    status: str
    total_rules: int
    passed_rules: int
    failed_rules: int
    skipped_rules: int
    disabled_rules: int
    total_issues: int
    information_count: int
    warning_count: int
    error_count: int
    critical_count: int
    records_evaluated: int
    duration_ms: int
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    no_op: bool = False


class ValidationIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_run_id: int
    validation_rule_id: int
    validation_version: str
    issue_code: str
    issue_type: str
    severity: str
    status: str
    entity_type: str
    entity_key: str | None
    source_file_id: int | None
    filename: str | None
    row_number: int | None
    column_name: str | None
    message: str
    observed_value: str | None
    expected_value: str | None
    issue_fingerprint: str
    metadata_json: dict[str, Any] | None
    detected_at: datetime


class ValidationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str
    rule_group: str
    target_entity: str
    severity: str
    version: str
    execution_order: int
    is_enabled: bool
    configuration_json: dict[str, Any] | None


class ValidationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_rule_id: int
    validation_version: str
    status: str
    records_evaluated: int
    issue_count: int
    duration_ms: int
    details_json: dict[str, Any] | None


class ValidationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_run_id: int
    validation_version: str
    overall_status: str
    issue_count: int
    counts_by_severity_json: dict[str, int]
    counts_by_rule_json: dict[str, int]
    counts_by_file_json: dict[str, int]
    counts_by_entity_json: dict[str, int]
    control_totals_json: dict[str, Any]
    summary_fingerprint: str


class ValidationStatisticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_run_id: int
    dimension_type: str
    dimension_key: str
    issue_count: int
    records_evaluated: int
    details_json: dict[str, Any] | None


class ValidationReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_run_id: int
    validation_version: str
    report_type: str
    filename: str
    relative_path: str
    sha256_checksum: str
    file_size_bytes: int
    metadata_json: dict[str, Any] | None
