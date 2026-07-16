from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunPayrollReconciliationRequest(BaseModel):
    payroll_bank_account_id: int
    date_from: date
    date_to: date
    settlement_model: Literal[
        "net_pay_only",
        "net_pay_plus_taxes",
        "full_payroll_cash_requirement",
        "split_withdrawals",
        "configured_components",
    ] = "net_pay_only"
    force_rerun: bool = False


class PayrollReconciliationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    reconciliation_version: str
    status: str
    date_from: date
    date_to: date
    payroll_bank_account_id: int
    settlement_model: str
    included_payroll_run_count: int
    included_payroll_entry_count: int
    included_bank_transaction_count: int
    included_gl_record_count: int
    automatically_matched_count: int
    suggested_match_count: int
    partially_matched_count: int
    unmatched_payroll_count: int
    unmatched_bank_count: int
    unmatched_gl_count: int
    exception_count: int
    gross_pay_total: Decimal
    employee_tax_total: Decimal
    employee_deduction_total: Decimal
    employer_tax_total: Decimal
    employer_contribution_total: Decimal
    reimbursement_total: Decimal
    net_pay_total: Decimal
    bank_withdrawal_total: Decimal
    gl_payroll_expense_total: Decimal
    gl_payroll_liability_total: Decimal
    matched_amount_total: Decimal
    reconciliation_rate: Decimal
    input_fingerprint: str
    ruleset_fingerprint: str
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    no_op: bool = False


class PayrollCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    payroll_run_id: int | None
    bank_transaction_id: int | None
    gl_record_id: str | None
    candidate_type: str
    amount_difference: Decimal
    date_difference_days: int | None
    total_confidence: Decimal
    candidate_status: str
    reason_json: dict[str, Any]


class PayrollGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    payroll_run_id: int
    group_type: str
    status: str
    confidence: Decimal
    payroll_total: Decimal
    bank_total: Decimal
    gl_total: Decimal
    matched_amount: Decimal
    difference_amount: Decimal
    auto_accepted: bool
    notes: str | None
    metadata_json: dict[str, Any] | None


class PayrollExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exception_code: str
    exception_type: str
    severity: str
    payroll_run_id: int | None
    payroll_entry_id: int | None
    employee_id: int | None
    bank_transaction_id: int | None
    gl_record_id: str | None
    reconciliation_group_id: int | None
    message: str
    observed_value: str | None
    expected_value: str | None
    status: str


class PayrollControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    payroll_run_id: int | None
    control_name: str
    payroll_value: Decimal | None
    bank_value: Decimal | None
    gl_value: Decimal | None
    difference_value: Decimal | None
    tolerance: Decimal
    status: str


class PayrollReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    report_type: str
    relative_path: str
    checksum: str
    mime_type: str
    file_size_bytes: int


class PayrollReviewRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)


class PayrollDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reconciliation_group_id: int
    actor_user_id: int
    decision: str
    previous_status: str
    new_status: str
    reason: str
    notes: str | None
    decided_at: datetime


class PayrollRunDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    payroll_run_source_id: str
    pay_period_start: date | None
    pay_period_end: date | None
    pay_date: date
    gross_pay_total: Decimal | None
    employee_deductions_total: Decimal | None
    employer_contributions_total: Decimal | None
    reimbursement_total: Decimal | None
    net_pay_total: Decimal | None
    status: str
