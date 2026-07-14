from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineDefinition, Tenant, ValidationRule, ValidationRuleSet

VERSION = "1.0.0"
RULE_SET_CODE = "financial_data_quality_v1"

RULES: tuple[tuple[str, str, str, str, str, dict[str, Any]], ...] = (
    ("schema_expected_columns", "Expected schema", "schema", "file", "critical", {}),
    ("schema_nonempty", "Non-empty file", "schema", "file", "error", {}),
    ("required_fields", "Required fields", "required_fields", "record", "error", {}),
    ("identifier_presence_format", "Identifier validity", "identifiers", "record", "error", {}),
    ("date_values", "Date validity", "dates", "record", "error", {}),
    ("monetary_values", "Monetary validity", "monetary", "record", "error", {}),
    ("duplicate_rows", "Exact duplicate rows", "duplicates", "record", "warning", {}),
    ("duplicate_identifiers", "Duplicate identifiers", "duplicates", "record", "error", {}),
    ("relationships", "Required relationships", "relationships", "record", "error", {}),
    ("canonical_lineage", "Canonical lineage", "relationships", "canonical", "error", {}),
    ("invoice_totals", "Invoice and line totals", "financial", "invoice", "critical", {}),
    ("payment_totals", "Payment application totals", "financial", "payment", "critical", {}),
    ("ap_totals", "Accounts payable totals", "financial", "accounts_payable", "critical", {}),
    ("gl_balanced", "General ledger balance", "financial", "general_ledger", "critical", {}),
    ("payroll_totals", "Payroll totals", "financial", "payroll", "critical", {}),
    ("running_balances", "Running cash balances", "financial", "bank_transaction", "error", {}),
    (
        "ingestion_control_reconciliation",
        "Ingestion row controls",
        "controls",
        "pipeline",
        "critical",
        {},
    ),
    (
        "generated_controls",
        "Generated source controls",
        "controls",
        "generated_dataset",
        "critical",
        {},
    ),
    ("messy_expected_counts", "Messy expected counts", "controls", "messy_dataset", "critical", {}),
    ("invoice_date_order", "Invoice date ordering", "business", "invoice", "error", {}),
    ("payment_after_invoice", "Payment after invoice", "business", "payment", "error", {}),
    ("lost_deal_not_invoiced", "Lost deals are not invoiced", "business", "crm_deal", "error", {}),
    ("inactive_relationships", "Inactive master data usage", "business", "record", "warning", {}),
    ("cross_file_payment_links", "Payment and invoice links", "cross_file", "payment", "error", {}),
    ("cross_file_ap_vendor", "AP and vendor links", "cross_file", "accounts_payable", "error", {}),
    (
        "cross_file_forecast",
        "Forecast assumptions",
        "cross_file",
        "forecast_assumption",
        "warning",
        {},
    ),
)


def seed_validation_data(session: Session) -> None:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "validation_engine", PipelineDefinition.version == VERSION
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="validation_engine",
                name="Financial Data Validation Engine",
                description="Versioned deterministic data-quality validation",
                version=VERSION,
                is_active=True,
                configuration_schema_json={"rule_set": RULE_SET_CODE},
            )
        )
    for tenant in session.scalars(select(Tenant).order_by(Tenant.id)):
        rule_set = session.scalar(
            select(ValidationRuleSet).where(
                ValidationRuleSet.tenant_id == tenant.id,
                ValidationRuleSet.code == RULE_SET_CODE,
                ValidationRuleSet.version == VERSION,
            )
        )
        if rule_set is None:
            rule_set = ValidationRuleSet(
                tenant_id=tenant.id,
                code=RULE_SET_CODE,
                name="Financial Data Quality Rules",
                description="Phase 8 rules for raw, staging, canonical, generated and messy data",
                version=VERSION,
                is_active=True,
                configuration_json={
                    "severity_model": ["information", "warning", "error", "critical"]
                },
            )
            session.add(rule_set)
            session.flush()
        for order, (code, name, group, entity, severity, config) in enumerate(RULES, 1):
            rule = session.scalar(
                select(ValidationRule).where(
                    ValidationRule.validation_rule_set_id == rule_set.id,
                    ValidationRule.code == code,
                )
            )
            if rule is None:
                session.add(
                    ValidationRule(
                        validation_rule_set_id=rule_set.id,
                        code=code,
                        name=name,
                        description=f"Deterministic {name.lower()} validation",
                        rule_group=group,
                        target_entity=entity,
                        severity=severity,
                        version=VERSION,
                        execution_order=order,
                        is_enabled=True,
                        configuration_json=config,
                    )
                )
    session.commit()
