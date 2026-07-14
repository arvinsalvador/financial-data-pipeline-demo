from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from app.services.messy.types import CsvDocument, CsvRow, MutationResult, PlannedMutation


def _find(document: CsvDocument, plan: PlannedMutation) -> CsvRow | None:
    return next(
        (row for row in document.rows if row.clean_row_number == plan.clean_row_number), None
    )


class SchemaMutationService:
    TYPES: ClassVar[set[str]] = {
        "duplicate_column_name",
        "blank_column_name",
        "unexpected_extra_column",
        "missing_required_column",
        "reordered_columns",
        "inconsistent_header_spacing",
        "malformed_row_too_many_fields",
        "malformed_row_too_few_fields",
        "unsupported_encoding_variant",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        original = ",".join(document.headers)
        defect = plan.defect_type
        if defect == "duplicate_column_name" and document.headers:
            document.headers.append(document.headers[-1])
        elif defect == "blank_column_name":
            document.headers.append("")
        elif defect == "unexpected_extra_column":
            document.headers.append("unexpected_extra")
            for row in document.rows:
                row.values.append("unexpected")
        elif defect == "missing_required_column" and plan.column in document.headers:
            index = document.headers.index(plan.column or "")
            document.headers.pop(index)
            for row in document.rows:
                if index < len(row.values):
                    row.values.pop(index)
        elif defect == "reordered_columns":
            document.headers.reverse()
            for row in document.rows:
                row.values.reverse()
        elif defect == "inconsistent_header_spacing" and document.headers:
            document.headers[0] = f" {document.headers[0]} "
        elif defect in {"malformed_row_too_many_fields", "malformed_row_too_few_fields"}:
            target_row = _find(document, plan)
            if target_row is None:
                return [MutationResult(plan, None, None, "failed", {"reason": "row_missing"})]
            if defect.endswith("many_fields"):
                target_row.values.append("EXTRA_FIELD")
            elif target_row.values:
                target_row.values.pop()
        elif defect == "unsupported_encoding_variant":
            return [
                MutationResult(
                    plan, original, original, "skipped", {"reason": "unsafe_encoding_disabled"}
                )
            ]
        else:
            return [
                MutationResult(
                    plan, original, None, "failed", {"reason": "inapplicable_schema_rule"}
                )
            ]
        return [MutationResult(plan, original, ",".join(document.headers), "applied")]


class RowMutationService:
    DUPLICATES: ClassVar[set[str]] = {
        "exact_duplicate_row",
        "duplicate_invoice",
        "duplicate_ap_bill",
        "duplicate_payment",
        "duplicate_vendor",
        "duplicated_assumption",
        "duplicated_bank_transaction",
        "duplicate_gl_entry",
        "duplicate_employee_payroll_entry",
    }
    DELETIONS: ClassVar[set[str]] = {
        "deleted_expected_record",
        "missing_payment",
        "missing_invoice",
        "missing_gl_entry",
    }
    TYPES: ClassVar[set[str]] = (
        DUPLICATES
        | DELETIONS
        | {
            "near_duplicate_row",
            "blank_row",
            "inserted_unexpected_record",
            "late_arriving_record",
            "duplicate_transaction_identifier",
            "modified_transaction_identifier",
            "missing_transaction_identifier",
        }
    )

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        row = _find(document, plan)
        if row is None:
            return [MutationResult(plan, None, None, "failed", {"reason": "row_missing"})]
        if plan.defect_type in self.DUPLICATES:
            document.rows.append(CsvRow(deepcopy(row.values), None))
            return [
                MutationResult(
                    plan, plan.record_key, plan.record_key, "applied", {"operation": "duplicate"}
                )
            ]
        if plan.defect_type in self.DELETIONS:
            document.rows.remove(row)
            return [MutationResult(plan, plan.record_key, None, "applied", {"operation": "delete"})]
        if plan.defect_type == "near_duplicate_row":
            duplicate = CsvRow(deepcopy(row.values), None)
            near_column = plan.column or document.headers[0]
            document.set_value(
                duplicate,
                near_column,
                f"{document.value(row, near_column) or ''} near duplicate",
            )
            document.rows.append(duplicate)
            return [
                MutationResult(
                    plan,
                    plan.record_key,
                    document.record_key(duplicate),
                    "applied",
                    {"operation": "near_duplicate"},
                )
            ]
        if plan.defect_type == "blank_row":
            document.rows.append(CsvRow([""] * len(document.headers), None))
            return [MutationResult(plan, None, "blank row", "applied")]
        if plan.defect_type == "inserted_unexpected_record":
            inserted = CsvRow(deepcopy(row.values), None)
            key = document.record_key(inserted)
            primary = next(
                (name for name in document.headers if name.endswith("_id")), document.headers[0]
            )
            document.set_value(inserted, primary, f"UNEXPECTED-{key}")
            document.rows.append(inserted)
            return [MutationResult(plan, key, document.record_key(inserted), "applied")]
        column = plan.column
        if column is None:
            return [MutationResult(plan, None, None, "failed", {"reason": "column_required"})]
        original = document.value(row, column)
        if plan.defect_type == "missing_transaction_identifier":
            mutated = ""
        elif plan.defect_type == "duplicate_transaction_identifier":
            mutated = document.value(document.rows[0], column) or "DUPLICATE-ID"
        elif plan.defect_type == "modified_transaction_identifier":
            mutated = f"MOD-{original}"
        elif plan.defect_type == "late_arriving_record":
            mutated = "2099-12-31"
        else:
            return [
                MutationResult(plan, original, None, "failed", {"reason": "unsupported_row_rule"})
            ]
        document.set_value(row, column, mutated)
        return [MutationResult(plan, original, mutated, "applied")]


class DateMutationService:
    TYPES: ClassVar[set[str]] = {
        "invalid_date",
        "ambiguous_date",
        "inconsistent_date_format",
        "future_date",
        "out_of_period_date",
        "missing_date",
        "invalid_due_date",
        "payment_date_before_invoice_date",
        "missing_effective_date",
        "reversed_effective_date_range",
        "stale_assumption",
        "pay_period_mismatch",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        row = _find(document, plan)
        if row is None or plan.column is None:
            return [MutationResult(plan, None, None, "failed", {"reason": "target_missing"})]
        original = document.value(row, plan.column)
        config = plan.configuration
        if plan.defect_type in {"invalid_date", "invalid_due_date"}:
            mutated = str(config.get("value", "not-a-date"))
        elif plan.defect_type == "ambiguous_date":
            mutated = "01/02/03"
        elif plan.defect_type == "inconsistent_date_format":
            try:
                mutated = date.fromisoformat(original or "").strftime(
                    str(config.get("format", "%m/%d/%Y"))
                )
            except ValueError:
                mutated = "01/02/2026"
        elif plan.defect_type == "future_date":
            mutated = str(config.get("value", "2099-01-01"))
        elif plan.defect_type == "out_of_period_date":
            mutated = "1999-12-31"
        elif plan.defect_type in {"missing_date", "missing_effective_date"}:
            mutated = ""
        elif plan.defect_type == "payment_date_before_invoice_date":
            mutated = "1999-01-01"
        elif plan.defect_type in {"stale_assumption", "pay_period_mismatch"}:
            mutated = str(config.get("value", "2020-12-31"))
        elif plan.defect_type == "reversed_effective_date_range":
            other = (
                "effective_start_date"
                if plan.column == "effective_end_date"
                else "effective_end_date"
            )
            mutated = document.value(row, other) or "2020-01-01"
        else:
            return [MutationResult(plan, original, None, "failed")]
        document.set_value(row, plan.column, mutated)
        return [MutationResult(plan, original, mutated, "applied")]


class MonetaryMutationService:
    TYPES: ClassVar[set[str]] = {
        "currency_symbol_added",
        "thousands_separator_added",
        "parentheses_negative",
        "invalid_monetary_text",
        "decimal_shift",
        "sign_flip",
        "amount_changed",
        "debit_credit_swapped",
        "currency_code_changed",
        "missing_amount",
        "underpayment",
        "overpayment",
        "invoice_total_line_mismatch",
        "ap_bill_total_mismatch",
        "overpaid_ap_bill",
        "payroll_gross_mismatch",
        "payroll_net_mismatch",
        "employer_contribution_mismatch",
        "payroll_bank_withdrawal_mismatch",
        "payroll_gl_mismatch",
        "payroll_gl_total_mismatch",
        "invoice_gl_total_mismatch",
        "ap_gl_total_mismatch",
        "unbalanced_journal_entry",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        row = _find(document, plan)
        if row is None or plan.column is None:
            return [MutationResult(plan, None, None, "failed", {"reason": "target_missing"})]
        original = document.value(row, plan.column) or ""
        config = plan.configuration
        try:
            value = Decimal(original.replace(",", "").replace("$", "") or "0")
        except InvalidOperation:
            value = Decimal(0)
        defect = plan.defect_type
        if defect == "currency_symbol_added":
            mutated = f"${original}"
        elif defect == "thousands_separator_added":
            mutated = f"{value:,.2f}"
        elif defect == "parentheses_negative":
            mutated = f"({abs(value):.2f})"
        elif defect == "invalid_monetary_text":
            mutated = str(config.get("value", "NOT_A_NUMBER"))
        elif defect == "decimal_shift":
            mutated = f"{value * Decimal(100):.2f}"
        elif defect == "sign_flip":
            mutated = f"{-value:.2f}"
        elif defect in {"underpayment"}:
            mutated = f"{value * Decimal(str(config.get('factor', '0.75'))):.2f}"
        elif defect in {"overpayment", "overpaid_ap_bill"}:
            mutated = f"{value * Decimal(str(config.get('factor', '1.25'))):.2f}"
        elif defect in {"currency_code_changed"}:
            mutated = "ZZZ"
        elif defect == "missing_amount":
            mutated = ""
        else:
            mutated = f"{value + Decimal(str(config.get('delta', '1.00'))):.2f}"
        document.set_value(row, plan.column, mutated)
        return [MutationResult(plan, original, mutated, "applied")]


class CustomerMutationService:
    TYPES: ClassVar[set[str]] = {
        "misspelled_customer_name",
        "duplicate_customer",
        "missing_customer_id",
        "deal_invoice_amount_mismatch",
        "closed_lost_deal_with_invoice",
        "closed_won_deal_without_invoice",
        "invalid_pipeline_stage",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        return CellMutationService().apply(document, plan)


class VendorMutationService:
    TYPES: ClassVar[set[str]] = {
        "misspelled_vendor_name",
        "duplicate_vendor",
        "missing_vendor_id",
        "missing_ap_payment",
        "credit_card_expense_double_count",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        return CellMutationService().apply(document, plan)


class GeneralLedgerMutationService:
    TYPES: ClassVar[set[str]] = {
        "invalid_account_code",
        "cash_gl_bank_mismatch",
        "debit_credit_swapped_gl",
        "reversed_transaction",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        if plan.defect_type == "reversed_transaction":
            row = _find(document, plan)
            if row is None:
                return [MutationResult(plan, None, None, "failed")]
            debit, credit = document.value(row, "debit") or "", document.value(row, "credit") or ""
            document.set_value(row, "debit", credit)
            document.set_value(row, "credit", debit)
            return [MutationResult(plan, f"{debit}|{credit}", f"{credit}|{debit}", "applied")]
        return CellMutationService().apply(document, plan)


class ForecastAssumptionMutationService:
    TYPES: ClassVar[set[str]] = {
        "invalid_frequency",
        "invalid_scenario",
        "unsupported_currency",
        "negative_minimum_cash_threshold",
    }

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        return CellMutationService().apply(document, plan)


class RelationshipMutationService:
    TYPES: ClassVar[set[str]] = {"split_payment", "combined_deposit"}

    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        row = _find(document, plan)
        if row is None:
            return [MutationResult(plan, None, None, "failed")]
        if plan.defect_type == "split_payment":
            amount = Decimal(document.value(row, "payment_amount") or "0")
            half = (amount / 2).quantize(Decimal("0.01"))
            original = f"{amount:.2f}"
            document.set_value(row, "payment_amount", f"{half:.2f}")
            duplicate = CsvRow(deepcopy(row.values), None)
            payment_id = document.value(row, "payment_id") or "PAY"
            document.set_value(duplicate, "payment_id", f"{payment_id}-SPLIT")
            document.set_value(duplicate, "payment_reference", f"{payment_id}-SPLIT")
            document.set_value(duplicate, "payment_amount", f"{amount - half:.2f}")
            document.rows.append(duplicate)
            return [
                MutationResult(
                    plan,
                    original,
                    f"{half:.2f}",
                    "applied",
                    {"relationship_defect_id": plan.rule_code, "part": 1},
                ),
                MutationResult(
                    plan,
                    None,
                    f"{amount - half:.2f}",
                    "applied",
                    {
                        "relationship_defect_id": plan.rule_code,
                        "part": 2,
                        "new_record_key": f"{payment_id}-SPLIT",
                    },
                ),
            ]
        rows = [candidate for candidate in document.rows if candidate is not row]
        if not rows:
            return [
                MutationResult(plan, None, None, "skipped", {"reason": "second_payment_missing"})
            ]
        other = rows[0]
        combined_original = document.value(row, "canonical_bank_transaction_id")
        mutated = document.value(other, "canonical_bank_transaction_id") or ""
        document.set_value(row, "canonical_bank_transaction_id", mutated)
        return [
            MutationResult(
                plan,
                combined_original,
                mutated,
                "applied",
                {
                    "relationship_defect_id": plan.rule_code,
                    "other_record_key": document.record_key(other),
                },
            )
        ]


class CellMutationService:
    def apply(self, document: CsvDocument, plan: PlannedMutation) -> list[MutationResult]:
        row = _find(document, plan)
        if row is None or plan.column is None:
            return [MutationResult(plan, None, None, "failed", {"reason": "target_missing"})]
        original = document.value(row, plan.column) or ""
        if plan.defect_type in {"misspelled_customer_name", "misspelled_vendor_name"}:
            mutated = original[:-1] + "x" if original else "Typo"
        elif plan.defect_type in {
            "missing_customer_id",
            "missing_vendor_id",
            "employee_identifier_missing",
            "missing_ap_payment",
        }:
            mutated = ""
        elif plan.defect_type == "invalid_account_code":
            mutated = str(plan.configuration.get("value", "INVALID-999"))
        elif plan.defect_type == "invalid_pipeline_stage":
            mutated = "impossible_stage"
        elif plan.defect_type == "invalid_frequency":
            mutated = "sometimes"
        elif plan.defect_type == "invalid_scenario":
            mutated = str(plan.configuration.get("value", "impossible"))
        elif plan.defect_type == "unsupported_currency":
            mutated = "ZZZ"
        else:
            mutated = plan.proposed_value or f"MUTATED-{original}"
        document.set_value(row, plan.column, mutated)
        return [MutationResult(plan, original, mutated, "applied")]


class MutationDispatcher:
    def __init__(self) -> None:
        self.services = (
            SchemaMutationService(),
            RowMutationService(),
            DateMutationService(),
            MonetaryMutationService(),
            CustomerMutationService(),
            VendorMutationService(),
            GeneralLedgerMutationService(),
            ForecastAssumptionMutationService(),
            RelationshipMutationService(),
        )

    def apply(
        self, documents: dict[str, CsvDocument], plan: PlannedMutation
    ) -> list[MutationResult]:
        if plan.status != "planned":
            return [MutationResult(plan, None, None, "skipped", {"reason": plan.reason})]
        document = documents[plan.file_type]
        for service in self.services:
            if plan.defect_type in service.TYPES:
                return service.apply(document, plan)
        return CellMutationService().apply(document, plan)
