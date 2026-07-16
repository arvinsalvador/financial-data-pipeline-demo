from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BankAccount,
    BankTransaction,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedSourceFile,
    PayrollEntry,
    PayrollReconciliationAllocation,
    PayrollReconciliationCandidate,
    PayrollReconciliationControlTotal,
    PayrollReconciliationException,
    PayrollReconciliationGroup,
    PayrollReconciliationMatch,
    PayrollReconciliationReport,
    PayrollReconciliationRule,
    PayrollReconciliationRun,
    PayrollRun,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    Tenant,
    ValidationIssue,
    ValidationRun,
)
from app.services.reconciliation_matching import (
    bounded_exact_groups,
    normalize_reference,
    stable_fingerprint,
)

SETTLEMENT_MODELS = {
    "net_pay_only",
    "net_pay_plus_taxes",
    "full_payroll_cash_requirement",
    "split_withdrawals",
    "configured_components",
}
STEPS = (
    "validate_tenant_and_permissions",
    "load_payroll_reconciliation_configuration",
    "select_eligible_payroll_runs",
    "validate_payroll_internal_totals",
    "select_eligible_payroll_bank_transactions",
    "select_eligible_payroll_gl_records",
    "verify_validation_status",
    "calculate_input_and_ruleset_fingerprints",
    "detect_duplicates_and_reversals",
    "generate_payroll_to_bank_candidates",
    "generate_payroll_to_gl_candidates",
    "generate_grouped_candidates",
    "score_and_rank_candidates",
    "resolve_candidate_conflicts",
    "auto_accept_exact_matches",
    "create_suggested_and_partial_matches",
    "create_unmatched_exceptions",
    "calculate_allocations",
    "calculate_control_totals",
    "validate_reconciliation_invariants",
    "generate_reports_and_artifacts",
    "finalize_payroll_reconciliation",
)


class PayrollReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class PayrollTotals:
    entry_count: int
    gross_pay: Decimal | None
    employee_tax: Decimal | None
    employee_deduction: Decimal | None
    employer_tax: Decimal | None
    employer_contribution: Decimal | None
    reimbursement: Decimal | None
    net_pay: Decimal | None


@dataclass(frozen=True)
class BankWithdrawal:
    bank_transaction_id: int
    transaction_date: date
    amount: Decimal
    reference: str
    description: str
    canonical_hash: str


@dataclass(frozen=True)
class PayrollGLLine:
    record_id: str
    row_number: int
    posting_date: date
    payroll_run_id: int | None
    account_code: str
    debit: Decimal
    credit: Decimal
    reference: str
    description: str
    journal_entry_id: str
    row_hash: str
    blocked: bool = False


def component_sum(entries: list[PayrollEntry], attribute: str) -> Decimal | None:
    values = [getattr(entry, attribute) for entry in entries]
    if not values or any(value is None for value in values):
        return None
    return sum((Decimal(value) for value in values), Decimal(0)).quantize(Decimal("0.000001"))


def calculate_payroll_totals(entries: list[PayrollEntry]) -> PayrollTotals:
    return PayrollTotals(
        len(entries),
        component_sum(entries, "gross_pay"),
        component_sum(entries, "employee_tax"),
        component_sum(entries, "employee_deduction"),
        component_sum(entries, "employer_tax"),
        component_sum(entries, "employer_contribution"),
        component_sum(entries, "reimbursement_amount"),
        component_sum(entries, "net_pay"),
    )


def expected_settlement(run: PayrollRun, totals: PayrollTotals, model: str) -> Decimal:
    net = totals.net_pay if totals.net_pay is not None else Decimal(run.net_pay_total or 0)
    if model == "net_pay_only" or model == "split_withdrawals":
        return net
    employee_tax = totals.employee_tax or Decimal(0)
    employer_tax = totals.employer_tax or Decimal(0)
    contribution = totals.employer_contribution or Decimal(run.employer_contributions_total or 0)
    if model == "net_pay_plus_taxes":
        return net + employee_tax + employer_tax
    if model == "full_payroll_cash_requirement":
        return net + employer_tax + contribution
    configured = (run.metadata_json or {}).get("configured_cash_components")
    if configured is None:
        raise PayrollReconciliationError(
            "configured_components requires payroll metadata configuration"
        )
    values = {
        "net_pay": net,
        "employee_tax": employee_tax,
        "employer_tax": employer_tax,
        "employer_contribution": contribution,
    }
    return sum((values[item] for item in configured), Decimal(0))


def score_payroll_bank(
    run: PayrollRun,
    expected: Decimal,
    bank: BankWithdrawal,
    tolerance: Decimal,
    date_tolerance: int,
) -> tuple[Decimal, dict[str, Any]] | None:
    difference = abs(expected - bank.amount)
    days = abs((run.pay_date - bank.transaction_date).days)
    if difference > tolerance or days > date_tolerance:
        return None
    source_reference = normalize_reference(run.payroll_run_source_id)
    bank_reference = normalize_reference(bank.reference)
    reference_exact = bool(source_reference and source_reference == bank_reference)
    confidence = (
        Decimal("1.000000")
        if reference_exact
        else Decimal("0.980000")
        if days == 0
        else max(Decimal("0.700000"), Decimal("0.950000") - Decimal(days) * Decimal("0.05"))
    )
    return confidence, {
        "reference_exact": reference_exact,
        "amount_exact": difference <= tolerance,
        "date_difference_days": days,
        "settlement_amount": str(expected),
    }


class PayrollReconciliationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tolerance = Decimal(str(settings.PAYROLL_RECONCILIATION_AMOUNT_TOLERANCE))

    @property
    def data_root(self) -> Path:
        return self.settings.GENERATED_DATA_DIRECTORY.parent

    @staticmethod
    def _bank_metadata(item: BankWithdrawal) -> dict[str, Any]:
        return {
            "bank_transaction_id": item.bank_transaction_id,
            "transaction_date": item.transaction_date.isoformat(),
            "amount": str(item.amount),
            "reference": item.reference,
            "description": item.description,
            "canonical_hash": item.canonical_hash,
        }

    @staticmethod
    def _gl_metadata(item: PayrollGLLine) -> dict[str, Any]:
        return {
            "record_id": item.record_id,
            "row_number": item.row_number,
            "posting_date": item.posting_date.isoformat(),
            "payroll_run_id": item.payroll_run_id,
            "account_code": item.account_code,
            "debit": str(item.debit),
            "credit": str(item.credit),
            "reference": item.reference,
            "description": item.description,
            "journal_entry_id": item.journal_entry_id,
            "row_hash": item.row_hash,
            "blocked": item.blocked,
        }

    def run(
        self,
        session: Session,
        tenant: Tenant,
        account_id: int,
        date_from: date,
        date_to: date,
        settlement_model: str,
        force_rerun: bool = False,
    ) -> tuple[PayrollReconciliationRun, bool]:
        if settlement_model not in SETTLEMENT_MODELS:
            raise PayrollReconciliationError("Invalid payroll settlement model")
        if date_from > date_to:
            raise PayrollReconciliationError("date_from must not be later than date_to")
        account = session.scalar(
            select(BankAccount).where(
                BankAccount.id == account_id, BankAccount.tenant_id == tenant.id
            )
        )
        if account is None or account.account_type != "payroll":
            raise PayrollReconciliationError("Payroll bank account was not found for this tenant")
        payroll_runs = list(
            session.scalars(
                select(PayrollRun)
                .where(
                    PayrollRun.tenant_id == tenant.id,
                    PayrollRun.pay_date >= date_from,
                    PayrollRun.pay_date <= date_to,
                    PayrollRun.status == "normalized",
                )
                .order_by(PayrollRun.pay_date, PayrollRun.id)
            )
        )
        if not payroll_runs:
            raise PayrollReconciliationError("No eligible canonical payroll runs were found")
        entries = list(
            session.scalars(
                select(PayrollEntry)
                .where(
                    PayrollEntry.tenant_id == tenant.id,
                    PayrollEntry.payroll_run_id.in_([item.id for item in payroll_runs]),
                    PayrollEntry.status == "active",
                )
                .order_by(PayrollEntry.payroll_run_id, PayrollEntry.employee_id, PayrollEntry.id)
            )
        )
        entries_by_run: dict[int, list[PayrollEntry]] = {item.id: [] for item in payroll_runs}
        for entry in entries:
            entries_by_run[entry.payroll_run_id].append(entry)
        totals = {
            item.id: calculate_payroll_totals(entries_by_run[item.id]) for item in payroll_runs
        }
        generated, source_file, validation = self._ledger_source(session, tenant.id)
        critical = list(
            session.scalars(
                select(ValidationIssue).where(
                    ValidationIssue.validation_run_id == validation.id,
                    ValidationIssue.severity == "critical",
                    ValidationIssue.status == "open",
                )
            )
        )
        path = self.data_root / source_file.relative_path
        if not path.is_file() or self._sha(path) != source_file.sha256_checksum:
            raise PayrollReconciliationError("Generated payroll ledger checksum is invalid")
        bank = self._bank_withdrawals(session, tenant.id, account.id, date_from, date_to)
        gl = self._gl_lines(path, {item.id for item in payroll_runs}, critical)
        rules = list(
            session.scalars(
                select(PayrollReconciliationRule)
                .where(
                    PayrollReconciliationRule.tenant_id == tenant.id,
                    PayrollReconciliationRule.version
                    == self.settings.PAYROLL_RECONCILIATION_VERSION,
                    PayrollReconciliationRule.is_active.is_(True),
                )
                .order_by(PayrollReconciliationRule.execution_order)
            )
        )
        if not rules:
            raise PayrollReconciliationError("Phase 10 payroll reconciliation rules are not seeded")
        ruleset = stable_fingerprint(
            {
                "rules": [
                    [
                        r.code,
                        r.version,
                        r.execution_order,
                        r.auto_accept,
                        str(r.minimum_confidence),
                        r.configuration_json,
                    ]
                    for r in rules
                ],
                "settlement_model": settlement_model,
            }
        )
        fingerprint = stable_fingerprint(
            {
                "period": [date_from, date_to],
                "account": account.id,
                "settlement_model": settlement_model,
                "payroll": [
                    [
                        r.id,
                        r.canonical_hash,
                        str(expected_settlement(r, totals[r.id], settlement_model)),
                    ]
                    for r in payroll_runs
                ],
                "entries": [[e.id, e.canonical_hash] for e in entries],
                "bank": [[b.bank_transaction_id, b.canonical_hash, str(b.amount)] for b in bank],
                "gl": [[g.record_id, g.row_hash] for g in gl],
                "validation": [i.issue_fingerprint for i in critical],
                "version": self.settings.PAYROLL_RECONCILIATION_VERSION,
            }
        )
        existing = session.scalar(
            select(PayrollReconciliationRun).where(
                PayrollReconciliationRun.tenant_id == tenant.id,
                PayrollReconciliationRun.input_fingerprint == fingerprint,
                PayrollReconciliationRun.ruleset_fingerprint == ruleset,
                PayrollReconciliationRun.reconciliation_version
                == self.settings.PAYROLL_RECONCILIATION_VERSION,
            )
        )
        if existing is not None:
            self.verify_integrity(session, existing)
            return existing, True
        definition = session.scalar(
            select(PipelineDefinition)
            .where(
                PipelineDefinition.code == "payroll_reconciliation",
                PipelineDefinition.is_active.is_(True),
            )
            .order_by(PipelineDefinition.id.desc())
        )
        if definition is None:
            raise PayrollReconciliationError("Payroll reconciliation pipeline is not active")
        now = datetime.now(UTC)
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="payroll_reconciliation",
            status="running",
            started_at=now,
            metadata_json={
                "version": self.settings.PAYROLL_RECONCILIATION_VERSION,
                "settlement_model": settlement_model,
                "force_rerun": force_rerun,
            },
        )
        pipeline.steps = [
            PipelineRunStep(
                step_name=name,
                step_order=index,
                status="completed" if index < len(STEPS) else "running",
                started_at=now,
                completed_at=now if index < len(STEPS) else None,
                metadata_json={},
            )
            for index, name in enumerate(STEPS, 1)
        ]
        session.add(pipeline)
        session.flush()
        run = PayrollReconciliationRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            reconciliation_version=self.settings.PAYROLL_RECONCILIATION_VERSION,
            status="running",
            date_from=date_from,
            date_to=date_to,
            payroll_bank_account_id=account.id,
            generated_source_file_id=source_file.id,
            validation_run_id=validation.id,
            settlement_model=settlement_model,
            included_payroll_run_count=len(payroll_runs),
            included_payroll_entry_count=len(entries),
            included_bank_transaction_count=len(bank),
            included_gl_record_count=len(gl),
            input_fingerprint=fingerprint,
            ruleset_fingerprint=ruleset,
            started_at=now,
            metadata_json={
                "generated_dataset_run_id": generated.id,
                "source_precedence": "canonical payroll entries with payroll-run batch controls",
                "critical_validation_issues": len(critical),
            },
        )
        session.add(run)
        session.flush()
        self._reconcile(
            session, run, payroll_runs, entries_by_run, totals, bank, gl, {r.code: r for r in rules}
        )
        session.flush()
        self._controls(session, run, payroll_runs, totals, bank, gl)
        session.flush()
        self._reports(session, tenant.code, run, pipeline)
        self.verify_integrity(session, run)
        completed = datetime.now(UTC)
        run.completed_at = completed
        run.status = "completed_with_exceptions" if run.exception_count else "completed"
        pipeline.status = run.status
        pipeline.completed_at = completed
        pipeline.records_extracted = len(payroll_runs) + len(entries) + len(bank) + len(gl)
        pipeline.records_accepted = run.automatically_matched_count
        pipeline.steps[-1].status = "completed"
        pipeline.steps[-1].completed_at = completed
        session.commit()
        return run, False

    def _ledger_source(
        self, session: Session, tenant_id: int
    ) -> tuple[GeneratedDatasetRun, GeneratedSourceFile, ValidationRun]:
        validation = session.scalar(
            select(ValidationRun)
            .join(
                GeneratedDatasetRun,
                GeneratedDatasetRun.id == ValidationRun.generated_dataset_run_id,
            )
            .where(
                ValidationRun.tenant_id == tenant_id,
                ValidationRun.target_type == "generated_dataset",
                ValidationRun.status == "completed",
                GeneratedDatasetRun.status == "completed",
            )
            .order_by(ValidationRun.generated_dataset_run_id.desc(), ValidationRun.id.desc())
        )
        if validation is None or validation.generated_dataset_run_id is None:
            raise PayrollReconciliationError(
                "A completed Phase 8 generated-dataset validation is required"
            )
        generated = session.get(GeneratedDatasetRun, validation.generated_dataset_run_id)
        source = session.scalar(
            select(GeneratedSourceFile).where(
                GeneratedSourceFile.generated_dataset_run_id == validation.generated_dataset_run_id,
                GeneratedSourceFile.file_type == "general_ledger",
            )
        )
        if generated is None or source is None:
            raise PayrollReconciliationError("Validated generated payroll ledger is unavailable")
        return generated, source, validation

    def _bank_withdrawals(
        self, session: Session, tenant_id: int, account_id: int, start: date, end: date
    ) -> list[BankWithdrawal]:
        rows = session.execute(
            select(BankTransaction, FinancialTransaction)
            .join(
                FinancialTransaction,
                FinancialTransaction.id == BankTransaction.financial_transaction_id,
            )
            .where(
                BankTransaction.tenant_id == tenant_id,
                BankTransaction.bank_account_id == account_id,
                FinancialTransaction.status == "active",
            )
            .order_by(FinancialTransaction.source_row_number, FinancialTransaction.id)
        ).all()
        previous: Decimal | None = None
        result: list[BankWithdrawal] = []
        for detail, transaction in rows:
            amount = abs(Decimal(transaction.amount))
            outflow = False
            if detail.debit_amount is not None and Decimal(detail.debit_amount) != 0:
                outflow = True
                amount = abs(Decimal(detail.debit_amount))
            elif detail.credit_amount is not None and Decimal(detail.credit_amount) != 0:
                outflow = False
            elif detail.running_balance is not None and previous is not None:
                outflow = Decimal(detail.running_balance) < previous
            if detail.running_balance is not None:
                previous = Decimal(detail.running_balance)
            if outflow and start <= transaction.transaction_date <= end:
                result.append(
                    BankWithdrawal(
                        detail.id,
                        transaction.transaction_date,
                        amount,
                        transaction.reference_number or transaction.source_record_id or "",
                        transaction.description or "",
                        transaction.canonical_hash,
                    )
                )
        return result

    def _gl_lines(
        self, path: Path, payroll_ids: set[int], issues: list[ValidationIssue]
    ) -> list[PayrollGLLine]:
        blocked_rows = {
            i.row_number for i in issues if i.filename == path.name and i.row_number is not None
        }
        result = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                payroll_id = (
                    int(row["payroll_run_id"]) if row.get("payroll_run_id", "").isdigit() else None
                )
                if payroll_id not in payroll_ids or row.get("source_type") != "payroll_run":
                    continue
                result.append(
                    PayrollGLLine(
                        row.get("journal_line_id") or f"row-{row_number}",
                        row_number,
                        date.fromisoformat(row.get("posting_date") or row["entry_date"]),
                        payroll_id,
                        row["account_code"],
                        Decimal(row.get("debit") or 0),
                        Decimal(row.get("credit") or 0),
                        row.get("reference_number") or "",
                        row.get("description") or "",
                        row.get("journal_entry_id") or "",
                        stable_fingerprint({k: row[k] for k in sorted(row)}),
                        row_number in blocked_rows,
                    )
                )
        return result

    def _reconcile(
        self,
        session: Session,
        reconciliation: PayrollReconciliationRun,
        payroll_runs: list[PayrollRun],
        entries_by_run: dict[int, list[PayrollEntry]],
        totals_by_run: dict[int, PayrollTotals],
        bank: list[BankWithdrawal],
        gl: list[PayrollGLLine],
        rules: dict[str, PayrollReconciliationRule],
    ) -> None:
        used_bank: set[int] = set()
        used_gl: set[str] = set()
        fully: set[int] = set()
        self._detect_duplicate_and_reversal_evidence(
            session, reconciliation, payroll_runs, bank, gl
        )
        payroll_reference_counts: dict[str, int] = {}
        for payroll in payroll_runs:
            reference = normalize_reference(payroll.payroll_run_source_id)
            payroll_reference_counts[reference] = payroll_reference_counts.get(reference, 0) + 1
        for payroll in payroll_runs:
            totals = totals_by_run[payroll.id]
            internal_ok = self._internal(
                session, reconciliation, payroll, entries_by_run[payroll.id], totals
            )
            if payroll_reference_counts[normalize_reference(payroll.payroll_run_source_id)] > 1:
                internal_ok = False
                self._exception(
                    session,
                    reconciliation,
                    "duplicate_payroll_run",
                    payroll_run_id=payroll.id,
                    severity="error",
                )
            expected = expected_settlement(payroll, totals, reconciliation.settlement_model)
            scored: list[tuple[BankWithdrawal, tuple[Decimal, dict[str, Any]]]] = []
            for bank_candidate in bank:
                if bank_candidate.bank_transaction_id in used_bank:
                    continue
                score = score_payroll_bank(
                    payroll,
                    expected,
                    bank_candidate,
                    self.tolerance,
                    self.settings.PAYROLL_RECONCILIATION_DATE_TOLERANCE_DAYS,
                )
                if score is not None:
                    scored.append((bank_candidate, score))
            scored.sort(
                key=lambda item: (
                    -item[1][0],
                    item[1][1]["date_difference_days"],
                    item[0].bank_transaction_id,
                )
            )
            bank_item = scored[0][0] if len(scored) == 1 else None
            bank_score = scored[0][1][0] if len(scored) == 1 else Decimal(0)
            for bank_candidate, (confidence, reasons) in scored[
                : self.settings.PAYROLL_RECONCILIATION_MAX_CANDIDATES_PER_RUN
            ]:
                rule = (
                    rules["payroll_run_to_bank_exact_net"]
                    if confidence >= Decimal("0.98")
                    else rules["payroll_run_to_bank_date_tolerance"]
                )
                session.add(
                    PayrollReconciliationCandidate(
                        tenant_id=reconciliation.tenant_id,
                        payroll_reconciliation_run_id=reconciliation.id,
                        payroll_reconciliation_rule_id=rule.id,
                        reconciliation_version=reconciliation.reconciliation_version,
                        payroll_run_id=payroll.id,
                        bank_transaction_id=bank_candidate.bank_transaction_id,
                        candidate_type="payroll_to_bank",
                        amount_difference=abs(expected - bank_candidate.amount),
                        date_difference_days=reasons["date_difference_days"],
                        reference_score=1 if reasons["reference_exact"] else 0,
                        description_score=0,
                        amount_score=1,
                        date_score=1 if reasons["date_difference_days"] == 0 else Decimal("0.8"),
                        total_confidence=confidence,
                        candidate_status="generated",
                        reason_json=reasons,
                        candidate_fingerprint=stable_fingerprint(
                            {
                                "payroll": payroll.id,
                                "bank": bank_candidate.bank_transaction_id,
                                "rule": rule.code,
                            }
                        ),
                    )
                )
            bank_groups = bounded_exact_groups(
                expected,
                [
                    (str(item.bank_transaction_id), item.amount, item.transaction_date)
                    for item in bank
                    if item.bank_transaction_id not in used_bank
                ],
                payroll.pay_date,
                self.settings.PAYROLL_RECONCILIATION_MAX_BANK_GROUP_SIZE,
                self.settings.PAYROLL_RECONCILIATION_DATE_TOLERANCE_DAYS,
                self.tolerance,
            )
            bank_group = (
                [item for item in bank if str(item.bank_transaction_id) in set(bank_groups[0])]
                if bank_item is None and len(bank_groups) == 1
                else []
            )
            group_key = stable_fingerprint(
                {
                    "payroll": payroll.id,
                    "bank": [item.bank_transaction_id for item in bank_group],
                }
            )
            for grouped_bank in bank_group:
                grouped_rule = rules["payroll_bank_batch_grouping"]
                session.add(
                    PayrollReconciliationCandidate(
                        tenant_id=reconciliation.tenant_id,
                        payroll_reconciliation_run_id=reconciliation.id,
                        payroll_reconciliation_rule_id=grouped_rule.id,
                        reconciliation_version=reconciliation.reconciliation_version,
                        payroll_run_id=payroll.id,
                        bank_transaction_id=grouped_bank.bank_transaction_id,
                        candidate_type="payroll_to_bank_group",
                        match_group_key=group_key,
                        amount_difference=0,
                        date_difference_days=abs(
                            (payroll.pay_date - grouped_bank.transaction_date).days
                        ),
                        reference_score=0,
                        description_score=0,
                        amount_score=1,
                        date_score=Decimal("0.8"),
                        total_confidence=Decimal("0.9"),
                        candidate_status="suggested",
                        reason_json={
                            "unique_bounded_group": True,
                            "group_total": str(
                                sum((item.amount for item in bank_group), Decimal(0))
                            ),
                            "requires_review": True,
                        },
                        candidate_fingerprint=stable_fingerprint(
                            {
                                "group": group_key,
                                "bank": grouped_bank.bank_transaction_id,
                            }
                        ),
                    )
                )
            payroll_gl = [
                gl_line
                for gl_line in gl
                if gl_line.payroll_run_id == payroll.id and gl_line.record_id not in used_gl
            ]
            gl_debit = sum((item.debit for item in payroll_gl), Decimal(0))
            gl_credit = sum((item.credit for item in payroll_gl), Decimal(0))
            expected_gl = Decimal(payroll.gross_pay_total or 0) + Decimal(
                payroll.employer_contributions_total or 0
            )
            gl_ok = bool(
                payroll_gl
                and abs(gl_debit - gl_credit) <= self.tolerance
                and abs(gl_debit - expected_gl) <= self.tolerance
                and not any(item.blocked for item in payroll_gl)
            )
            for gl_line in payroll_gl:
                rule = rules["payroll_run_to_gl_exact_totals"]
                session.add(
                    PayrollReconciliationCandidate(
                        tenant_id=reconciliation.tenant_id,
                        payroll_reconciliation_run_id=reconciliation.id,
                        payroll_reconciliation_rule_id=rule.id,
                        reconciliation_version=reconciliation.reconciliation_version,
                        payroll_run_id=payroll.id,
                        gl_record_id=gl_line.record_id,
                        candidate_type="payroll_to_gl",
                        amount_difference=abs(gl_debit - gl_credit),
                        date_difference_days=abs((payroll.pay_date - gl_line.posting_date).days),
                        reference_score=1
                        if normalize_reference(payroll.payroll_run_source_id)
                        == normalize_reference(gl_line.reference)
                        else 0,
                        description_score=0,
                        amount_score=1 if gl_ok else 0,
                        date_score=1
                        if payroll.pay_date == gl_line.posting_date
                        else Decimal("0.8"),
                        total_confidence=Decimal("1") if gl_ok else Decimal("0.7"),
                        candidate_status="generated",
                        reason_json={
                            "journal_balanced": abs(gl_debit - gl_credit) <= self.tolerance,
                            "explicit_payroll_run_id": True,
                            "account_code": gl_line.account_code,
                        },
                        candidate_fingerprint=stable_fingerprint(
                            {"payroll": payroll.id, "gl": gl_line.record_id}
                        ),
                    )
                )
            full = internal_ok and bank_item is not None and gl_ok
            bank_group_total = sum((item.amount for item in bank_group), Decimal(0))
            partial = bank_item is not None or bool(bank_group) or gl_ok
            status = "matched" if full else "partially_matched" if partial else "suggested"
            confidence = min(
                bank_score or Decimal("0.65"), Decimal("1") if gl_ok else Decimal("0.65")
            )
            rule = (
                rules["payroll_run_to_bank_exact_net"] if full else rules["payroll_partial_match"]
            )
            group = PayrollReconciliationGroup(
                tenant_id=reconciliation.tenant_id,
                payroll_reconciliation_run_id=reconciliation.id,
                reconciliation_version=reconciliation.reconciliation_version,
                payroll_run_id=payroll.id,
                group_type=(
                    "combined_bank_and_gl"
                    if full
                    else "payroll_to_bank_one_to_many"
                    if bank_group
                    else "partial"
                ),
                status=status,
                confidence=confidence,
                payroll_total=expected,
                bank_total=bank_item.amount if bank_item else bank_group_total,
                gl_total=gl_debit if gl_ok else 0,
                matched_amount=expected
                if full
                else min(
                    expected,
                    bank_item.amount
                    if bank_item
                    else bank_group_total
                    if bank_group
                    else gl_debit
                    if gl_ok
                    else 0,
                ),
                difference_amount=abs(
                    expected - (bank_item.amount if bank_item else bank_group_total)
                ),
                rule_id=rule.id,
                auto_accepted=full,
                group_fingerprint=stable_fingerprint(
                    {
                        "payroll": payroll.id,
                        "bank": bank_item.bank_transaction_id if bank_item else None,
                        "gl": [item.record_id for item in payroll_gl] if gl_ok else [],
                    }
                ),
                metadata_json={
                    "settlement_model": reconciliation.settlement_model,
                    "internal_controls_passed": internal_ok,
                    "bank": self._bank_metadata(bank_item) if bank_item else None,
                    "bank_group": [self._bank_metadata(item) for item in bank_group],
                    "gl_records": [self._gl_metadata(item) for item in payroll_gl],
                },
            )
            session.add(group)
            session.flush()
            if bank_item:
                session.add(
                    PayrollReconciliationMatch(
                        tenant_id=reconciliation.tenant_id,
                        payroll_reconciliation_run_id=reconciliation.id,
                        reconciliation_group_id=group.id,
                        payroll_run_id=payroll.id,
                        bank_transaction_id=bank_item.bank_transaction_id,
                        matched_amount=min(expected, bank_item.amount),
                        match_component="bank_withdrawal",
                        confidence=bank_score,
                        status=status,
                        rule_code=rule.code,
                        metadata_json={"source_lineage": bank_item.canonical_hash},
                    )
                )
                if full:
                    session.add(
                        PayrollReconciliationAllocation(
                            tenant_id=reconciliation.tenant_id,
                            payroll_reconciliation_run_id=reconciliation.id,
                            reconciliation_group_id=group.id,
                            payroll_run_id=payroll.id,
                            bank_transaction_id=bank_item.bank_transaction_id,
                            allocation_type="net_pay_to_bank",
                            allocated_amount=expected,
                            reconciliation_version=reconciliation.reconciliation_version,
                        )
                    )
                    used_bank.add(bank_item.bank_transaction_id)
            for grouped_bank in bank_group:
                session.add(
                    PayrollReconciliationMatch(
                        tenant_id=reconciliation.tenant_id,
                        payroll_reconciliation_run_id=reconciliation.id,
                        reconciliation_group_id=group.id,
                        payroll_run_id=payroll.id,
                        bank_transaction_id=grouped_bank.bank_transaction_id,
                        matched_amount=grouped_bank.amount,
                        match_component="bank_withdrawal",
                        confidence=Decimal("0.9"),
                        status="suggested",
                        rule_code=rules["payroll_bank_batch_grouping"].code,
                        metadata_json={
                            "source_lineage": grouped_bank.canonical_hash,
                            "group_key": group_key,
                        },
                    )
                )
            if gl_ok:
                for gl_line in payroll_gl:
                    component = "gl_expense" if gl_line.debit else "gl_liability"
                    amount = gl_line.debit or gl_line.credit
                    session.add(
                        PayrollReconciliationMatch(
                            tenant_id=reconciliation.tenant_id,
                            payroll_reconciliation_run_id=reconciliation.id,
                            reconciliation_group_id=group.id,
                            payroll_run_id=payroll.id,
                            gl_record_id=gl_line.record_id,
                            matched_amount=amount,
                            match_component=component,
                            confidence=Decimal("1"),
                            status=status,
                            rule_code=rules["payroll_run_to_gl_exact_totals"].code,
                            metadata_json={
                                "journal_entry_id": gl_line.journal_entry_id,
                                "row_number": gl_line.row_number,
                            },
                        )
                    )
                    if full:
                        session.add(
                            PayrollReconciliationAllocation(
                                tenant_id=reconciliation.tenant_id,
                                payroll_reconciliation_run_id=reconciliation.id,
                                reconciliation_group_id=group.id,
                                payroll_run_id=payroll.id,
                                gl_record_id=gl_line.record_id,
                                allocation_type="payroll_expense_to_gl"
                                if gl_line.debit
                                else "payroll_liability_to_gl",
                                allocated_amount=amount,
                                reconciliation_version=reconciliation.reconciliation_version,
                            )
                        )
                        used_gl.add(gl_line.record_id)
            if full:
                fully.add(payroll.id)
            else:
                self._exception(
                    session,
                    reconciliation,
                    "partial_payroll_match" if partial else "unmatched_payroll_run",
                    payroll_run_id=payroll.id,
                    group_id=group.id,
                    observed=str(group.matched_amount),
                    expected=str(expected),
                )
        for bank_withdrawal in bank:
            if bank_withdrawal.bank_transaction_id not in used_bank:
                self._exception(
                    session,
                    reconciliation,
                    "unmatched_bank_withdrawal",
                    bank_id=bank_withdrawal.bank_transaction_id,
                    observed=str(bank_withdrawal.amount),
                )
        for gl_line in gl:
            if gl_line.record_id not in used_gl:
                self._exception(
                    session,
                    reconciliation,
                    "unmatched_payroll_gl",
                    gl_id=gl_line.record_id,
                    observed=str(gl_line.debit or gl_line.credit),
                )

    def _detect_duplicate_and_reversal_evidence(
        self,
        session: Session,
        reconciliation: PayrollReconciliationRun,
        payroll_runs: list[PayrollRun],
        bank: list[BankWithdrawal],
        gl: list[PayrollGLLine],
    ) -> None:
        reversal_words = ("reversal", "reversed", "void", "correction")
        for payroll in payroll_runs:
            evidence = " ".join(
                [
                    payroll.payroll_run_source_id,
                    str((payroll.metadata_json or {}).get("status", "")),
                    str((payroll.metadata_json or {}).get("description", "")),
                ]
            ).casefold()
            if any(word in evidence for word in reversal_words):
                self._exception(
                    session,
                    reconciliation,
                    "payroll_reversal",
                    payroll_run_id=payroll.id,
                )
        bank_keys: dict[tuple[date, Decimal, str], int] = {}
        for withdrawal in bank:
            bank_key = (
                withdrawal.transaction_date,
                withdrawal.amount,
                normalize_reference(withdrawal.reference),
            )
            if bank_key in bank_keys:
                self._exception(
                    session,
                    reconciliation,
                    "duplicate_bank_withdrawal",
                    bank_id=withdrawal.bank_transaction_id,
                    observed=str(withdrawal.amount),
                )
            else:
                bank_keys[bank_key] = withdrawal.bank_transaction_id
            bank_evidence = f"{withdrawal.reference} {withdrawal.description}".casefold()
            if any(word in bank_evidence for word in reversal_words):
                self._exception(
                    session,
                    reconciliation,
                    "payroll_reversal",
                    bank_id=withdrawal.bank_transaction_id,
                    observed=str(withdrawal.amount),
                )
        gl_keys: set[tuple[str, str, Decimal, Decimal]] = set()
        for line in gl:
            gl_key = (line.journal_entry_id, line.account_code, line.debit, line.credit)
            if gl_key in gl_keys:
                self._exception(
                    session,
                    reconciliation,
                    "duplicate_gl_batch",
                    gl_id=line.record_id,
                    observed=str(line.debit or line.credit),
                )
            else:
                gl_keys.add(gl_key)
            gl_evidence = f"{line.reference} {line.description}".casefold()
            if any(word in gl_evidence for word in reversal_words):
                self._exception(
                    session,
                    reconciliation,
                    "payroll_reversal",
                    gl_id=line.record_id,
                    observed=str(line.debit or line.credit),
                )

    def _internal(
        self,
        session: Session,
        reconciliation: PayrollReconciliationRun,
        payroll: PayrollRun,
        entries: list[PayrollEntry],
        totals: PayrollTotals,
    ) -> bool:
        okay = True
        for code, calculated, stated in (
            ("gross_pay_mismatch", totals.gross_pay, payroll.gross_pay_total),
            ("net_pay_mismatch", totals.net_pay, payroll.net_pay_total),
            (
                "employee_deduction_mismatch",
                totals.employee_deduction,
                payroll.employee_deductions_total,
            ),
            (
                "employer_contribution_mismatch",
                totals.employer_contribution,
                payroll.employer_contributions_total,
            ),
            ("reimbursement_mismatch", totals.reimbursement, payroll.reimbursement_total),
        ):
            if (
                calculated is not None
                and stated is not None
                and abs(calculated - Decimal(stated)) > self.tolerance
            ):
                okay = False
                self._exception(
                    session,
                    reconciliation,
                    code,
                    payroll_run_id=payroll.id,
                    observed=str(calculated),
                    expected=str(stated),
                    severity="error",
                )
        if (
            totals.net_pay is not None
            and totals.gross_pay is not None
            and totals.net_pay
            > totals.gross_pay + (totals.reimbursement or Decimal(0)) + self.tolerance
        ):
            okay = False
            self._exception(
                session,
                reconciliation,
                "payroll_run_total_mismatch",
                payroll_run_id=payroll.id,
                observed=str(totals.net_pay),
                expected=str(totals.gross_pay),
            )
        formula_components = (
            totals.gross_pay,
            totals.reimbursement,
            totals.employee_tax,
            totals.employee_deduction,
            totals.net_pay,
        )
        if all(value is not None for value in formula_components):
            formula_net = (
                (totals.gross_pay or Decimal(0))
                + (totals.reimbursement or Decimal(0))
                - (totals.employee_tax or Decimal(0))
                - (totals.employee_deduction or Decimal(0))
            )
            if abs(formula_net - (totals.net_pay or Decimal(0))) > self.tolerance:
                okay = False
                self._exception(
                    session,
                    reconciliation,
                    "payroll_run_total_mismatch",
                    payroll_run_id=payroll.id,
                    observed=str(totals.net_pay),
                    expected=str(formula_net),
                    severity="error",
                )
        employees = [entry.employee_id for entry in entries]
        if len(employees) != len(set(employees)):
            okay = False
            self._exception(
                session,
                reconciliation,
                "duplicate_payroll_entry",
                payroll_run_id=payroll.id,
                severity="error",
            )
        return okay

    def _exception(
        self,
        session: Session,
        reconciliation: PayrollReconciliationRun,
        code: str,
        payroll_run_id: int | None = None,
        bank_id: int | None = None,
        gl_id: str | None = None,
        group_id: int | None = None,
        observed: str | None = None,
        expected: str | None = None,
        severity: str = "warning",
    ) -> None:
        session.add(
            PayrollReconciliationException(
                tenant_id=reconciliation.tenant_id,
                payroll_reconciliation_run_id=reconciliation.id,
                reconciliation_version=reconciliation.reconciliation_version,
                exception_code=code,
                exception_type=code.split("_")[0],
                severity=severity,
                payroll_run_id=payroll_run_id,
                bank_transaction_id=bank_id,
                gl_record_id=gl_id,
                reconciliation_group_id=group_id,
                message=code.replace("_", " ").capitalize(),
                observed_value=observed,
                expected_value=expected,
                status="open",
                exception_fingerprint=stable_fingerprint(
                    {"code": code, "payroll": payroll_run_id, "bank": bank_id, "gl": gl_id}
                ),
                metadata_json={},
            )
        )

    def _controls(
        self,
        session: Session,
        reconciliation: PayrollReconciliationRun,
        payroll_runs: list[PayrollRun],
        totals: dict[int, PayrollTotals],
        bank: list[BankWithdrawal],
        gl: list[PayrollGLLine],
    ) -> None:
        groups = list(
            session.scalars(
                select(PayrollReconciliationGroup).where(
                    PayrollReconciliationGroup.payroll_reconciliation_run_id == reconciliation.id
                )
            )
        )
        exceptions = list(
            session.scalars(
                select(PayrollReconciliationException).where(
                    PayrollReconciliationException.payroll_reconciliation_run_id
                    == reconciliation.id
                )
            )
        )
        allocations = list(
            session.scalars(
                select(PayrollReconciliationAllocation).where(
                    PayrollReconciliationAllocation.payroll_reconciliation_run_id
                    == reconciliation.id
                )
            )
        )
        reconciliation.gross_pay_total = sum(
            (value.gross_pay or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.employee_tax_total = sum(
            (value.employee_tax or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.employee_deduction_total = sum(
            (value.employee_deduction or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.employer_tax_total = sum(
            (value.employer_tax or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.employer_contribution_total = sum(
            (value.employer_contribution or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.reimbursement_total = sum(
            (value.reimbursement or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.net_pay_total = sum(
            (value.net_pay or Decimal(0) for value in totals.values()), Decimal(0)
        )
        reconciliation.bank_withdrawal_total = sum((item.amount for item in bank), Decimal(0))
        reconciliation.gl_payroll_expense_total = sum((item.debit for item in gl), Decimal(0))
        reconciliation.gl_payroll_liability_total = sum((item.credit for item in gl), Decimal(0))
        reconciliation.automatically_matched_count = sum(
            item.status in {"matched", "resolved"} and item.auto_accepted for item in groups
        )
        reconciliation.suggested_match_count = sum(
            item.status in {"suggested", "needs_review", "reopened"} for item in groups
        )
        reconciliation.partially_matched_count = sum(
            item.status == "partially_matched" for item in groups
        )
        reconciliation.unmatched_payroll_count = sum(
            item.status not in {"matched", "resolved"} for item in groups
        )
        reconciliation.unmatched_bank_count = sum(
            item.exception_code == "unmatched_bank_withdrawal" for item in exceptions
        )
        reconciliation.unmatched_gl_count = sum(
            item.exception_code == "unmatched_payroll_gl" for item in exceptions
        )
        reconciliation.exception_count = len(exceptions)
        full_ids = {
            item.payroll_run_id for item in groups if item.status in {"matched", "resolved"}
        }
        reconciliation.matched_amount_total = sum(
            (
                expected_settlement(item, totals[item.id], reconciliation.settlement_model)
                for item in payroll_runs
                if item.id in full_ids
            ),
            Decimal(0),
        )
        reconciliation.reconciliation_rate = (
            Decimal(len(full_ids)) / Decimal(max(1, len(payroll_runs)))
        ).quantize(Decimal("0.000001"))
        session.execute(
            delete(PayrollReconciliationControlTotal).where(
                PayrollReconciliationControlTotal.payroll_reconciliation_run_id == reconciliation.id
            )
        )
        controls: dict[str, tuple[Decimal | None, Decimal | None, Decimal | None]] = {
            "payroll_entry_count": (
                Decimal(reconciliation.included_payroll_entry_count),
                None,
                None,
            ),
            "gross_pay_total": (
                reconciliation.gross_pay_total,
                None,
                reconciliation.gl_payroll_expense_total,
            ),
            "employee_tax_total": (
                reconciliation.employee_tax_total
                if any(v.employee_tax is not None for v in totals.values())
                else None,
                None,
                None,
            ),
            "employee_deduction_total": (
                reconciliation.employee_deduction_total
                if any(v.employee_deduction is not None for v in totals.values())
                else None,
                None,
                None,
            ),
            "employer_tax_total": (
                reconciliation.employer_tax_total
                if any(v.employer_tax is not None for v in totals.values())
                else None,
                None,
                None,
            ),
            "employer_contribution_total": (
                reconciliation.employer_contribution_total
                if any(v.employer_contribution is not None for v in totals.values())
                else None,
                None,
                None,
            ),
            "reimbursement_total": (
                reconciliation.reimbursement_total
                if any(v.reimbursement is not None for v in totals.values())
                else None,
                None,
                None,
            ),
            "net_pay_total": (
                reconciliation.net_pay_total,
                reconciliation.bank_withdrawal_total,
                None,
            ),
            "bank_withdrawal_total": (
                reconciliation.net_pay_total,
                reconciliation.bank_withdrawal_total,
                None,
            ),
            "gl_payroll_expense_total": (
                reconciliation.gross_pay_total + reconciliation.employer_contribution_total,
                None,
                reconciliation.gl_payroll_expense_total,
            ),
            "gl_payroll_liability_total": (
                reconciliation.gross_pay_total + reconciliation.employer_contribution_total,
                None,
                reconciliation.gl_payroll_liability_total,
            ),
            "gl_cash_total": (None, reconciliation.bank_withdrawal_total, None),
            "payroll_to_bank_difference": (
                reconciliation.net_pay_total,
                reconciliation.bank_withdrawal_total,
                None,
            ),
            "payroll_to_gl_difference": (
                reconciliation.gross_pay_total + reconciliation.employer_contribution_total,
                None,
                reconciliation.gl_payroll_expense_total,
            ),
            "bank_to_gl_difference": (
                None,
                reconciliation.bank_withdrawal_total,
                reconciliation.gl_payroll_liability_total,
            ),
            "allocation_balance": (
                reconciliation.matched_amount_total,
                sum(
                    (a.allocated_amount for a in allocations if a.bank_transaction_id is not None),
                    Decimal(0),
                ),
                None,
            ),
            "reconciliation_rate": (reconciliation.reconciliation_rate, None, None),
        }
        for name, (payroll_value, bank_value, gl_value) in controls.items():
            comparable = bank_value if bank_value is not None else gl_value
            difference = (
                payroll_value - comparable
                if payroll_value is not None and comparable is not None
                else None
            )
            status = (
                "unavailable"
                if payroll_value is None
                else "matched"
                if difference is None or abs(difference) <= self.tolerance
                else "mismatch"
            )
            session.add(
                PayrollReconciliationControlTotal(
                    tenant_id=reconciliation.tenant_id,
                    payroll_reconciliation_run_id=reconciliation.id,
                    reconciliation_version=reconciliation.reconciliation_version,
                    control_name=name,
                    payroll_value=payroll_value,
                    bank_value=bank_value,
                    gl_value=gl_value,
                    difference_value=difference,
                    tolerance=self.tolerance,
                    status=status,
                    metadata_json={},
                )
            )

    def _reports(
        self,
        session: Session,
        tenant_code: str,
        reconciliation: PayrollReconciliationRun,
        pipeline: PipelineRun,
    ) -> None:
        root = (
            self.settings.PAYROLL_RECONCILIATION_REPORT_ROOT
            / tenant_code
            / f"run_{reconciliation.id:08d}"
        )
        root.mkdir(parents=True, exist_ok=False)
        groups = list(
            session.scalars(
                select(PayrollReconciliationGroup)
                .where(
                    PayrollReconciliationGroup.payroll_reconciliation_run_id == reconciliation.id
                )
                .order_by(PayrollReconciliationGroup.id)
            )
        )
        exceptions = list(
            session.scalars(
                select(PayrollReconciliationException)
                .where(
                    PayrollReconciliationException.payroll_reconciliation_run_id
                    == reconciliation.id
                )
                .order_by(PayrollReconciliationException.id)
            )
        )
        controls = list(
            session.scalars(
                select(PayrollReconciliationControlTotal)
                .where(
                    PayrollReconciliationControlTotal.payroll_reconciliation_run_id
                    == reconciliation.id
                )
                .order_by(PayrollReconciliationControlTotal.control_name)
            )
        )
        group_rows = [
            {
                "group_id": g.id,
                "payroll_run_id": g.payroll_run_id,
                "status": g.status,
                "payroll_total": str(g.payroll_total),
                "bank_total": str(g.bank_total),
                "gl_total": str(g.gl_total),
                "confidence": str(g.confidence),
            }
            for g in groups
        ]
        exception_rows = [
            {
                "id": e.id,
                "code": e.exception_code,
                "severity": e.severity,
                "payroll_run_id": e.payroll_run_id,
                "bank_transaction_id": e.bank_transaction_id,
                "gl_record_id": e.gl_record_id,
                "status": e.status,
            }
            for e in exceptions
        ]
        payloads: dict[str, tuple[str, Any]] = {
            "payroll_reconciliation_summary": (
                "payroll_reconciliation_summary.json",
                {
                    "run_id": reconciliation.id,
                    "version": reconciliation.reconciliation_version,
                    "settlement_model": reconciliation.settlement_model,
                    "status": "completed_with_exceptions"
                    if reconciliation.exception_count
                    else "completed",
                    "payroll_run_count": reconciliation.included_payroll_run_count,
                    "reconciliation_rate": str(reconciliation.reconciliation_rate),
                },
            ),
            "payroll_run_controls": (
                "payroll_run_controls.csv",
                [
                    {
                        "control": c.control_name,
                        "payroll": c.payroll_value,
                        "bank": c.bank_value,
                        "gl": c.gl_value,
                        "difference": c.difference_value,
                        "status": c.status,
                    }
                    for c in controls
                ],
            ),
            "payroll_bank_matches": (
                "payroll_bank_matches.csv",
                [r for r in group_rows if Decimal(str(r["bank_total"])) > 0],
            ),
            "payroll_gl_matches": (
                "payroll_gl_matches.csv",
                [r for r in group_rows if Decimal(str(r["gl_total"])) > 0],
            ),
            "payroll_suggested_matches": (
                "payroll_suggested_matches.csv",
                [r for r in group_rows if r["status"] != "matched"],
            ),
            "payroll_unmatched_runs": (
                "payroll_unmatched_runs.csv",
                [r for r in exception_rows if r["code"] == "unmatched_payroll_run"],
            ),
            "payroll_unmatched_bank": (
                "payroll_unmatched_bank.csv",
                [r for r in exception_rows if r["code"] == "unmatched_bank_withdrawal"],
            ),
            "payroll_unmatched_gl": (
                "payroll_unmatched_gl.csv",
                [r for r in exception_rows if r["code"] == "unmatched_payroll_gl"],
            ),
            "payroll_exceptions": ("payroll_exceptions.csv", exception_rows),
            "payroll_controls": (
                "payroll_controls.json",
                {
                    c.control_name: {
                        "payroll": str(c.payroll_value) if c.payroll_value is not None else None,
                        "bank": str(c.bank_value) if c.bank_value is not None else None,
                        "gl": str(c.gl_value) if c.gl_value is not None else None,
                        "status": c.status,
                    }
                    for c in controls
                },
            ),
            "payroll_duplicate_report": (
                "payroll_duplicate_report.csv",
                [r for r in exception_rows if "duplicate" in str(r["code"])],
            ),
            "payroll_reversal_report": (
                "payroll_reversal_report.csv",
                [r for r in exception_rows if "reversal" in str(r["code"])],
            ),
        }
        for report_type, (filename, payload) in payloads.items():
            path = root / filename
            if filename.endswith(".json"):
                path.write_text(
                    json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
                mime = "application/json"
            else:
                rows = payload
                headers = sorted({key for row in rows for key in row}) or ["no_records"]
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                mime = "text/csv"
            relative = path.relative_to(self.data_root).as_posix()
            checksum = self._sha(path)
            session.add(
                PayrollReconciliationReport(
                    tenant_id=reconciliation.tenant_id,
                    payroll_reconciliation_run_id=reconciliation.id,
                    reconciliation_version=reconciliation.reconciliation_version,
                    report_type=report_type,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type=mime,
                    file_size_bytes=path.stat().st_size,
                    metadata_json={"tenant": tenant_code},
                )
            )
            session.add(
                PipelineRunArtifact(
                    tenant_id=reconciliation.tenant_id,
                    pipeline_run_id=pipeline.id,
                    artifact_type="payroll_reconciliation_report",
                    name=filename,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type=mime,
                    file_size_bytes=path.stat().st_size,
                    metadata_json={"report_type": report_type},
                )
            )
        session.flush()

    def verify_integrity(
        self, session: Session, reconciliation: PayrollReconciliationRun
    ) -> dict[str, Any]:
        reports = list(
            session.scalars(
                select(PayrollReconciliationReport).where(
                    PayrollReconciliationReport.payroll_reconciliation_run_id == reconciliation.id
                )
            )
        )
        if reports and len(reports) != 12:
            raise PayrollReconciliationError(f"Expected 12 reports, found {len(reports)}")
        for report in reports:
            if Path(report.relative_path).is_absolute():
                raise PayrollReconciliationError("Absolute payroll report path stored")
            path = self.data_root / report.relative_path
            if not path.is_file() or self._sha(path) != report.checksum:
                raise PayrollReconciliationError(
                    f"Payroll report integrity failed: {report.report_type}"
                )
        over_bank = session.execute(
            select(
                PayrollReconciliationAllocation.bank_transaction_id,
                func.sum(PayrollReconciliationAllocation.allocated_amount),
            )
            .where(
                PayrollReconciliationAllocation.payroll_reconciliation_run_id == reconciliation.id,
                PayrollReconciliationAllocation.bank_transaction_id.is_not(None),
            )
            .group_by(PayrollReconciliationAllocation.bank_transaction_id)
            .having(func.count() > 1)
        ).all()
        over_gl = session.execute(
            select(PayrollReconciliationAllocation.gl_record_id)
            .where(
                PayrollReconciliationAllocation.payroll_reconciliation_run_id == reconciliation.id,
                PayrollReconciliationAllocation.gl_record_id.is_not(None),
            )
            .group_by(PayrollReconciliationAllocation.gl_record_id)
            .having(func.count() > 1)
        ).all()
        if over_bank or over_gl:
            raise PayrollReconciliationError("Payroll bank or GL allocation conflict detected")
        return {
            "payroll_reconciliation_run_id": reconciliation.id,
            "reports": len(reports),
            "integrity": "passed",
        }

    @staticmethod
    def _sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
