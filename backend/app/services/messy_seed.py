from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DefectScenario, DefectScenarioRule, PipelineDefinition, SourceSystem, Tenant

VERSION = "1.0.0"

STANDARD_RULES: tuple[tuple[str, str, str, str | None, int, str, dict[str, Any]], ...] = (
    ("duplicate_bank_rows", "exact_duplicate_row", "general_ledger", None, 2, "error", {}),
    (
        "missing_transaction_ids",
        "missing_transaction_identifier",
        "general_ledger",
        "journal_line_id",
        2,
        "error",
        {},
    ),
    (
        "mixed_bank_dates",
        "inconsistent_date_format",
        "general_ledger",
        "entry_date",
        2,
        "warning",
        {"format": "%m/%d/%Y"},
    ),
    (
        "invalid_running_balance",
        "invalid_running_balance",
        "general_ledger",
        "running_balance",
        1,
        "error",
        {},
    ),
    (
        "reversed_bank_transaction",
        "reversed_transaction",
        "general_ledger",
        "debit",
        1,
        "critical",
        {},
    ),
    (
        "card_amount_format",
        "parentheses_negative",
        "general_ledger",
        "debit",
        2,
        "warning",
        {"filter_source_type": "credit_card_purchase"},
    ),
    (
        "duplicate_card_transaction",
        "near_duplicate_row",
        "general_ledger",
        "description",
        1,
        "error",
        {"filter_source_type": "credit_card_purchase"},
    ),
    (
        "missing_payroll_employee",
        "employee_identifier_missing",
        "general_ledger",
        "payroll_run_id",
        1,
        "error",
        {"filter_source_type": "payroll_run"},
    ),
    (
        "payroll_net_mismatch",
        "payroll_net_mismatch",
        "general_ledger",
        "credit",
        1,
        "critical",
        {"filter_source_type": "payroll_run", "delta": "17.00"},
    ),
    (
        "payroll_bank_mismatch",
        "payroll_bank_withdrawal_mismatch",
        "general_ledger",
        "credit",
        1,
        "critical",
        {"filter_source_type": "payroll_payment", "delta": "25.00"},
    ),
    (
        "customer_name_typos",
        "misspelled_customer_name",
        "customers",
        "customer_name",
        2,
        "warning",
        {},
    ),
    ("duplicate_invoice", "duplicate_invoice", "invoices", None, 1, "error", {}),
    (
        "invoice_line_mismatch",
        "invoice_total_line_mismatch",
        "invoice_lines",
        "line_total",
        1,
        "critical",
        {"delta": "9.99"},
    ),
    (
        "partial_payment",
        "underpayment",
        "customer_payments",
        "payment_amount",
        1,
        "error",
        {"factor": "0.75"},
    ),
    ("split_payment", "split_payment", "customer_payments", "payment_amount", 1, "warning", {}),
    (
        "combined_deposit",
        "combined_deposit",
        "customer_payments",
        "canonical_bank_transaction_id",
        1,
        "warning",
        {},
    ),
    ("missing_customer_payment", "missing_payment", "customer_payments", None, 1, "critical", {}),
    (
        "overpayment",
        "overpayment",
        "customer_payments",
        "payment_amount",
        1,
        "critical",
        {"factor": "1.25"},
    ),
    ("vendor_name_typo", "misspelled_vendor_name", "vendors", "vendor_name", 1, "warning", {}),
    ("duplicate_ap_bill", "duplicate_ap_bill", "accounts_payable", None, 1, "error", {}),
    (
        "missing_ap_payment",
        "missing_ap_payment",
        "accounts_payable",
        "canonical_payment_transaction_id",
        1,
        "critical",
        {},
    ),
    (
        "unbalanced_journal",
        "unbalanced_journal_entry",
        "general_ledger",
        "debit",
        1,
        "critical",
        {"delta": "1.00"},
    ),
    (
        "missing_gl_cash",
        "missing_gl_entry",
        "general_ledger",
        None,
        1,
        "critical",
        {"filter_account_code": "1000"},
    ),
    (
        "invalid_gl_account",
        "invalid_account_code",
        "general_ledger",
        "account_code",
        1,
        "critical",
        {"value": "INVALID-999"},
    ),
    (
        "stale_assumption",
        "stale_assumption",
        "forecast_assumptions",
        "effective_end_date",
        1,
        "warning",
        {"value": "2020-12-31"},
    ),
    (
        "invalid_amount_text",
        "invalid_monetary_text",
        "accounts_payable",
        "total_amount",
        1,
        "error",
        {"value": "NOT_A_NUMBER"},
    ),
    ("currency_symbol", "currency_symbol_added", "invoices", "subtotal", 1, "warning", {}),
    (
        "invalid_due_date",
        "invalid_due_date",
        "invoices",
        "due_date",
        1,
        "error",
        {"value": "2026-99-99"},
    ),
    (
        "future_date",
        "future_date",
        "crm_deals",
        "created_date",
        1,
        "warning",
        {"value": "2099-01-01"},
    ),
    (
        "invalid_scenario",
        "invalid_scenario",
        "forecast_assumptions",
        "scenario",
        1,
        "error",
        {"value": "impossible"},
    ),
)


