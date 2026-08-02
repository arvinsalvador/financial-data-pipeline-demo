from __future__ import annotations

import csv
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BankAccount,
    BankLedgerReconciliationRun,
    BankTransaction,
    FinancialAccount,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedSourceFile,
    InvoiceCollectionsReconciliationRule,
    InvoiceCollectionsReconciliationRun,
    PayrollEntry,
    PayrollReconciliationRule,
    PayrollReconciliationRun,
    PayrollRun,
    PipelineDefinition,
    ReconciliationRule,
    ValidationRun,
)
from app.services.reconciliation_matching import stable_fingerprint

VALIDATION_STATUSES = ("completed", "completed_with_issues")
INVOICE_FILES = {
    "customers",
    "crm_deals",
    "invoices",
    "invoice_lines",
    "customer_payments",
    "customer_payment_applications",
    "general_ledger",
}


class ReconciliationDatasetResolver:
    """Resolve the latest module-compatible generated dataset and validation."""

    def __init__(self, settings: Settings) -> None:
        self.data_root = settings.GENERATED_DATA_DIRECTORY.parent

    def resolve(
        self, session: Session, tenant_id: int, module: str
    ) -> tuple[GeneratedDatasetRun | None, ValidationRun | None, dict[str, GeneratedSourceFile]]:
        fallback: tuple[GeneratedDatasetRun, None, dict[str, GeneratedSourceFile]] | None = None
        for generated in session.scalars(
            select(GeneratedDatasetRun)
            .where(
                GeneratedDatasetRun.tenant_id == tenant_id,
                GeneratedDatasetRun.status == "completed",
            )
            .order_by(GeneratedDatasetRun.id.desc())
        ):
            files = {
                item.file_type: item
                for item in session.scalars(
                    select(GeneratedSourceFile).where(
                        GeneratedSourceFile.generated_dataset_run_id == generated.id
                    )
                )
            }
            required = INVOICE_FILES if module == "invoice_collections" else {"general_ledger"}
            if not required.issubset(files):
                continue
            if module == "payroll" and generated.source_payroll_run_count <= 0:
                continue
            validation = session.scalar(
                select(ValidationRun)
                .where(
                    ValidationRun.tenant_id == tenant_id,
                    ValidationRun.generated_dataset_run_id == generated.id,
                    ValidationRun.target_type == "generated_dataset",
                    ValidationRun.status.in_(VALIDATION_STATUSES),
                    ValidationRun.critical_count == 0,
                )
                .order_by(ValidationRun.id.desc())
            )
            if validation is not None:
                return generated, validation, files
            if fallback is None:
                fallback = (generated, None, files)
        return fallback or (None, None, {})

    def rows(self, source: GeneratedSourceFile | None) -> list[dict[str, str]]:
        if source is None:
            return []
        path = self.data_root / source.relative_path
        if not path.is_file():
            return []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))


class ReconciliationValidationGate:
    @staticmethod
    def diagnostics(
        generated: GeneratedDatasetRun | None, validation: ValidationRun | None
    ) -> tuple[list[str], list[str]]:
        missing: list[str] = []
        blocking: list[str] = []
        if generated is None:
            missing.append("No completed module-compatible generated dataset exists.")
        elif validation is None:
            missing.append(
                f"Generated dataset #{generated.id} must complete generated-dataset validation."
            )
        elif validation.critical_count:
            blocking.append(
                f"Validation run #{validation.id} has {validation.critical_count} critical issues."
            )
        return missing, blocking


class ReconciliationAccountMappingService:
    @staticmethod
    def accounts(
        session: Session, tenant_id: int, account_type: str | None = None
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                BankAccount,
                FinancialAccount,
                func.count(BankTransaction.id),
                func.min(FinancialTransaction.transaction_date),
                func.max(FinancialTransaction.transaction_date),
            )
            .join(FinancialAccount, FinancialAccount.id == BankAccount.financial_account_id)
            .join(BankTransaction, BankTransaction.bank_account_id == BankAccount.id)
            .join(
                FinancialTransaction,
                FinancialTransaction.id == BankTransaction.financial_transaction_id,
            )
            .where(
                BankAccount.tenant_id == tenant_id,
                BankAccount.status == "active",
                FinancialTransaction.status == "active",
            )
            .group_by(BankAccount.id, FinancialAccount.id)
            .order_by(BankAccount.id)
        )
        if account_type is not None:
            statement = statement.where(BankAccount.account_type == account_type)
        return [
            {
                "id": account.id,
                "account_name": account.account_name,
                "source_account_code": account.source_account_code,
                "account_type": account.account_type,
                "financial_account_code": financial.account_code,
                "financial_account_name": financial.account_name,
                "transaction_count": count,
                "date_min": date_min,
                "date_max": date_max,
            }
            for account, financial, count, date_min, date_max in session.execute(statement)
        ]


