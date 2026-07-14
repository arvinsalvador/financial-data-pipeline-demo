import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BankAccount,
    BankTransaction,
    CanonicalRecordLineage,
    Counterparty,
    CreditAccount,
    CreditCardTransaction,
    Currency,
    Employee,
    FinancialTransaction,
    NormalizationControlTotal,
    NormalizationException,
    NormalizationMapping,
    PayrollEntry,
    PayrollRun,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    StagingBankTransaction,
    StagingCreditCardTransaction,
    StagingPayrollDetail,
    StagingPayrollSummary,
    Tenant,
    TransactionCategory,
    Vendor,
)

NORMALIZATION_STEPS = (
    "validate_tenant_and_permissions",
    "load_ingestion_run",
    "validate_staging_integrity",
    "load_normalization_mapping",
    "resolve_master_data",
    "normalize_bank_transactions",
    "normalize_credit_card_transactions",
    "normalize_payroll_runs",
    "normalize_payroll_entries",
    "create_lineage_records",
    "calculate_control_totals",
    "create_normalization_exceptions",
    "validate_invariants",
    "register_artifacts",
    "finalize_normalization",
)
STAGING_MODELS: dict[str, type[Any]] = {
    "staging_bank_transaction": StagingBankTransaction,
    "staging_credit_card_transaction": StagingCreditCardTransaction,
    "staging_payroll_summary": StagingPayrollSummary,
    "staging_payroll_detail": StagingPayrollDetail,
}


class NormalizationError(Exception):
    def __init__(self, message: str, *, run_id: int | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True)
class NormalizationResult:
    run: PipelineRun
    mapping: NormalizationMapping
    no_op: bool = False


def normalize_name(value: str) -> str:
    value = re.sub(r"[^\w\s-]", " ", value.casefold())
    return " ".join(value.split())


