from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import InvoiceCollectionsReconciliationRule, PipelineDefinition, Tenant

VERSION = "1.0.0"
RULE_CODES = (
    "crm_deal_to_invoice_exact",
    "invoice_internal_total_validation",
    "invoice_to_payment_application_exact",
    "payment_to_invoice_reference_exact",
    "payment_to_invoice_customer_amount",
    "payment_to_invoice_date_tolerance",
    "payment_to_multiple_invoices",
    "multiple_payments_to_invoice",
    "payment_to_bank_deposit_exact",
    "payment_to_bank_deposit_date_tolerance",
    "multiple_payments_to_combined_deposit",
    "one_payment_to_split_deposits",
    "invoice_to_gl_receivable_exact",
    "payment_to_gl_cash_and_ar_exact",
    "duplicate_invoice_detection",
    "duplicate_payment_detection",
    "missing_payment_classification",
    "unapplied_payment_classification",
    "overpayment_detection",
    "underpayment_detection",
    "unmatched_deposit_classification",
    "invalid_relationship_classification",
)


def seed_invoice_collections_data(session: Session, settings: Settings) -> None:
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "invoice_collections_reconciliation",
            PipelineDefinition.version == VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="invoice_collections_reconciliation",
                name="Invoice and Collections Reconciliation",
                description=(
                    "Deterministic invoice, payment, deposit, GL, and AR aging reconciliation"
                ),
                version=VERSION,
                is_active=True,
                configuration_schema_json={
                    "aging_buckets": settings.INVOICE_COLLECTIONS_AGING_BUCKETS.split(",")
                },
            )
        )
    config = {
        "amount_tolerance": settings.INVOICE_COLLECTIONS_AMOUNT_TOLERANCE,
        "date_tolerance_days": settings.INVOICE_COLLECTIONS_DATE_TOLERANCE_DAYS,
        "max_payments_per_invoice": settings.INVOICE_COLLECTIONS_MAX_PAYMENTS_PER_INVOICE,
        "max_invoices_per_payment": settings.INVOICE_COLLECTIONS_MAX_INVOICES_PER_PAYMENT,
        "max_payments_per_deposit": settings.INVOICE_COLLECTIONS_MAX_PAYMENTS_PER_DEPOSIT,
        "max_deposits_per_payment": settings.INVOICE_COLLECTIONS_MAX_DEPOSITS_PER_PAYMENT,
        "auto_accept_grouped": settings.INVOICE_COLLECTIONS_AUTO_ACCEPT_GROUPED,
    }
    auto = {
        "crm_deal_to_invoice_exact",
        "invoice_to_payment_application_exact",
        "payment_to_bank_deposit_exact",
        "invoice_to_gl_receivable_exact",
        "payment_to_gl_cash_and_ar_exact",
    }
    for tenant in session.scalars(select(Tenant).order_by(Tenant.id)):
        for order, code in enumerate(RULE_CODES, 1):
            rule = session.scalar(
                select(InvoiceCollectionsReconciliationRule).where(
                    InvoiceCollectionsReconciliationRule.tenant_id == tenant.id,
                    InvoiceCollectionsReconciliationRule.code == code,
                    InvoiceCollectionsReconciliationRule.version == VERSION,
                )
            )
            if rule is None:
                session.add(
                    InvoiceCollectionsReconciliationRule(
                        tenant_id=tenant.id,
                        code=code,
                        name=code.replace("_", " ").title(),
                        description=f"Deterministic {code.replace('_', ' ')} rule",
                        version=VERSION,
                        rule_type=code.split("_")[0],
                        execution_order=order,
                        is_active=True,
                        auto_accept=code in auto,
                        minimum_confidence=Decimal("0.98") if code in auto else Decimal("0.65"),
                        configuration_json=config,
                    )
                )
            else:
                rule.configuration_json = config
    session.commit()