class ReconciliationRunEligibilityService:
    module = ""
    pipeline_code = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.datasets = ReconciliationDatasetResolver(settings)

    def base(self, session: Session, tenant_id: int) -> dict[str, Any]:
        generated, validation, files = self.datasets.resolve(session, tenant_id, self.module)
        missing, blocking = ReconciliationValidationGate.diagnostics(generated, validation)
        if (
            session.scalar(
                select(PipelineDefinition.id).where(
                    PipelineDefinition.code == self.pipeline_code,
                    PipelineDefinition.is_active.is_(True),
                )
            )
            is None
        ):
            missing.append(f"Pipeline definition {self.pipeline_code} is not active.")
        return {
            "tenant_id": tenant_id,
            "generated_dataset_run_id": generated.id if generated else None,
            "validation_run_id": validation.id if validation else None,
            "generated": generated,
            "validation": validation,
            "files": files,
            "missing_prerequisites": missing,
            "blocking_conditions": blocking,
            "warnings": [],
        }

    @staticmethod
    def finish(result: dict[str, Any], fingerprint_payload: dict[str, Any]) -> dict[str, Any]:
        result["eligible"] = (
            not result["missing_prerequisites"] and not result["blocking_conditions"]
        )
        result["input_fingerprint"] = stable_fingerprint(fingerprint_payload)
        result.pop("generated", None)
        result.pop("validation", None)
        result.pop("files", None)
        return result


class BankReconciliationEligibilityService(ReconciliationRunEligibilityService):
    module = "bank_ledger"
    pipeline_code = "bank_ledger_reconciliation"

    def evaluate(self, session: Session, tenant_id: int) -> dict[str, Any]:
        result = self.base(session, tenant_id)
        accounts = ReconciliationAccountMappingService.accounts(session, tenant_id)
        gl = self.datasets.rows(result["files"].get("general_ledger"))
        eligible_accounts = []
        for account in accounts:
            gl_rows = [
                row for row in gl if row.get("account_code") == account["financial_account_code"]
            ]
            eligible_accounts.append(
                {
                    **account,
                    "eligible_bank_transaction_count": account["transaction_count"],
                    "eligible_gl_line_count": len(gl_rows),
                    "total_gl_cash_amount": str(
                        sum(
                            (
                                float(row.get("debit") or 0) - float(row.get("credit") or 0)
                                for row in gl_rows
                            ),
                            0.0,
                        )
                    ),
                }
            )
        if not eligible_accounts:
            result["missing_prerequisites"].append(
                "No active bank account has canonical bank transactions and a stable GL mapping."
            )
        elif not any(item["eligible_gl_line_count"] for item in eligible_accounts):
            result["blocking_conditions"].append(
                "Generated general ledger has no cash lines for mapped bank accounts."
            )
        rules = (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationRule)
                .where(
                    ReconciliationRule.tenant_id == tenant_id,
                    ReconciliationRule.is_active.is_(True),
                )
            )
            or 0
        )
        if rules == 0:
            result["missing_prerequisites"].append("Bank reconciliation rules are not seeded.")
        existing = session.scalar(
            select(BankLedgerReconciliationRun.id)
            .where(BankLedgerReconciliationRun.tenant_id == tenant_id)
            .order_by(BankLedgerReconciliationRun.id.desc())
        )
        dates = [item["date_min"] for item in eligible_accounts if item["date_min"]]
        ends = [item["date_max"] for item in eligible_accounts if item["date_max"]]
        result.update(
            {
                "date_min": min(dates) if dates else None,
                "date_max": max(ends) if ends else None,
                "eligible_record_counts": {
                    "bank_transactions": sum(item["transaction_count"] for item in accounts),
                    "gl_cash_lines": sum(
                        item["eligible_gl_line_count"] for item in eligible_accounts
                    ),
                },
                "eligible_accounts": eligible_accounts,
                "existing_run_id": existing,
                "validation_required": True,
                "generated_gl_strategy": "generated_general_ledger_csv_adapter",
            }
        )
        return self.finish(
            result,
            {
                "module": self.module,
                "dataset": result["generated_dataset_run_id"],
                "validation": result["validation_run_id"],
                "accounts": eligible_accounts,
            },
        )


