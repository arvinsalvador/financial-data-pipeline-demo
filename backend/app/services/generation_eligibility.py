import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    BankAccount,
    BankTransaction,
    CanonicalRecordLineage,
    CreditAccount,
    CreditCardTransaction,
    FinancialAccount,
    FinancialTransaction,
    GeneratedDatasetRun,
    NormalizationControlTotal,
    NormalizationException,
    PayrollEntry,
    PayrollRun,
    PipelineRun,
)
from app.schemas.generation import CanonicalGenerationCounts, GenerationEligibilityResponse

ELIGIBLE_NORMALIZATION_STATUSES = frozenset(
    {"completed", "completed_with_exceptions", "completed_with_warnings"}
)


@dataclass(frozen=True)
class GenerationInput:
    normalization_run: PipelineRun
    bank: list[Any]
    cards: list[Any]
    payroll: list[PayrollRun]


class GeneratedDataEligibilityService:
    """Resolve a tenant-scoped canonical snapshot anchored to a normalization run."""

    def candidates(self, session: Session, tenant_id: int) -> list[GenerationEligibilityResponse]:
        runs = session.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.run_type == "canonical_normalization",
            )
            .order_by(PipelineRun.completed_at.desc().nullslast(), PipelineRun.id.desc())
        ).all()
        return [self.evaluate(session, tenant_id, run.id) for run in runs]

    def latest_eligible(
        self, session: Session, tenant_id: int
    ) -> GenerationEligibilityResponse | None:
        return next((item for item in self.candidates(session, tenant_id) if item.eligible), None)

    def resolve_input(
        self, session: Session, tenant_id: int, normalization_run_id: int
    ) -> GenerationInput:
        run = session.scalar(
            select(PipelineRun).where(
                PipelineRun.id == normalization_run_id,
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.run_type == "canonical_normalization",
            )
        )
        if run is None:
            raise ValueError("Normalization run not found")
        bank = list(
            session.execute(
                select(FinancialTransaction, BankTransaction, BankAccount)
                .join(
                    BankTransaction,
                    BankTransaction.financial_transaction_id == FinancialTransaction.id,
                )
                .join(BankAccount, BankAccount.id == BankTransaction.bank_account_id)
                .where(
                    FinancialTransaction.tenant_id == tenant_id,
                    FinancialTransaction.normalization_run_id <= normalization_run_id,
                )
                .order_by(FinancialTransaction.transaction_date, FinancialTransaction.id)
            ).all()
        )
        cards = list(
            session.execute(
                select(FinancialTransaction, CreditCardTransaction, CreditAccount)
                .join(
                    CreditCardTransaction,
                    CreditCardTransaction.financial_transaction_id == FinancialTransaction.id,
                )
                .join(CreditAccount, CreditAccount.id == CreditCardTransaction.credit_account_id)
                .where(
                    FinancialTransaction.tenant_id == tenant_id,
                    FinancialTransaction.normalization_run_id <= normalization_run_id,
                )
                .order_by(FinancialTransaction.transaction_date, FinancialTransaction.id)
            ).all()
        )
        payroll = list(
            session.scalars(
                select(PayrollRun)
                .where(
                    PayrollRun.tenant_id == tenant_id,
                    PayrollRun.pipeline_run_id <= normalization_run_id,
                )
                .order_by(PayrollRun.pay_date, PayrollRun.id)
            ).all()
        )
        return GenerationInput(run, bank, cards, payroll)

    def evaluate(
        self, session: Session, tenant_id: int, normalization_run_id: int
    ) -> GenerationEligibilityResponse:
        resolved = self.resolve_input(session, tenant_id, normalization_run_id)
        run, bank, cards, payroll = (
            resolved.normalization_run,
            resolved.bank,
            resolved.cards,
            resolved.payroll,
        )
        payroll_ids = [item.id for item in payroll]
        payroll_entry_count = (
            session.scalar(
                select(func.count())
                .select_from(PayrollEntry)
                .where(
                    PayrollEntry.tenant_id == tenant_id,
                    PayrollEntry.payroll_run_id.in_(payroll_ids),
                )
            )
            if payroll_ids
            else 0
        ) or 0
        employee_count = (
            session.scalar(
                select(func.count(distinct(PayrollEntry.employee_id))).where(
                    PayrollEntry.tenant_id == tenant_id,
                    PayrollEntry.payroll_run_id.in_(payroll_ids),
                )
            )
            if payroll_ids
            else 0
        ) or 0
        lineage_count = (
            session.scalar(
                select(func.count())
                .select_from(CanonicalRecordLineage)
                .where(
                    CanonicalRecordLineage.tenant_id == tenant_id,
                    CanonicalRecordLineage.pipeline_run_id <= normalization_run_id,
                )
            )
            or 0
        )
        account_count = (
            session.scalar(
                select(func.count())
                .select_from(FinancialAccount)
                .where(
                    FinancialAccount.tenant_id == tenant_id, FinancialAccount.is_active.is_(True)
                )
            )
            or 0
        )
        source_file_ids = {item[0].source_file_id for item in bank + cards}
        source_file_ids.update(item.source_file_id for item in payroll)
        counts = CanonicalGenerationCounts(
            financial_accounts=account_count,
            bank_transactions=len(bank),
            credit_card_transactions=len(cards),
            employees=employee_count,
            payroll_runs=len(payroll),
            payroll_entries=payroll_entry_count,
            lineage=lineage_count,
        )
        missing: list[str] = []
        blocking: list[str] = []
        warnings: list[str] = []
        if run.status not in ELIGIBLE_NORMALIZATION_STATUSES:
            blocking.append(f"Normalization status is {run.status}, not completed")
        if not bank and not cards and not payroll:
            missing.append("No canonical bank, credit-card, or payroll records found")
        if not bank:
            missing.append("No canonical bank transactions found")
        elif not any(item[0].amount > 0 for item in bank):
            missing.append("No canonical bank inflow found for customer and invoice generation")
        if not account_count:
            missing.append("No active canonical financial accounts found")
        if not lineage_count:
            missing.append("No canonical lineage found")
        if not cards:
            warnings.append("No canonical credit-card transactions; card-derived AP is omitted")
        if not payroll:
            warnings.append("No canonical payroll runs; payroll-derived ledger records are omitted")
        elif not payroll_entry_count:
            warnings.append("No canonical payroll entries; payroll detail links are omitted")
        mismatches = session.scalars(
            select(NormalizationControlTotal).where(
                NormalizationControlTotal.pipeline_run_id == normalization_run_id,
                NormalizationControlTotal.status.not_in(("matched", "passed")),
            )
        ).all()
        blocking.extend(f"Normalization control failed: {item.control_name}" for item in mismatches)
        critical = session.scalars(
            select(NormalizationException).where(
                NormalizationException.pipeline_run_id == normalization_run_id,
                NormalizationException.severity == "critical",
                NormalizationException.status.in_(("open", "new")),
            )
        ).all()
        blocking.extend(
            f"Critical normalization exception: {item.exception_code}" for item in critical
        )
        hashes = {
            "normalization_run_id": normalization_run_id,
            "bank": [item[0].canonical_hash for item in bank],
            "cards": [item[0].canonical_hash for item in cards],
            "payroll": [item.canonical_hash for item in payroll],
        }
        input_fingerprint = hashlib.sha256(
            (json.dumps(hashes, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()
        generated = session.scalar(
            select(GeneratedDatasetRun)
            .where(
                GeneratedDatasetRun.tenant_id == tenant_id,
                GeneratedDatasetRun.normalization_run_id == normalization_run_id,
                GeneratedDatasetRun.status == "completed",
            )
            .order_by(GeneratedDatasetRun.id.desc())
        )
        return GenerationEligibilityResponse(
            normalization_run_id=normalization_run_id,
            tenant_id=tenant_id,
            status=run.status,
            completed_at=run.completed_at,
            source_file_count=len(source_file_ids),
            eligible=not missing and not blocking,
            canonical_counts=counts,
            missing_prerequisites=missing,
            blocking_conditions=blocking,
            warnings=warnings,
            already_generated_run_id=generated.id if generated else None,
            can_force_rerun=False,
            input_fingerprint=input_fingerprint,
        )
