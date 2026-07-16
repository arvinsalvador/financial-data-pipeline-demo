from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PayrollReconciliationRule, PipelineDefinition, Tenant

VERSION = "1.0.0"
RULES = (
    ("payroll_run_internal_totals", "Payroll run internal totals", "control", False, "1.000000"),
    ("payroll_entries_to_run", "Payroll entries to run", "control", False, "1.000000"),
    ("payroll_run_to_bank_exact_net", "Exact payroll net to bank", "bank", True, "1.000000"),
    (
        "payroll_run_to_bank_date_tolerance",
        "Payroll to bank date tolerance",
        "bank",
        False,
        "0.900000",
    ),
    ("payroll_run_to_gl_exact_totals", "Exact payroll GL totals", "gl", True, "1.000000"),
    ("payroll_run_to_gl_date_tolerance", "Payroll GL date tolerance", "gl", False, "0.900000"),
    ("payroll_bank_batch_grouping", "Payroll bank grouping", "group", False, "0.900000"),
    ("payroll_gl_batch_grouping", "Payroll GL grouping", "group", False, "0.900000"),
    ("payroll_duplicate_detection", "Payroll duplicate detection", "duplicate", False, "1.000000"),
    ("payroll_reversal_detection", "Payroll reversal detection", "reversal", False, "0.800000"),
    ("payroll_partial_match", "Payroll partial match", "partial", False, "0.650000"),
    (
        "payroll_unmatched_classification",
        "Payroll unmatched classification",
        "classification",
        False,
        "0.000000",
    ),
)


def seed_payroll_reconciliation_data(session: Session, settings: Settings) -> None:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "payroll_reconciliation",
            PipelineDefinition.version == VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="payroll_reconciliation",
                name="Payroll Reconciliation",
                description="Deterministic payroll-to-bank-to-ledger reconciliation",
                version=VERSION,
                is_active=True,
                configuration_schema_json={
                    "settlement_models": [
                        "net_pay_only",
                        "net_pay_plus_taxes",
                        "full_payroll_cash_requirement",
                        "split_withdrawals",
                        "configured_components",
                    ]
                },
            )
        )
    for tenant in session.scalars(select(Tenant).order_by(Tenant.id)):
        for order, (code, name, rule_type, auto, confidence) in enumerate(RULES, 1):
            rule = session.scalar(
                select(PayrollReconciliationRule).where(
                    PayrollReconciliationRule.tenant_id == tenant.id,
                    PayrollReconciliationRule.code == code,
                    PayrollReconciliationRule.version == VERSION,
                )
            )
            config = {
                "amount_tolerance": settings.PAYROLL_RECONCILIATION_AMOUNT_TOLERANCE,
                "date_tolerance_days": settings.PAYROLL_RECONCILIATION_DATE_TOLERANCE_DAYS,
                "settlement_model": settings.PAYROLL_RECONCILIATION_DEFAULT_SETTLEMENT_MODEL,
                "minimum_auto_accept_confidence": (
                    settings.PAYROLL_RECONCILIATION_MIN_AUTO_ACCEPT_CONFIDENCE
                ),
                "minimum_suggestion_confidence": (
                    settings.PAYROLL_RECONCILIATION_MIN_SUGGESTION_CONFIDENCE
                ),
                "maximum_bank_group_size": settings.PAYROLL_RECONCILIATION_MAX_BANK_GROUP_SIZE,
                "maximum_gl_group_size": settings.PAYROLL_RECONCILIATION_MAX_GL_GROUP_SIZE,
                "maximum_candidates_per_run": (
                    settings.PAYROLL_RECONCILIATION_MAX_CANDIDATES_PER_RUN
                ),
                "duplicate_date_tolerance_days": (
                    settings.PAYROLL_RECONCILIATION_DUPLICATE_DATE_TOLERANCE_DAYS
                ),
                "reversal_date_tolerance_days": (
                    settings.PAYROLL_RECONCILIATION_REVERSAL_DATE_TOLERANCE_DAYS
                ),
                "employee_tolerance": settings.PAYROLL_RECONCILIATION_EMPLOYEE_TOLERANCE,
            }
            if rule is None:
                session.add(
                    PayrollReconciliationRule(
                        tenant_id=tenant.id,
                        code=code,
                        name=name,
                        description=f"Deterministic {name.lower()} rule",
                        version=VERSION,
                        rule_type=rule_type,
                        execution_order=order,
                        is_active=True,
                        auto_accept=auto,
                        minimum_confidence=Decimal(confidence),
                        configuration_json=config,
                    )
                )
            else:
                rule.configuration_json = config
    session.commit()