class PayrollReconciliationEligibilityService(ReconciliationRunEligibilityService):
    module = "payroll"
    pipeline_code = "payroll_reconciliation"

    def evaluate(self, session: Session, tenant_id: int) -> dict[str, Any]:
        result = self.base(session, tenant_id)
        accounts = ReconciliationAccountMappingService.accounts(session, tenant_id, "payroll")
        payroll_runs = list(
            session.scalars(
                select(PayrollRun).where(
                    PayrollRun.tenant_id == tenant_id, PayrollRun.status == "normalized"
                )
            )
        )
        entries = (
            session.scalar(
                select(func.count())
                .select_from(PayrollEntry)
                .where(PayrollEntry.tenant_id == tenant_id, PayrollEntry.status == "active")
            )
            or 0
        )
        gl = [
            row
            for row in self.datasets.rows(result["files"].get("general_ledger"))
            if row.get("source_type") == "payroll_run"
        ]
        if not accounts:
            result["missing_prerequisites"].append(
                "No transaction-bearing payroll bank account is mapped."
            )
        if not payroll_runs:
            result["missing_prerequisites"].append("No normalized payroll runs exist.")
        if not gl:
            result["blocking_conditions"].append("Generated ledger has no payroll GL lines.")
        rules = (
            session.scalar(
                select(func.count())
                .select_from(PayrollReconciliationRule)
                .where(
                    PayrollReconciliationRule.tenant_id == tenant_id,
                    PayrollReconciliationRule.is_active.is_(True),
                )
            )
            or 0
        )
        if rules == 0:
            result["missing_prerequisites"].append("Payroll reconciliation rules are not seeded.")
        existing = session.scalar(
            select(PayrollReconciliationRun.id)
            .where(PayrollReconciliationRun.tenant_id == tenant_id)
            .order_by(PayrollReconciliationRun.id.desc())
        )
        result.update(
            {
                "date_min": min((item.pay_date for item in payroll_runs), default=None),
                "date_max": max((item.pay_date for item in payroll_runs), default=None),
                "eligible_record_counts": {
                    "payroll_runs": len(payroll_runs),
                    "payroll_entries": entries,
                    "bank_withdrawals": sum(item["transaction_count"] for item in accounts),
                    "gl_payroll_lines": len(gl),
                },
                "eligible_accounts": accounts,
                "supported_settlement_models": [
                    "net_pay_only",
                    "net_pay_plus_taxes",
                    "full_payroll_cash_requirement",
                    "split_withdrawals",
                    "configured_components",
                ],
                "existing_run_id": existing,
                "validation_required": True,
                "generated_gl_strategy": "generated_general_ledger_csv_adapter",
            }
        )
        return self.finish(
            result,
            {
                "module": self.module,
                "dataset": result["generated_dataset_run_id"],
                "validation": result["validation_run_id"],
                "counts": result["eligible_record_counts"],
            },
        )


class InvoiceCollectionsEligibilityService(ReconciliationRunEligibilityService):
    module = "invoice_collections"
    pipeline_code = "invoice_collections_reconciliation"

    def evaluate(self, session: Session, tenant_id: int) -> dict[str, Any]:
        result = self.base(session, tenant_id)
        accounts = [
            item
            for item in ReconciliationAccountMappingService.accounts(session, tenant_id)
            if item["account_type"] != "payroll"
        ]
        files = result["files"]
        counts = {
            key: files[key].record_count if key in files else 0
            for key in (
                "customers",
                "crm_deals",
                "invoices",
                "invoice_lines",
                "customer_payments",
                "customer_payment_applications",
            )
        }
        gl = self.datasets.rows(files.get("general_ledger"))
        counts["gl_ar_lines"] = sum(row.get("account_code") == "1100" for row in gl)
        counts["gl_cash_lines"] = sum(row.get("account_code") == "1000" for row in gl)
        counts["bank_deposits"] = sum(item["transaction_count"] for item in accounts)
        if not accounts:
            result["missing_prerequisites"].append(
                "No transaction-bearing operating bank account is mapped."
            )
        if counts["invoices"] == 0:
            result["missing_prerequisites"].append("Generated data has no invoices.")
        if counts["gl_ar_lines"] == 0 or counts["gl_cash_lines"] == 0:
            result["blocking_conditions"].append(
                "Generated ledger is missing mapped accounts-receivable or cash lines."
            )
        rules = (
            session.scalar(
                select(func.count())
                .select_from(InvoiceCollectionsReconciliationRule)
                .where(
                    InvoiceCollectionsReconciliationRule.tenant_id == tenant_id,
                    InvoiceCollectionsReconciliationRule.is_active.is_(True),
                )
            )
            or 0
        )
        if rules == 0:
            result["missing_prerequisites"].append(
                "Invoice collections reconciliation rules are not seeded."
            )
        existing = session.scalar(
            select(InvoiceCollectionsReconciliationRun.id)
            .where(InvoiceCollectionsReconciliationRun.tenant_id == tenant_id)
            .order_by(InvoiceCollectionsReconciliationRun.id.desc())
        )
        generated = result["generated"]
        result.update(
            {
                "date_min": generated.base_date_start if generated else None,
                "date_max": generated.base_date_end if generated else None,
                "eligible_record_counts": counts,
                "eligible_accounts": accounts,
                "aging_date_options": {
                    "min": generated.base_date_start if generated else None,
                    "max": generated.base_date_end if generated else None,
                },
                "existing_run_id": existing,
                "validation_required": True,
                "generated_gl_strategy": "generated_general_ledger_csv_adapter",
            }
        )
        return self.finish(
            result,
            {
                "module": self.module,
                "dataset": result["generated_dataset_run_id"],
                "validation": result["validation_run_id"],
                "counts": counts,
            },
        )
