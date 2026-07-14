from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PipelineDefinition, ReconciliationRule, Tenant

VERSION = "1.0.0"

RULES: tuple[tuple[str, str, str, bool, str, dict[str, Any]], ...] = (
    (
        "exact_reference_amount",
        "Exact reference and amount",
        "one_to_one",
        True,
        "1.000000",
        {"date_tolerance_days": 3},
    ),
    ("exact_amount_exact_date", "Exact amount and exact date", "one_to_one", True, "0.980000", {}),
    (
        "exact_amount_date_tolerance",
        "Exact amount in date tolerance",
        "one_to_one",
        False,
        "0.850000",
        {"date_tolerance_days": 3},
    ),
    (
        "exact_reference_date_tolerance",
        "Exact reference in date tolerance",
        "one_to_one",
        False,
        "0.900000",
        {"date_tolerance_days": 3},
    ),
    (
        "normalized_description_amount",
        "Description-assisted amount",
        "suggestion",
        False,
        "0.650000",
        {},
    ),
    (
        "one_bank_to_many_ledger",
        "One bank to many ledger",
        "one_to_many",
        False,
        "0.900000",
        {"maximum_group_size": 5},
    ),
    (
        "many_bank_to_one_ledger",
        "Many bank to one ledger",
        "many_to_one",
        False,
        "0.900000",
        {"maximum_group_size": 5},
    ),
    ("duplicate_bank_detection", "Duplicate bank detection", "duplicate", False, "1.000000", {}),
    (
        "duplicate_ledger_detection",
        "Duplicate ledger detection",
        "duplicate",
        False,
        "1.000000",
        {},
    ),
    (
        "reversed_transaction_detection",
        "Reversal detection",
        "reversal",
        False,
        "0.800000",
        {"date_tolerance_days": 7},
    ),
    (
        "unmatched_bank_classification",
        "Unmatched bank classification",
        "classification",
        False,
        "0.000000",
        {},
    ),
    (
        "unmatched_ledger_classification",
        "Unmatched ledger classification",
        "classification",
        False,
        "0.000000",
        {},
    ),
)


def seed_reconciliation_data(session: Session, settings: Settings) -> None:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "bank_ledger_reconciliation",
            PipelineDefinition.version == VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="bank_ledger_reconciliation",
                name="Bank-to-Ledger Reconciliation",
                description="Deterministic canonical bank to generated cash-ledger matching",
                version=VERSION,
                is_active=True,
                configuration_schema_json={
                    "amount_tolerance": settings.RECONCILIATION_AMOUNT_TOLERANCE
                },
            )
        )
    for tenant in session.scalars(select(Tenant).order_by(Tenant.id)):
        for order, (code, name, rule_type, auto_accept, confidence, config) in enumerate(RULES, 1):
            rule = session.scalar(
                select(ReconciliationRule).where(
                    ReconciliationRule.tenant_id == tenant.id,
                    ReconciliationRule.code == code,
                    ReconciliationRule.version == VERSION,
                )
            )
            merged = {
                "amount_tolerance": settings.RECONCILIATION_AMOUNT_TOLERANCE,
                "date_tolerance_days": settings.RECONCILIATION_DATE_TOLERANCE_DAYS,
                "maximum_group_size": settings.RECONCILIATION_MAX_GROUP_SIZE,
                **config,
            }
            if rule is None:
                session.add(
                    ReconciliationRule(
                        tenant_id=tenant.id,
                        code=code,
                        name=name,
                        description=f"Deterministic {name.lower()} rule",
                        version=VERSION,
                        rule_type=rule_type,
                        execution_order=order,
                        is_active=True,
                        auto_accept=auto_accept,
                        minimum_confidence=Decimal(confidence),
                        configuration_json=merged,
                    )
                )
            else:
                rule.configuration_json = merged
    session.commit()
