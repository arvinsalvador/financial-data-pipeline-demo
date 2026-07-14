from fnmatch import fnmatch
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PipelineDefinition,
    SourceSchemaMapping,
    SourceSchemaMappingColumn,
    Tenant,
)

INGESTION_VERSION = "1.0.0"

COMMON_ALIASES: dict[str, list[str]] = {
    "source_record_id": ["transaction_id", "id", "record_id", "reference", "reference_number"],
    "transaction_date": ["transaction_date", "date", "trans_date"],
    "posted_date": ["posted_date", "posting_date", "post_date"],
    "description": ["description", "details", "transaction_description", "name"],
    "amount": ["amount", "transaction_amount", "net_amount"],
    "debit_amount": ["debit", "debit_amount", "withdrawal", "withdrawals"],
    "credit_amount": ["credit", "credit_amount", "deposit", "deposits"],
    "running_balance": ["balance", "running_balance"],
    "account_source_code": ["account", "account_id", "account_number", "account_name"],
    "category_raw": ["category", "transaction_category", "type"],
    "memo_raw": ["memo", "notes", "note"],
    "merchant_raw": ["merchant", "merchant_name", "description", "name"],
    "currency": ["currency", "currency_code"],
    "employee_source_id": ["employee_id", "employee_number", "employee_uuid", "employee"],
    "employee_name_raw": ["employee_name", "name", "employee"],
    "payroll_run_source_id": ["payroll_id", "payroll_run_id", "payroll_uuid"],
    "pay_period_start": ["pay_period_start", "period_start", "start_date"],
    "pay_period_end": ["pay_period_end", "period_end", "end_date"],
    "pay_date": ["pay_date", "check_date", "payment_date"],
    "gross_pay": ["gross_pay", "gross_earnings", "gross"],
    "net_pay": ["net_pay", "net_payment", "net"],
    "employee_deductions": ["employee_deductions", "deductions"],
    "employer_contributions": ["employer_contributions", "company_contributions"],
    "reimbursements": ["reimbursements", "reimbursement"],
    "regular_pay": ["regular_pay", "regular_earnings"],
    "overtime_pay": ["overtime_pay", "overtime_earnings"],
    "bonus_pay": ["bonus_pay", "bonus"],
    "reimbursement_amount": ["reimbursement_amount", "reimbursement"],
    "employee_tax": ["employee_tax", "employee_taxes"],
    "employee_deduction": ["employee_deduction", "deduction_amount"],
    "employer_tax": ["employer_tax", "employer_taxes"],
    "employer_contribution": ["employer_contribution", "company_contribution"],
    "earning_type_raw": ["earning_type", "earnings_type"],
    "deduction_type_raw": ["deduction_type", "deductions_type"],
}

MAPPING_SPECS: tuple[dict[str, Any], ...] = (
    {
        "code": "checking_account_main_v1",
        "name": "Main checking account",
        "pattern": "checking_account_main.csv",
        "target": "bank_transaction",
        "fields": [
            "source_record_id",
            "account_source_code",
            "transaction_date",
            "posted_date",
            "description",
            "amount",
            "debit_amount",
            "credit_amount",
            "running_balance",
            "category_raw",
            "memo_raw",
            "currency",
        ],
    },
    {
        "code": "checking_account_secondary_v1",
        "name": "Secondary checking account",
        "pattern": "checking_account_secondary.csv",
        "target": "bank_transaction",
        "fields": [
            "source_record_id",
            "account_source_code",
            "transaction_date",
            "posted_date",
            "description",
            "amount",
            "debit_amount",
            "credit_amount",
            "running_balance",
            "category_raw",
            "memo_raw",
            "currency",
        ],
    },
    {
        "code": "credit_card_account_v1",
        "name": "Credit card account",
        "pattern": "credit_card_account.csv",
        "target": "credit_card_transaction",
        "fields": [
            "source_record_id",
            "account_source_code",
            "transaction_date",
            "posted_date",
            "description",
            "merchant_raw",
            "amount",
            "debit_amount",
            "credit_amount",
            "category_raw",
            "memo_raw",
            "currency",
        ],
    },
    {
        "code": "gusto_payroll_v1",
        "name": "Gusto payroll summary",
        "pattern": "gusto_payroll.csv",
        "target": "payroll_summary",
        "fields": [
            "source_record_id",
            "payroll_run_source_id",
            "pay_period_start",
            "pay_period_end",
            "pay_date",
            "employee_source_id",
            "employee_name_raw",
            "gross_pay",
            "employee_deductions",
            "employer_contributions",
            "reimbursements",
            "net_pay",
            "currency",
        ],
    },
    {
        "code": "gusto_payroll_bc_v1",
        "name": "Gusto payroll detail",
        "pattern": "gusto_payroll_bc.csv",
        "target": "payroll_detail",
        "fields": [
            "source_record_id",
            "payroll_run_source_id",
            "pay_period_start",
            "pay_period_end",
            "pay_date",
            "employee_source_id",
            "employee_name_raw",
            "earning_type_raw",
            "deduction_type_raw",
            "gross_pay",
            "regular_pay",
            "overtime_pay",
            "bonus_pay",
            "reimbursement_amount",
            "employee_tax",
            "employee_deduction",
            "employer_tax",
            "employer_contribution",
            "net_pay",
            "currency",
        ],
    },
)


