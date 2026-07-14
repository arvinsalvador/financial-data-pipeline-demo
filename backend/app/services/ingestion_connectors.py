from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models import (
    SourceSchemaMapping,
    StagingBankTransaction,
    StagingCreditCardTransaction,
    StagingPayrollDetail,
    StagingPayrollSummary,
)
from app.services.profile_parsing import parse_date, parse_decimal


@dataclass(frozen=True)
class RowError:
    code: str
    category: str
    field: str | None
    observed: str | None
    message: str
    severity: str = "error"


@dataclass
class ParsedRow:
    values: dict[str, Any]
    errors: list[RowError]


def normalize_header(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", " ").split())


class BaseSourceConnector:
    target_record_type = ""
    staging_model: type[Any]
    connector_name = "BaseSourceConnector"

    def __init__(self, mapping: SourceSchemaMapping, headers: list[str]) -> None:
        self.mapping = mapping
        normalized = {normalize_header(header): header for header in headers}
        self.bindings: dict[str, str] = {}
        for column in mapping.columns:
            config = column.transformation_config_json or {}
            aliases = [column.source_column_name, *config.get("aliases", [])]
            matches = {
                normalized[normalize_header(alias)]
                for alias in aliases
                if normalize_header(alias) in normalized
            }
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous columns for {column.canonical_field_name}: {sorted(matches)}"
                )
            if matches:
                self.bindings[column.canonical_field_name] = matches.pop()
            elif column.is_required:
                raise ValueError(
                    f"Required mapped column is unavailable: {column.canonical_field_name}"
                )

    def parse(self, raw: dict[str, str | None]) -> ParsedRow:
        values: dict[str, Any] = {}
        errors: list[RowError] = []
        for column in self.mapping.columns:
            field = column.canonical_field_name
            source = self.bindings.get(field)
            observed = raw.get(source) if source else None
            text = observed.strip() if observed is not None else ""
            if column.is_required and not text:
                errors.append(
                    RowError(
                        "missing_required_field",
                        "required_field",
                        field,
                        observed,
                        f"{field} is required",
                    )
                )
                continue
            if not text:
                values[field] = None
            elif column.target_data_type == "date":
                result = parse_date(text)
                if result.value is None:
                    errors.append(
                        RowError(
                            "invalid_date",
                            "date",
                            field,
                            observed,
                            f"{field} is not a supported unambiguous date",
                        )
                    )
                else:
                    values[field] = result.value.date()
            elif column.target_data_type == "decimal":
                parsed = parse_decimal(text, currency=True)
                if parsed is None:
                    errors.append(
                        RowError(
                            "invalid_monetary_value",
                            "monetary",
                            field,
                            observed,
                            f"{field} is not a valid monetary value",
                        )
                    )
                else:
                    values[field] = parsed
            else:
                values[field] = text
        self.validate(values, raw, errors)
        return ParsedRow(values, errors)

    def validate(
        self, values: dict[str, Any], raw: dict[str, str | None], errors: list[RowError]
    ) -> None:
        del values, raw, errors

    def build(self, common: dict[str, Any], values: dict[str, Any]) -> Any:
        raise NotImplementedError

    @staticmethod
    def monetary_total(values: dict[str, Any]) -> Decimal | None:
        amount = values.get("amount")
        if isinstance(amount, Decimal):
            return amount
        debit, credit = values.get("debit_amount"), values.get("credit_amount")
        if isinstance(debit, Decimal) or isinstance(credit, Decimal):
            return (credit or Decimal(0)) - (debit or Decimal(0))
        net = values.get("net_pay")
        return net if isinstance(net, Decimal) else None


class BankConnector(BaseSourceConnector):
    target_record_type = "bank_transaction"
    staging_model: type[Any] = StagingBankTransaction

    def validate(
        self, values: dict[str, Any], raw: dict[str, str | None], errors: list[RowError]
    ) -> None:
        del raw
        if not any(
            isinstance(values.get(field), Decimal)
            for field in ("amount", "debit_amount", "credit_amount")
        ):
            errors.append(
                RowError(
                    "missing_amount",
                    "required_field",
                    "amount",
                    None,
                    "At least one amount, debit, or credit value is required",
                )
            )

    def build(self, common: dict[str, Any], values: dict[str, Any]) -> Any:
        return StagingBankTransaction(
            **common,
            account_source_code=values.get("account_source_code"),
            transaction_date=values["transaction_date"],
            posted_date=values.get("posted_date"),
            description=values.get("description"),
            reference_number=values.get("source_record_id"),
            amount=values.get("amount"),
            debit_amount=values.get("debit_amount"),
            credit_amount=values.get("credit_amount"),
            running_balance=values.get("running_balance"),
            currency=values.get("currency"),
            counterparty_raw=None,
            category_raw=values.get("category_raw"),
            memo_raw=values.get("memo_raw"),
        )


