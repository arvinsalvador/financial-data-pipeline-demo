from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BankAccount,
    CreditAccount,
    Currency,
    FinancialAccount,
    NormalizationMapping,
    PipelineDefinition,
    SourceSystem,
    Tenant,
    TransactionCategory,
)

NORMALIZATION_VERSION = "1.0.0"

ACCOUNT_SPECS = (
    ("1000", "Cash — Main Operating Account", "asset", "cash", "debit"),
    ("1010", "Cash — Payroll Account", "asset", "cash", "debit"),
    ("2000", "Credit Card Payable", "liability", "credit_card", "credit"),
    ("1100", "Accounts Receivable", "asset", "accounts_receivable", "debit"),
    ("2010", "Accounts Payable", "liability", "accounts_payable", "credit"),
    ("2030", "Sales Tax Payable", "liability", "sales_tax", "credit"),
    ("4000", "Sales Revenue", "revenue", "sales", "credit"),
    ("5000", "Payroll Expense", "expense", "payroll", "debit"),
    ("5010", "Employer Payroll Taxes", "expense", "payroll_tax", "debit"),
    ("2020", "Payroll Deductions Payable", "liability", "payroll", "credit"),
    ("5100", "General Operating Expense", "expense", "operating", "debit"),
    ("5990", "Uncategorized Expense", "expense", "uncategorized", "debit"),
    ("4990", "Uncategorized Income", "revenue", "uncategorized", "credit"),
)

CATEGORY_SPECS = (
    ("payroll", "Payroll", "expense", "5000"),
    ("payroll_tax", "Payroll Tax", "expense", "5010"),
    ("reimbursement", "Reimbursement", "expense", "5100"),
    ("credit_card_purchase", "Credit Card Purchase", "expense", "5100"),
    ("bank_fee", "Bank Fee", "expense", "5100"),
    ("transfer", "Transfer", "transfer", "1000"),
    ("customer_deposit", "Customer Deposit", "income", "4990"),
    ("vendor_payment", "Vendor Payment", "expense", "5100"),
    ("uncategorized_expense", "Uncategorized Expense", "expense", "5990"),
    ("uncategorized_income", "Uncategorized Income", "income", "4990"),
)

MAPPING_SPECS: tuple[dict[str, Any], ...] = (
    {
        "code": "bank_transaction_main_v1",
        "name": "Main bank normalization",
        "source": "staging_bank_transaction",
        "target": "bank_transaction",
        "ingestion_mapping": "checking_account_main_v1",
        "account": "primary_operating",
        "default_currency": "USD",
        "sign_rule": "positive_inflow_negative_outflow",
    },
    {
        "code": "bank_transaction_secondary_v1",
        "name": "Secondary bank normalization",
        "source": "staging_bank_transaction",
        "target": "bank_transaction",
        "ingestion_mapping": "checking_account_secondary_v1",
        "account": "secondary_payroll",
        "default_currency": "USD",
        "sign_rule": "positive_inflow_negative_outflow",
    },
    {
        "code": "credit_card_transaction_v1",
        "name": "Credit card normalization",
        "source": "staging_credit_card_transaction",
        "target": "credit_card_transaction",
        "ingestion_mapping": "credit_card_account_v1",
        "account": "business_credit_card",
        "default_currency": "USD",
        "sign_rule": "negative_source_purchase_to_positive_liability",
    },
    {
        "code": "payroll_summary_v1",
        "name": "Payroll summary normalization",
        "source": "staging_payroll_summary",
        "target": "payroll_entry",
        "ingestion_mapping": "gusto_payroll_v1",
        "default_currency": "USD",
        "precedence": "detail_over_summary",
    },
    {
        "code": "payroll_detail_v1",
        "name": "Payroll detail normalization",
        "source": "staging_payroll_detail",
        "target": "payroll_entry",
        "ingestion_mapping": "gusto_payroll_bc_v1",
        "default_currency": "USD",
        "precedence": "detail_over_summary",
    },
)