def _data_type(field: str) -> str:
    if field.endswith("_date") or field.startswith("pay_period_") or field == "transaction_date":
        return "date"
    if field in {
        "amount",
        "debit_amount",
        "credit_amount",
        "running_balance",
        "gross_pay",
        "net_pay",
        "employee_deductions",
        "employer_contributions",
        "reimbursements",
        "regular_pay",
        "overtime_pay",
        "bonus_pay",
        "reimbursement_amount",
        "employee_tax",
        "employee_deduction",
        "employer_tax",
        "employer_contribution",
    }:
        return "decimal"
    return "string"


def seed_ingestion_data(session: Session) -> dict[str, int]:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "csv_ingestion",
            PipelineDefinition.version == INGESTION_VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="csv_ingestion",
                name="CSV Raw and Staging Ingestion",
                description=(
                    "Preserves registered CSV rows and loads validated "
                    "source-specific staging records."
                ),
                version=INGESTION_VERSION,
                is_active=True,
                configuration_schema_json={},
            )
        )
    created = 0
    for tenant in session.scalars(select(Tenant)).all():
        for spec in MAPPING_SPECS:
            mapping = session.scalar(
                select(SourceSchemaMapping).where(
                    SourceSchemaMapping.tenant_id == tenant.id,
                    SourceSchemaMapping.mapping_code == spec["code"],
                    SourceSchemaMapping.mapping_version == INGESTION_VERSION,
                )
            )
            if mapping is not None:
                continue
            fields = list(spec["fields"])
            required = (
                ["transaction_date"]
                if spec["target"] in {"bank_transaction", "credit_card_transaction"}
                else ["pay_date", "employee_source_id"]
            )
            mapping = SourceSchemaMapping(
                tenant_id=tenant.id,
                source_file_pattern=str(spec["pattern"]),
                mapping_code=str(spec["code"]),
                mapping_name=str(spec["name"]),
                mapping_version=INGESTION_VERSION,
                target_record_type=str(spec["target"]),
                is_active=True,
                required_columns_json=required,
                optional_columns_json=[field for field in fields if field not in required],
                configuration_json={
                    "selection": "filename_pattern_and_profile_headers",
                    "amount_rule": "at least one of amount/debit_amount/credit_amount",
                },
            )
            for order, field in enumerate(fields, 1):
                aliases = COMMON_ALIASES[field]
                mapping.columns.append(
                    SourceSchemaMappingColumn(
                        source_column_name=aliases[0],
                        canonical_field_name=field,
                        target_data_type=_data_type(field),
                        is_required=field in required,
                        parser_name={"date": "parse_date", "decimal": "parse_decimal"}.get(
                            _data_type(field), "preserve_text"
                        ),
                        transformation_config_json={"aliases": aliases},
                        column_order=order,
                    )
                )
            session.add(mapping)
            created += 1
    session.commit()
    return {
        "mappings_created": created,
        "mapping_specs": len(MAPPING_SPECS),
        "pipeline_definitions": 1,
    }


def mapping_matches_filename(mapping: SourceSchemaMapping, filename: str) -> bool:
    return fnmatch(filename.lower(), mapping.source_file_pattern.lower())