class MainCheckingConnector(BankConnector):
    connector_name = "MainCheckingConnector"


class SecondaryCheckingConnector(BankConnector):
    connector_name = "SecondaryCheckingConnector"


class CreditCardConnector(BankConnector):
    target_record_type = "credit_card_transaction"
    staging_model = StagingCreditCardTransaction
    connector_name = "CreditCardConnector"

    def build(self, common: dict[str, Any], values: dict[str, Any]) -> StagingCreditCardTransaction:
        return StagingCreditCardTransaction(
            **common,
            credit_account_source_code=values.get("account_source_code"),
            transaction_date=values["transaction_date"],
            posted_date=values.get("posted_date"),
            description=values.get("description"),
            merchant_raw=values.get("merchant_raw"),
            reference_number=values.get("source_record_id"),
            amount=values.get("amount"),
            debit_amount=values.get("debit_amount"),
            credit_amount=values.get("credit_amount"),
            category_raw=values.get("category_raw"),
            currency=values.get("currency"),
            memo_raw=values.get("memo_raw"),
        )


class PayrollConnector(BaseSourceConnector):
    def build_common_payroll(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "payroll_run_source_id": values.get("payroll_run_source_id"),
            "pay_period_start": values.get("pay_period_start"),
            "pay_period_end": values.get("pay_period_end"),
            "pay_date": values["pay_date"],
            "employee_source_id": values["employee_source_id"],
            "employee_name_raw": values.get("employee_name_raw"),
            "gross_pay": values.get("gross_pay"),
            "net_pay": values.get("net_pay"),
            "currency": values.get("currency"),
        }


class PayrollSummaryConnector(PayrollConnector):
    target_record_type = "payroll_summary"
    staging_model = StagingPayrollSummary
    connector_name = "PayrollSummaryConnector"

    def build(self, common: dict[str, Any], values: dict[str, Any]) -> StagingPayrollSummary:
        return StagingPayrollSummary(
            **common,
            **self.build_common_payroll(values),
            employee_deductions=values.get("employee_deductions"),
            employer_contributions=values.get("employer_contributions"),
            reimbursements=values.get("reimbursements"),
        )


class PayrollDetailConnector(PayrollConnector):
    target_record_type = "payroll_detail"
    staging_model = StagingPayrollDetail
    connector_name = "PayrollDetailConnector"

    def build(self, common: dict[str, Any], values: dict[str, Any]) -> StagingPayrollDetail:
        return StagingPayrollDetail(
            **common,
            **self.build_common_payroll(values),
            earning_type_raw=values.get("earning_type_raw"),
            deduction_type_raw=values.get("deduction_type_raw"),
            regular_pay=values.get("regular_pay"),
            overtime_pay=values.get("overtime_pay"),
            bonus_pay=values.get("bonus_pay"),
            reimbursement_amount=values.get("reimbursement_amount"),
            employee_tax=values.get("employee_tax"),
            employee_deduction=values.get("employee_deduction"),
            employer_tax=values.get("employer_tax"),
            employer_contribution=values.get("employer_contribution"),
        )


CONNECTORS: dict[str, type[BaseSourceConnector]] = {
    "checking_account_main_v1": MainCheckingConnector,
    "checking_account_secondary_v1": SecondaryCheckingConnector,
    "credit_card_account_v1": CreditCardConnector,
    "gusto_payroll_v1": PayrollSummaryConnector,
    "gusto_payroll_bc_v1": PayrollDetailConnector,
}


def connector_for(mapping: SourceSchemaMapping, headers: list[str]) -> BaseSourceConnector:
    connector_type = CONNECTORS.get(mapping.mapping_code)
    if connector_type is None or connector_type.target_record_type != mapping.target_record_type:
        raise ValueError("No unambiguous connector exists for this mapping")
    return connector_type(mapping, headers)