def seed_messy_data(session: Session) -> dict[str, int]:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "messy_data_generation",
            PipelineDefinition.version == VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="messy_data_generation",
                name="Controlled Messy Data Generation",
                description=(
                    "Creates deterministic defective copies and expected exception manifests."
                ),
                version=VERSION,
                is_active=True,
                configuration_schema_json={"default_scenario": "standard_messy_v1"},
            )
        )
    rules_created = 0
    for tenant in session.scalars(select(Tenant)).all():
        source = session.scalar(
            select(SourceSystem).where(
                SourceSystem.tenant_id == tenant.id,
                SourceSystem.code == "generated_demo_business_messy",
            )
        )
        if source is None:
            session.add(
                SourceSystem(
                    tenant_id=tenant.id,
                    code="generated_demo_business_messy",
                    name="Generated Demo Business Messy Sources",
                    description=(
                        "Controlled deterministic defective copies of clean generated "
                        "business sources"
                    ),
                    source_type="generated_csv",
                    is_active=True,
                )
            )
            session.flush()
        for code, name, description, multiplier, selected in (
            (
                "light_messy_v1",
                "Light Messy Data",
                "Small formatting and duplicate issue set.",
                1,
                STANDARD_RULES[:6],
            ),
            (
                "standard_messy_v1",
                "Standard Messy Data",
                "Balanced portfolio demonstration defect set.",
                1,
                STANDARD_RULES,
            ),
            (
                "hostile_messy_v1",
                "Hostile Messy Data",
                "Higher-density stress and recovery defect set.",
                2,
                STANDARD_RULES,
            ),
        ):
            scenario = session.scalar(
                select(DefectScenario).where(
                    DefectScenario.tenant_id == tenant.id,
                    DefectScenario.code == code,
                    DefectScenario.version == VERSION,
                )
            )
            if scenario is None:
                scenario = DefectScenario(
                    tenant_id=tenant.id,
                    code=code,
                    name=name,
                    description=description,
                    version=VERSION,
                    is_system_scenario=True,
                    is_active=True,
                    configuration_json={"conflict_policy": "skip_later"},
                )
                session.add(scenario)
                session.flush()
            for order, spec in enumerate(selected, 1):
                rule_code, defect_type, file_type, column, count, severity, config = spec
                rule = session.scalar(
                    select(DefectScenarioRule).where(
                        DefectScenarioRule.defect_scenario_id == scenario.id,
                        DefectScenarioRule.rule_code == rule_code,
                    )
                )
                if rule is None:
                    session.add(
                        DefectScenarioRule(
                            defect_scenario_id=scenario.id,
                            rule_code=rule_code,
                            defect_type=defect_type,
                            target_file_type=file_type,
                            target_column=column,
                            requested_count=count * multiplier,
                            requested_percentage=None,
                            severity=severity,
                            is_enabled=True,
                            rule_order=order,
                            configuration_json=config,
                        )
                    )
                    rules_created += 1
    session.commit()
    return {"scenarios": 3, "rules_created": rules_created}
