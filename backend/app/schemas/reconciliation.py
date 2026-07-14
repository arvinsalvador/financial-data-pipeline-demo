from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunReconciliationRequest(BaseModel):
    bank_account_id: int
    date_from: date
    date_to: date
    generated_dataset_run_id: int | None = None
    force_rerun: bool = False


class ReconciliationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    reconciliation_version: str
    status: str
    date_from: date
    date_to: date
    bank_account_id: int
    generated_source_file_id: int
    validation_run_id: int | None
    included_bank_transaction_count: int
    included_ledger_line_count: int
    automatically_matched_count: int
    suggested_match_count: int
    partially_matched_count: int
    unmatched_bank_count: int
    unmatched_ledger_count: int
    duplicate_count: int
    reversal_count: int
    exception_count: int
    total_bank_amount: Decimal
    total_ledger_amount: Decimal
    total_matched_amount: Decimal
    total_unmatched_bank_amount: Decimal
    total_unmatched_ledger_amount: Decimal
    reconciliation_rate: Decimal
    input_fingerprint: str
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    no_op: bool = False


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reconciliation_rule_id: int
    bank_transaction_id: int | None
    ledger_record_id: str | None
    candidate_type: str
    amount_difference: Decimal
    date_difference_days: int | None
    total_confidence: Decimal
    candidate_status: str
    reason_json: dict[str, Any]


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reconciliation_rule_id: int
    group_type: str
    status: str
    confidence: Decimal
    matched_amount: Decimal
    bank_total: Decimal
    ledger_total: Decimal
    difference_amount: Decimal
    auto_accepted: bool
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    notes: str | None
    metadata_json: dict[str, Any] | None


class DecisionRequest(BaseModel):
    decision: Literal["accept", "reject", "resolve", "reopen"]
    reason: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)


class ReviewRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    match_group_id: int
    actor_user_id: int
    decision: str
    previous_status: str
    new_status: str
    reason: str
    notes: str | None
    decided_at: datetime


class ExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exception_code: str
    exception_type: str
    severity: str
    bank_transaction_id: int | None
    ledger_record_id: str | None
    match_group_id: int | None
    message: str
    status: str
    metadata_json: dict[str, Any] | None


class ControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    control_name: str
    source_value: Decimal
    matched_value: Decimal
    unmatched_value: Decimal
    difference_value: Decimal
    tolerance: Decimal
    status: str


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    report_type: str
    relative_path: str
    checksum: str
    mime_type: str
    file_size_bytes: int


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_name: str
    source_account_code: str
    institution_name: str | None
    status: str