def seed_canonical_data(session: Session) -> dict[str, int]:
    currencies: dict[str, Currency] = {}
    for code, name, symbol, places in (
        ("USD", "US Dollar", "$", 2),
        ("PHP", "Philippine Peso", "₱", 2),
    ):
        currency = session.scalar(select(Currency).where(Currency.code == code))
        if currency is None:
            currency = Currency(
                code=code, name=name, symbol=symbol, decimal_places=places, is_active=True
            )
            session.add(currency)
            session.flush()
        currencies[code] = currency
    definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "canonical_normalization",
            PipelineDefinition.version == NORMALIZATION_VERSION,
        )
    )
    if definition is None:
        session.add(
            PipelineDefinition(
                code="canonical_normalization",
                name="Staging-to-Canonical Financial Normalization",
                version=NORMALIZATION_VERSION,
                is_active=True,
                configuration_schema_json={},
            )
        )
    generation_definition = session.scalar(
        select(PipelineDefinition).where(
            PipelineDefinition.code == "demo_source_generation",
            PipelineDefinition.version == "1.0.0",
        )
    )
    if generation_definition is None:
        session.add(
            PipelineDefinition(
                code="demo_source_generation",
                name="Deterministic Demo Business Source Generation",
                description="Generates clean synthetic business sources from canonical history.",
                version="1.0.0",
                is_active=True,
                configuration_schema_json={"default_seed": 20260714},
            )
        )
    mapping_count = 0
    for tenant in session.scalars(select(Tenant)).all():
        generated_source = session.scalar(
            select(SourceSystem).where(
                SourceSystem.tenant_id == tenant.id,
                SourceSystem.code == "generated_demo_business",
            )
        )
        if generated_source is None:
            session.add(
                SourceSystem(
                    tenant_id=tenant.id,
                    code="generated_demo_business",
                    name="Generated Demo Business Sources",
                    source_type="generated_csv",
                    description=(
                        "Deterministic synthetic CRM, receivables, payables, ledger, and "
                        "forecast-assumption sources derived from canonical demo financial history"
                    ),
                    is_active=True,
                )
            )
            session.flush()
        currency = currencies.get(tenant.default_currency) or currencies["USD"]
        accounts: dict[str, FinancialAccount] = {}
        for code, name, account_type, subtype, normal in ACCOUNT_SPECS:
            account = session.scalar(
                select(FinancialAccount).where(
                    FinancialAccount.tenant_id == tenant.id, FinancialAccount.account_code == code
                )
            )
            if account is None:
                account = FinancialAccount(
                    tenant_id=tenant.id,
                    account_code=code,
                    account_name=name,
                    account_type=account_type,
                    account_subtype=subtype,
                    normal_balance=normal,
                    currency_id=currency.id,
                    is_active=True,
                    is_system_generated=True,
                    source_metadata_json={"seed_version": NORMALIZATION_VERSION},
                )
                session.add(account)
                session.flush()
            accounts[code] = account
        for code, name, category_type, account_code in CATEGORY_SPECS:
            if (
                session.scalar(
                    select(TransactionCategory).where(
                        TransactionCategory.tenant_id == tenant.id, TransactionCategory.code == code
                    )
                )
                is None
            ):
                session.add(
                    TransactionCategory(
                        tenant_id=tenant.id,
                        code=code,
                        name=name,
                        category_type=category_type,
                        financial_account_id=accounts[account_code].id,
                        is_system_category=True,
                    )
                )
        for source_system in session.scalars(
            select(SourceSystem).where(SourceSystem.tenant_id == tenant.id)
        ).all():
            for source_code, name, financial_code, account_type in (
                ("primary_operating", "Primary Operating Checking", "1000", "checking"),
                ("secondary_payroll", "Secondary Payroll Checking", "1010", "payroll"),
            ):
                if (
                    session.scalar(
                        select(BankAccount).where(
                            BankAccount.tenant_id == tenant.id,
                            BankAccount.source_system_id == source_system.id,
                            BankAccount.source_account_code == source_code,
                        )
                    )
                    is None
                ):
                    session.add(
                        BankAccount(
                            tenant_id=tenant.id,
                            financial_account_id=accounts[financial_code].id,
                            source_system_id=source_system.id,
                            source_account_code=source_code,
                            account_name=name,
                            institution_name="Source-mapped institution",
                            masked_account_number="•••• synthetic",
                            account_type=account_type,
                            currency_id=currency.id,
                            status="active",
                        )
                    )
            if (
                session.scalar(
                    select(CreditAccount).where(
                        CreditAccount.tenant_id == tenant.id,
                        CreditAccount.source_system_id == source_system.id,
                        CreditAccount.source_account_code == "business_credit_card",
                    )
                )
                is None
            ):
                session.add(
                    CreditAccount(
                        tenant_id=tenant.id,
                        financial_account_id=accounts["2000"].id,
                        source_system_id=source_system.id,
                        source_account_code="business_credit_card",
                        account_name="Business Credit Card",
                        issuer_name="Source-mapped issuer",
                        masked_account_number="•••• synthetic",
                        currency_id=currency.id,
                        status="active",
                    )
                )
        for spec in MAPPING_SPECS:
            if (
                session.scalar(
                    select(NormalizationMapping).where(
                        NormalizationMapping.tenant_id == tenant.id,
                        NormalizationMapping.code == spec["code"],
                        NormalizationMapping.version == NORMALIZATION_VERSION,
                    )
                )
                is None
            ):
                config = {
                    key: value
                    for key, value in spec.items()
                    if key not in {"code", "name", "source", "target"}
                }
                session.add(
                    NormalizationMapping(
                        tenant_id=tenant.id,
                        code=str(spec["code"]),
                        name=str(spec["name"]),
                        version=NORMALIZATION_VERSION,
                        source_record_type=str(spec["source"]),
                        target_record_type=str(spec["target"]),
                        configuration_json=config,
                        is_active=True,
                    )
                )
                mapping_count += 1
    session.commit()
    return {
        "currencies": len(currencies),
        "mapping_specs": len(MAPPING_SPECS),
        "mappings_created": mapping_count,
    }