def stable_hash(*values: object) -> str:
    return hashlib.sha256(
        json.dumps(values, default=str, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class CanonicalNormalizationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def normalize(
        self,
        session: Session,
        ingestion_run_id: int,
        tenant_id: int,
        mapping_code: str | None = None,
        *,
        force_rerun: bool = False,
    ) -> NormalizationResult:
        ingestion = session.scalar(
            select(PipelineRun).where(
                PipelineRun.id == ingestion_run_id,
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.run_type == "csv_ingestion",
            )
        )
        if ingestion is None:
            raise NormalizationError("Ingestion run not found")
        if ingestion.status not in {"completed", "completed_with_rejections"}:
            raise NormalizationError("Only completed ingestion runs can be normalized")
        mapping = self._mapping(session, tenant_id, ingestion, mapping_code)
        prior = session.scalar(
            select(PipelineRun)
            .where(
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.run_type == "canonical_normalization",
                PipelineRun.status.in_(("completed", "completed_with_exceptions")),
            )
            .order_by(PipelineRun.id.desc())
        )
        if (
            prior
            and (prior.metadata_json or {}).get("ingestion_run_id") == ingestion.id
            and (prior.metadata_json or {}).get("mapping_code") == mapping.code
            and (prior.metadata_json or {}).get("normalization_version")
            == self.settings.NORMALIZATION_VERSION
        ):
            return NormalizationResult(prior, mapping, True)
        run = self._start(session, ingestion, mapping, force_rerun)
        try:
            model = STAGING_MODELS[mapping.source_record_type]
            rows = list(
                session.scalars(
                    select(model)
                    .where(model.tenant_id == tenant_id, model.pipeline_run_id == ingestion.id)
                    .order_by(model.id)
                ).all()
            )
            if len(rows) != ingestion.records_accepted:
                raise NormalizationError(
                    "Staging integrity count does not match accepted ingestion rows", run_id=run.id
                )
            self._complete(run, 1, {"tenant_id": tenant_id})
            self._complete(run, 2, {"ingestion_run_id": ingestion.id})
            self._complete(run, 3, {"staging_count": len(rows)})
            self._complete(
                run, 4, {"mapping_code": mapping.code, "mapping_version": mapping.version}
            )
            self._complete(
                run,
                5,
                {"resolution": "seeded account/category and deterministic exact master data"},
            )
            staging_total = canonical_total = Decimal(0)
            normalized = exception_rows = lineage_count = 0
            for row in rows:
                try:
                    if isinstance(row, StagingBankTransaction):
                        source, canonical, lineage = self._bank(
                            session, run, ingestion, mapping, row
                        )
                    elif isinstance(row, StagingCreditCardTransaction):
                        source, canonical, lineage = self._card(
                            session, run, ingestion, mapping, row
                        )
                    else:
                        source, canonical, lineage = self._payroll(
                            session, run, ingestion, mapping, row
                        )
                    staging_total += source
                    canonical_total += canonical
                    normalized += 1
                    lineage_count += lineage
                except NormalizationError as error:
                    exception_rows += 1
                    self._exception(
                        session,
                        run,
                        ingestion,
                        mapping.source_record_type,
                        row.id,
                        "canonical_validation",
                        "canonical_validation",
                        "error",
                        str(error),
                    )
            self._complete(
                run,
                6,
                {"count": normalized if mapping.target_record_type == "bank_transaction" else 0},
            )
            self._complete(
                run,
                7,
                {
                    "count": normalized
                    if mapping.target_record_type == "credit_card_transaction"
                    else 0
                },
            )
            self._complete(
                run,
                8,
                {
                    "source": mapping.source_record_type,
                    "groups_resolved": normalized if "payroll" in mapping.source_record_type else 0,
                },
            )
            self._complete(
                run, 9, {"count": normalized if "payroll" in mapping.source_record_type else 0}
            )
            self._complete(run, 10, {"lineage_records": lineage_count})
            controls = self._controls(
                session, run, ingestion, len(rows), normalized, staging_total, canonical_total
            )
            self._complete(run, 11, {"control_count": len(controls)})
            exceptions = (
                session.scalar(
                    select(func.count())
                    .select_from(NormalizationException)
                    .where(NormalizationException.pipeline_run_id == run.id)
                )
                or 0
            )
            self._complete(run, 12, {"exception_count": exceptions})
            mismatches = sum(item.status == "mismatch" for item in controls)
            if normalized + exception_rows != len(rows):
                raise NormalizationError("Normalization count invariant failed", run_id=run.id)
            self._complete(
                run,
                13,
                {
                    "staging_equals_normalized_plus_exceptions": True,
                    "control_mismatches": mismatches,
                },
            )
            run.records_extracted, run.records_accepted, run.records_rejected = (
                len(rows),
                normalized,
                exception_rows,
            )
            self._artifacts(session, run, ingestion, mapping, controls, exceptions)
            self._complete(run, 14, {"artifact_count": 4})
            run.status = "completed_with_exceptions" if exceptions or mismatches else "completed"
            run.completed_at = datetime.now(UTC)
            self._complete(run, 15, {"status": run.status})
            session.commit()
            return NormalizationResult(run, mapping)
        except Exception as error:
            session.rollback()
            persisted = session.get(PipelineRun, run.id)
            if persisted:
                persisted.status = "failed"
                persisted.completed_at = datetime.now(UTC)
                persisted.error_message = str(error)[:2000]
                step = next(
                    (item for item in persisted.steps if item.status in {"running", "pending"}),
                    None,
                )
                if step:
                    step.status, step.completed_at, step.error_message = (
                        "failed",
                        datetime.now(UTC),
                        str(error)[:2000],
                    )
                session.commit()
            if isinstance(error, NormalizationError):
                error.run_id = run.id
                raise
            raise NormalizationError(str(error), run_id=run.id) from error

    def _mapping(
        self, session: Session, tenant_id: int, ingestion: PipelineRun, code: str | None
    ) -> NormalizationMapping:
        query = select(NormalizationMapping).where(
            NormalizationMapping.tenant_id == tenant_id, NormalizationMapping.is_active.is_(True)
        )
        if code:
            query = query.where(NormalizationMapping.code == code)
        candidates = [
            item
            for item in session.scalars(query).all()
            if item.configuration_json.get("ingestion_mapping")
            == (ingestion.metadata_json or {}).get("mapping_code")
        ]
        if len(candidates) != 1:
            raise NormalizationError(
                "Exactly one active normalization mapping must match the ingestion"
            )
        return candidates[0]

    def _start(
        self, session: Session, ingestion: PipelineRun, mapping: NormalizationMapping, force: bool
    ) -> PipelineRun:
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "canonical_normalization",
                PipelineDefinition.version == self.settings.NORMALIZATION_VERSION,
                PipelineDefinition.is_active.is_(True),
            )
        )
        if definition is None:
            raise NormalizationError("Canonical normalization pipeline definition is not active")
        now = datetime.now(UTC)
        run = PipelineRun(
            tenant_id=ingestion.tenant_id,
            pipeline_definition_id=definition.id,
            run_type="canonical_normalization",
            status="running",
            started_at=now,
            source_file_id=ingestion.source_file_id,
            metadata_json={
                "ingestion_run_id": ingestion.id,
                "normalization_version": self.settings.NORMALIZATION_VERSION,
                "mapping_code": mapping.code,
                "mapping_version": mapping.version,
                "force_rerun": force,
            },
        )
        for order, name in enumerate(NORMALIZATION_STEPS, 1):
            run.steps.append(
                PipelineRunStep(
                    step_name=name,
                    step_order=order,
                    status="running" if order == 1 else "pending",
                    started_at=now,
                    metadata_json={},
                )
            )
        session.add(run)
        session.commit()
        return run

    def _complete(self, run: PipelineRun, order: int, metadata: dict[str, Any]) -> None:
        step = run.steps[order - 1]
        step.status, step.completed_at, step.metadata_json = (
            "completed",
            datetime.now(UTC),
            metadata,
        )
        if order < len(run.steps):
            run.steps[order].status = "running"

    def _currency(
        self, session: Session, tenant_id: int, source: str | None, mapping: NormalizationMapping
    ) -> tuple[Currency, str]:
        tenant = session.get(Tenant, tenant_id)
        assert tenant is not None
        if source:
            supplied = session.scalar(
                select(Currency).where(
                    Currency.code == source.upper(), Currency.is_active.is_(True)
                )
            )
            if supplied is None:
                raise NormalizationError(f"Source currency is invalid: {source[:10]}")
            return supplied, "source"
        candidates = (
            (str(mapping.configuration_json.get("default_currency", "")), "mapping_default"),
            (tenant.default_currency, "tenant_default"),
        )
        for code, resolution in candidates:
            if code:
                currency = session.scalar(
                    select(Currency).where(
                        Currency.code == code.upper(), Currency.is_active.is_(True)
                    )
                )
                if currency:
                    return currency, resolution
        raise NormalizationError("No valid canonical currency could be resolved")

    def _category(
        self,
        session: Session,
        tenant_id: int,
        raw: str | None,
        description: str | None,
        amount: Decimal,
        *,
        card: bool = False,
    ) -> TransactionCategory:
        text = normalize_name(" ".join(value for value in (raw, description) if value))
        if card:
            code = "credit_card_purchase"
        elif "payroll tax" in text:
            code = "payroll_tax"
        elif "payroll" in text:
            code = "payroll"
        elif "fee" in text:
            code = "bank_fee"
        elif "transfer" in text:
            code = "transfer"
        else:
            code = "uncategorized_income" if amount > 0 else "uncategorized_expense"
        category = session.scalar(
            select(TransactionCategory).where(
                TransactionCategory.tenant_id == tenant_id, TransactionCategory.code == code
            )
        )
        if category is None:
            raise NormalizationError(f"Canonical category is missing: {code}")
        return category

    def _counterparty(
        self,
        session: Session,
        tenant_id: int,
        raw: str | None,
        kind: str,
        external: str | None = None,
    ) -> Counterparty | None:
        if not raw:
            return None
        normalized = normalize_name(raw)
        matches = list(
            session.scalars(
                select(Counterparty).where(
                    Counterparty.tenant_id == tenant_id,
                    Counterparty.counterparty_type == kind,
                    Counterparty.normalized_name == normalized,
                )
            ).all()
        )
        if len(matches) > 1:
            raise NormalizationError("Counterparty resolution is ambiguous")
        if matches:
            return matches[0]
        item = Counterparty(
            tenant_id=tenant_id,
            counterparty_type=kind,
            canonical_name=raw.strip(),
            normalized_name=normalized,
            external_reference=external,
            status="active",
            metadata_json={"resolution": "exact_normalized_or_created"},
        )
        session.add(item)
        session.flush()
        if kind == "vendor":
            session.add(
                Vendor(
                    tenant_id=tenant_id,
                    counterparty_id=item.id,
                    vendor_code=f"V-{item.id:06d}",
                    display_name=item.canonical_name,
                    status="active",
                )
            )
        return item

    @staticmethod
    def _bank_amount(row: StagingBankTransaction) -> Decimal:
        if row.amount is not None:
            return row.amount
        if row.debit_amount is not None or row.credit_amount is not None:
            return (row.credit_amount or Decimal(0)) - (row.debit_amount or Decimal(0))
        raise NormalizationError("Bank staging row has no authoritative amount")

    def _bank(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        mapping: NormalizationMapping,
        row: StagingBankTransaction,
    ) -> tuple[Decimal, Decimal, int]:
        account_code = str(mapping.configuration_json.get("account"))
        account = session.scalar(
            select(BankAccount).where(
                BankAccount.tenant_id == run.tenant_id,
                BankAccount.source_system_id == row.source_system_id,
                BankAccount.source_account_code == account_code,
                BankAccount.status == "active",
            )
        )
        if account is None:
            raise NormalizationError("Configured bank account mapping is missing")
        amount = self._bank_amount(row)
        currency, resolution = self._currency(session, run.tenant_id, row.currency, mapping)
        category = self._category(session, run.tenant_id, row.category_raw, row.description, amount)
        canonical_hash = stable_hash(
            "bank", row.id, row.row_hash, amount, self.settings.NORMALIZATION_VERSION
        )
        transaction = FinancialTransaction(
            tenant_id=run.tenant_id,
            transaction_type="bank",
            transaction_date=row.transaction_date,
            posted_date=row.posted_date,
            amount=amount,
            currency_id=currency.id,
            description=row.description,
            normalized_description=normalize_name(row.description or "") or None,
            reference_number=row.reference_number,
            category_id=category.id,
            source_system_id=row.source_system_id,
            source_file_id=row.source_file_id,
            pipeline_run_id=ingestion.id,
            normalization_run_id=run.id,
            source_record_id=row.source_record_id,
            source_row_number=row.source_row_number,
            normalization_version=self.settings.NORMALIZATION_VERSION,
            canonical_hash=canonical_hash,
            status="active",
            metadata_json={
                "currency_resolution": resolution,
                "category_resolution": "deterministic",
                "source_amount": str(amount),
            },
        )
        session.add(transaction)
        session.flush()
        child = BankTransaction(
            tenant_id=run.tenant_id,
            financial_transaction_id=transaction.id,
            bank_account_id=account.id,
            staging_bank_transaction_id=row.id,
            debit_amount=row.debit_amount,
            credit_amount=row.credit_amount,
            running_balance=row.running_balance,
            transaction_direction="inflow"
            if amount > 0
            else ("outflow" if amount < 0 else "neutral"),
            is_internal_transfer=category.code == "transfer",
            normalization_version=self.settings.NORMALIZATION_VERSION,
        )
        session.add(child)
        session.flush()
        self._lineage(
            session,
            run,
            ingestion,
            mapping,
            row,
            "bank_transaction",
            child.id,
            "staging_bank_transaction",
        )
        return amount, amount, 1

    def _card(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        mapping: NormalizationMapping,
        row: StagingCreditCardTransaction,
    ) -> tuple[Decimal, Decimal, int]:
        account = session.scalar(
            select(CreditAccount).where(
                CreditAccount.tenant_id == run.tenant_id,
                CreditAccount.source_system_id == row.source_system_id,
                CreditAccount.source_account_code == mapping.configuration_json.get("account"),
                CreditAccount.status == "active",
            )
        )
        if account is None:
            raise NormalizationError("Configured credit account mapping is missing")
        source = (
            row.amount
            if row.amount is not None
            else (row.credit_amount or Decimal(0)) - (row.debit_amount or Decimal(0))
        )
        description = row.description or ""
        if "payment" in normalize_name(description):
            direction, canonical, purchase, refund = "payment", -abs(source), None, None
        elif source < 0:
            direction, canonical, purchase, refund = "purchase", abs(source), abs(source), None
        elif source > 0:
            direction, canonical, purchase, refund = "refund", -abs(source), None, abs(source)
        else:
            direction, canonical, purchase, refund = "adjustment", Decimal(0), None, None
        currency, resolution = self._currency(session, run.tenant_id, row.currency, mapping)
        merchant = self._counterparty(session, run.tenant_id, row.merchant_raw, "vendor")
        category = self._category(
            session, run.tenant_id, row.category_raw, description, canonical, card=True
        )
        transaction = FinancialTransaction(
            tenant_id=run.tenant_id,
            transaction_type="credit_card",
            transaction_date=row.transaction_date,
            posted_date=row.posted_date,
            amount=canonical,
            currency_id=currency.id,
            description=row.description,
            normalized_description=normalize_name(description) or None,
            reference_number=row.reference_number,
            counterparty_id=merchant.id if merchant else None,
            category_id=category.id,
            source_system_id=row.source_system_id,
            source_file_id=row.source_file_id,
            pipeline_run_id=ingestion.id,
            normalization_run_id=run.id,
            source_record_id=row.source_record_id,
            source_row_number=row.source_row_number,
            normalization_version=self.settings.NORMALIZATION_VERSION,
            canonical_hash=stable_hash(
                "card", row.id, row.row_hash, canonical, self.settings.NORMALIZATION_VERSION
            ),
            status="active",
            metadata_json={
                "source_signed_amount": str(source),
                "currency_resolution": resolution,
                "sign_conversion": mapping.configuration_json.get("sign_rule"),
            },
        )
        session.add(transaction)
        session.flush()
        child = CreditCardTransaction(
            tenant_id=run.tenant_id,
            financial_transaction_id=transaction.id,
            credit_account_id=account.id,
            staging_credit_card_transaction_id=row.id,
            merchant_counterparty_id=merchant.id if merchant else None,
            purchase_amount=purchase,
            refund_amount=refund,
            transaction_direction=direction,
            normalization_version=self.settings.NORMALIZATION_VERSION,
        )
        session.add(child)
        session.flush()
        self._lineage(
            session,
            run,
            ingestion,
            mapping,
            row,
            "credit_card_transaction",
            child.id,
            "staging_credit_card_transaction",
        )
        return canonical, canonical, 1

    def _payroll(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        mapping: NormalizationMapping,
        row: StagingPayrollSummary | StagingPayrollDetail,
    ) -> tuple[Decimal, Decimal, int]:
        currency, resolution = self._currency(session, run.tenant_id, row.currency, mapping)
        key = (
            row.payroll_run_source_id
            or "derived:"
            f"{row.pay_period_start or 'unknown'}:"
            f"{row.pay_period_end or 'unknown'}:{row.pay_date}"
        )
        payroll_run = session.scalar(
            select(PayrollRun).where(
                PayrollRun.tenant_id == run.tenant_id,
                PayrollRun.source_system_id == row.source_system_id,
                PayrollRun.payroll_run_source_id == key,
                PayrollRun.normalization_version == self.settings.NORMALIZATION_VERSION,
            )
        )
        if payroll_run is None:
            payroll_run = PayrollRun(
                tenant_id=run.tenant_id,
                source_system_id=row.source_system_id,
                source_file_id=row.source_file_id,
                pipeline_run_id=run.id,
                payroll_run_source_id=key,
                pay_period_start=row.pay_period_start,
                pay_period_end=row.pay_period_end,
                pay_date=row.pay_date,
                currency_id=currency.id,
                status="normalized",
                gross_pay_total=None,
                employee_deductions_total=None,
                employer_contributions_total=None,
                reimbursement_total=None,
                net_pay_total=None,
                normalization_version=self.settings.NORMALIZATION_VERSION,
                canonical_hash=stable_hash(
                    "payroll_run",
                    run.tenant_id,
                    row.source_system_id,
                    key,
                    self.settings.NORMALIZATION_VERSION,
                ),
                metadata_json={
                    "key_derivation": "source_id"
                    if row.payroll_run_source_id
                    else "pay_period_and_pay_date",
                    "currency_resolution": resolution,
                },
            )
            session.add(payroll_run)
            session.flush()
        employee = session.scalar(
            select(Employee).where(
                Employee.tenant_id == run.tenant_id,
                Employee.source_system_id == row.source_system_id,
                Employee.employee_source_id == row.employee_source_id,
            )
        )
        if employee is None:
            name = row.employee_name_raw or f"Employee {row.employee_source_id}"
            counterparty = self._counterparty(
                session, run.tenant_id, name, "employee", row.employee_source_id
            )
            assert counterparty is not None
            employee = Employee(
                tenant_id=run.tenant_id,
                counterparty_id=counterparty.id,
                source_system_id=row.source_system_id,
                employee_source_id=row.employee_source_id,
                employee_number=row.employee_source_id,
                display_name=name,
                status="active",
            )
            session.add(employee)
            session.flush()
        entry = session.scalar(
            select(PayrollEntry).where(
                PayrollEntry.tenant_id == run.tenant_id,
                PayrollEntry.payroll_run_id == payroll_run.id,
                PayrollEntry.employee_id == employee.id,
                PayrollEntry.normalization_version == self.settings.NORMALIZATION_VERSION,
            )
        )
        is_detail = isinstance(row, StagingPayrollDetail)
        if entry is None:
            entry = PayrollEntry(
                tenant_id=run.tenant_id,
                payroll_run_id=payroll_run.id,
                employee_id=employee.id,
                staging_payroll_summary_id=None if is_detail else row.id,
                staging_payroll_detail_id=row.id if is_detail else None,
                gross_pay=row.gross_pay,
                regular_pay=getattr(row, "regular_pay", None),
                overtime_pay=getattr(row, "overtime_pay", None),
                bonus_pay=getattr(row, "bonus_pay", None),
                reimbursement_amount=(
                    getattr(row, "reimbursement_amount", None)
                    if is_detail
                    else getattr(row, "reimbursements", None)
                ),
                employee_tax=getattr(row, "employee_tax", None),
                employee_deduction=(
                    getattr(row, "employee_deduction", None)
                    if is_detail
                    else getattr(row, "employee_deductions", None)
                ),
                employer_tax=getattr(row, "employer_tax", None),
                employer_contribution=(
                    getattr(row, "employer_contribution", None)
                    if is_detail
                    else getattr(row, "employer_contributions", None)
                ),
                net_pay=row.net_pay,
                currency_id=currency.id,
                normalization_version=self.settings.NORMALIZATION_VERSION,
                canonical_hash=stable_hash(
                    "payroll_entry",
                    run.tenant_id,
                    row.source_system_id,
                    key,
                    row.employee_source_id,
                    self.settings.NORMALIZATION_VERSION,
                ),
                status="active",
                metadata_json={
                    "authoritative_source": "detail" if is_detail else "summary",
                    "currency_resolution": resolution,
                },
            )
            session.add(entry)
            session.flush()
        elif is_detail:
            if (
                entry.net_pay is not None
                and row.net_pay is not None
                and entry.net_pay != row.net_pay
            ):
                self._exception(
                    session,
                    run,
                    ingestion,
                    mapping.source_record_type,
                    row.id,
                    "payroll_conflict",
                    "payroll_conflict",
                    "warning",
                    "Summary and detail net pay differ",
                    observed=str(row.net_pay),
                    expected=str(entry.net_pay),
                )
            entry.staging_payroll_detail_id = row.id
            for field in (
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
            ):
                value = getattr(row, field)
                if value is not None:
                    setattr(entry, field, value)
            entry.metadata_json = {**(entry.metadata_json or {}), "authoritative_source": "detail"}
        else:
            entry.staging_payroll_summary_id = row.id
            if (
                (entry.metadata_json or {}).get("authoritative_source") == "detail"
                and entry.net_pay is not None
                and row.net_pay is not None
                and entry.net_pay != row.net_pay
            ):
                self._exception(
                    session,
                    run,
                    ingestion,
                    mapping.source_record_type,
                    row.id,
                    "payroll_conflict",
                    "payroll_conflict",
                    "warning",
                    "Summary and detail net pay differ",
                    observed=str(row.net_pay),
                    expected=str(entry.net_pay),
                )
        session.flush()
        staging_type = "staging_payroll_detail" if is_detail else "staging_payroll_summary"
        self._lineage(
            session, run, ingestion, mapping, row, "payroll_entry", entry.id, staging_type
        )
        self._recalculate_payroll_run(session, payroll_run)
        value = row.net_pay or Decimal(0)
        return value, entry.net_pay or Decimal(0), 1

    def _recalculate_payroll_run(self, session: Session, payroll_run: PayrollRun) -> None:
        entries = list(
            session.scalars(
                select(PayrollEntry).where(PayrollEntry.payroll_run_id == payroll_run.id)
            ).all()
        )

        def total(field: str) -> Decimal | None:
            values = [getattr(item, field) for item in entries if getattr(item, field) is not None]
            return sum(values, Decimal(0)) if values else None

        payroll_run.gross_pay_total = total("gross_pay")
        payroll_run.employee_deductions_total = total("employee_deduction")
        payroll_run.employer_contributions_total = total("employer_contribution")
        payroll_run.reimbursement_total = total("reimbursement_amount")
        payroll_run.net_pay_total = total("net_pay")

    def _lineage(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        mapping: NormalizationMapping,
        row: Any,
        canonical_type: str,
        canonical_id: int,
        staging_type: str,
    ) -> None:
        session.add(
            CanonicalRecordLineage(
                tenant_id=run.tenant_id,
                canonical_entity_type=canonical_type,
                canonical_entity_id=canonical_id,
                source_system_id=row.source_system_id,
                source_file_id=row.source_file_id,
                pipeline_run_id=ingestion.id,
                raw_source_row_id=row.raw_source_row_id,
                staging_entity_type=staging_type,
                staging_entity_id=row.id,
                source_row_number=row.source_row_number,
                source_record_id=row.source_record_id,
                transformation_name="staging_to_canonical",
                transformation_version=self.settings.NORMALIZATION_VERSION,
                mapping_code=mapping.code,
                mapping_version=mapping.version,
                metadata_json={"normalization_run_id": run.id},
            )
        )

    def _exception(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        staging_type: str,
        staging_id: int,
        code: str,
        exception_type: str,
        severity: str,
        message: str,
        *,
        observed: str | None = None,
        expected: str | None = None,
    ) -> None:
        fingerprint = stable_hash(
            ingestion.id, staging_type, staging_id, code, self.settings.NORMALIZATION_VERSION
        )
        if (
            session.scalar(
                select(NormalizationException).where(
                    NormalizationException.tenant_id == run.tenant_id,
                    NormalizationException.exception_fingerprint == fingerprint,
                )
            )
            is None
        ):
            session.add(
                NormalizationException(
                    tenant_id=run.tenant_id,
                    pipeline_run_id=run.id,
                    source_file_id=ingestion.source_file_id,
                    staging_entity_type=staging_type,
                    staging_entity_id=staging_id,
                    exception_code=code,
                    exception_type=exception_type,
                    severity=severity,
                    observed_value=observed,
                    expected_value=expected,
                    message=message,
                    status="open",
                    exception_fingerprint=fingerprint,
                    metadata_json={"normalization_version": self.settings.NORMALIZATION_VERSION},
                )
            )

    def _controls(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        staging_count: int,
        canonical_count: int,
        staging_total: Decimal,
        canonical_total: Decimal,
    ) -> list[NormalizationControlTotal]:
        controls = []
        for name, staging, canonical in (
            ("staging_record_count", Decimal(staging_count), Decimal(canonical_count)),
            ("staging_amount_total", staging_total, canonical_total),
        ):
            difference = canonical - staging
            status = "matched" if difference == 0 else "mismatch"
            item = NormalizationControlTotal(
                tenant_id=run.tenant_id,
                pipeline_run_id=run.id,
                source_file_id=ingestion.source_file_id,
                control_name=name,
                staging_value=staging,
                canonical_value=canonical,
                difference_value=difference,
                tolerance=Decimal("0.000001"),
                status=status,
                metadata_json={
                    "normalization_version": self.settings.NORMALIZATION_VERSION,
                    "basis": "mapping-specific canonical economic sign",
                },
            )
            session.add(item)
            controls.append(item)
        session.flush()
        return controls

    def _artifacts(
        self,
        session: Session,
        run: PipelineRun,
        ingestion: PipelineRun,
        mapping: NormalizationMapping,
        controls: list[NormalizationControlTotal],
        exceptions: int,
    ) -> None:
        base = {
            "tenant_id": run.tenant_id,
            "ingestion_run_id": ingestion.id,
            "normalization_run_id": run.id,
            "mapping_code": mapping.code,
            "mapping_version": mapping.version,
            "normalization_version": self.settings.NORMALIZATION_VERSION,
            "staging_count": run.records_extracted,
            "canonical_count": run.records_accepted,
            "exception_count": exceptions,
        }
        payloads = {
            "normalization_manifest": base,
            "normalization_summary": base,
            "normalization_exceptions_report": {**base, "exception_count": exceptions},
            "normalization_control_total_report": {
                **base,
                "controls": [
                    {
                        "name": item.control_name,
                        "staging": item.staging_value,
                        "canonical": item.canonical_value,
                        "difference": item.difference_value,
                        "status": item.status,
                    }
                    for item in controls
                ],
            },
        }
        for artifact_type, payload in payloads.items():
            if artifact_type == "normalization_manifest":
                directory, relative = (
                    self.settings.MANIFESTS_DIRECTORY / "normalization",
                    "manifests/normalization",
                )
            elif artifact_type == "normalization_exceptions_report":
                directory, relative = (
                    self.settings.INGESTION_REPORTS_DIRECTORY / "normalization-exceptions",
                    "reports/normalization-exceptions",
                )
            else:
                directory, relative = (
                    self.settings.INGESTION_REPORTS_DIRECTORY / "normalization",
                    "reports/normalization",
                )
            directory.mkdir(parents=True, exist_ok=True)
            filename = f"run_{run.id}_{artifact_type}.json"
            path = directory / filename
            data = json.dumps(payload, default=str, indent=2).encode()
            with path.open("xb") as handle:
                handle.write(data)
            session.add(
                PipelineRunArtifact(
                    tenant_id=run.tenant_id,
                    pipeline_run_id=run.id,
                    artifact_type=artifact_type,
                    name=filename,
                    relative_path=f"{relative}/{filename}",
                    checksum=hashlib.sha256(data).hexdigest(),
                    mime_type="application/json",
                    file_size_bytes=len(data),
                    metadata_json={"normalization_version": self.settings.NORMALIZATION_VERSION},
                )
            )
