from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunInvoiceCollectionsRequest(BaseModel):
    bank_account_id: int
    date_from: date
    date_to: date
    aging_as_of_date: date
    force_rerun: bool = False


class InvoiceCollectionsRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pipeline_run_id: int
    reconciliation_version: str
    status: str
    date_from: date
    date_to: date
    aging_as_of_date: date
    bank_account_id: int
    included_customer_count: int
    included_deal_count: int
    included_invoice_count: int
    included_payment_count: int
    included_bank_deposit_count: int
    included_gl_record_count: int
    automatically_matched_count: int
    suggested_match_count: int
    partially_matched_count: int
    unmatched_invoice_count: int
    unmatched_payment_count: int
    unmatched_deposit_count: int
    unmatched_gl_count: int
    exception_count: int
    invoice_total: Decimal
    invoice_paid_total: Decimal
    invoice_balance_total: Decimal
    payment_total: Decimal
    bank_deposit_total: Decimal
    matched_collection_total: Decimal
    reconciliation_rate: Decimal
    input_fingerprint: str
    ruleset_fingerprint: str
    started_at: datetime
    completed_at: datetime | None
    metadata_json: dict[str, Any] | None
    no_op: bool = False


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: str | None
    invoice_id: str | None
    payment_id: str | None
    bank_transaction_id: int | None
    gl_record_id: str | None
    candidate_type: str
    total_confidence: Decimal
    candidate_status: str
    reason_json: dict[str, Any]


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_type: str
    status: str
    confidence: Decimal
    invoice_total: Decimal
    payment_total: Decimal
    deposit_total: Decimal
    gl_total: Decimal
    matched_amount: Decimal
    remaining_amount: Decimal
    difference_amount: Decimal
    auto_accepted: bool
    notes: str | None
    metadata_json: dict[str, Any] | None


class ExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exception_code: str
    severity: str
    invoice_id: str | None
    payment_id: str | None
    bank_transaction_id: int | None
    gl_record_id: str | None
    message: str
    status: str


class ControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    control_name: str
    invoice_value: Decimal | None
    payment_value: Decimal | None
    deposit_value: Decimal | None
    gl_value: Decimal | None
    difference_value: Decimal | None
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


class AgingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    as_of_date: date
    customer_id: str
    invoice_count: int
    current_amount: Decimal
    days_1_30_amount: Decimal
    days_31_60_amount: Decimal
    days_61_90_amount: Decimal
    over_90_days_amount: Decimal
    total_outstanding: Decimal


class PaymentResponse(BaseModel):
    payment_id: str
    payment_reference: str
    customer_id: str
    payment_date: date
    payment_amount: Decimal
    applied_amount: Decimal
    unapplied_amount: Decimal
    invoice_count: int
    bank_transaction_id: int | None
    deposit_status: str
    gl_status: str
    overall_status: str
    invoice_ids: list[str]


class ReviewRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
