from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerateMessyDatasetRequest(BaseModel):
    clean_generated_dataset_run_id: int
    scenario_code: str = "standard_messy_v1"
    random_seed: int | None = None
    force_rerun: bool = False


class MessyDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    pipeline_run_id: int
    clean_generated_dataset_run_id: int
    defect_scenario_id: int
    messy_generator_version: str
    random_seed: int
    input_fingerprint: str
    defect_plan_fingerprint: str
    output_fingerprint: str | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    clean_file_count: int
    messy_file_count: int
    requested_defect_count: int
    applied_defect_count: int
    skipped_defect_count: int
    failed_defect_count: int
    expected_exception_count: int
    metadata_json: dict[str, Any] | None
    no_op: bool = False
    pipeline_steps: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class MessySourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    messy_dataset_run_id: int
    clean_generated_source_file_id: int
    source_file_id: int
    file_type: str
    filename: str
    relative_path: str
    sha256_checksum: str
    file_size_bytes: int
    row_count: int
    column_count: int
    metadata_json: dict[str, Any] | None


class MutationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    messy_dataset_run_id: int
    defect_scenario_rule_id: int
    defect_type: str
    target_file_type: str
    target_filename: str
    source_row_number: int | None
    source_record_key: str | None
    target_column: str | None
    original_value: str | None
    mutated_value: str | None
    mutation_fingerprint: str
    mutation_status: str
    metadata_json: dict[str, Any] | None


class ExpectedExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    messy_dataset_run_id: int
    expected_exception_code: str
    expected_issue_type: str
    expected_severity: str
    expected_file_type: str
    expected_filename: str
    expected_source_row_number: int | None
    expected_source_record_key: str | None
    expected_column_name: str | None
    related_mutation_id: int | None
    expected_message_pattern: str
    expected_count_group: str | None
    expectation_fingerprint: str
    status: str
    metadata_json: dict[str, Any] | None


class MessyControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    control_name: str
    clean_value: Decimal | None
    messy_value: Decimal | None
    difference_value: Decimal | None
    expected_difference: Decimal | None
    tolerance: Decimal
    status: str
    metadata_json: dict[str, Any] | None


class ScenarioRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_code: str
    defect_type: str
    target_file_type: str
    target_column: str | None
    requested_count: int | None
    requested_percentage: Decimal | None
    severity: str
    is_enabled: bool
    rule_order: int
    configuration_json: dict[str, Any] | None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None
    version: str
    is_system_scenario: bool
    is_active: bool
    configuration_json: dict[str, Any] | None
    enabled_rule_count: int = 0
    expected_approximate_defect_count: int = 0
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    rules: list[ScenarioRuleResponse] = Field(default_factory=list)
