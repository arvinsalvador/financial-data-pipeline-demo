from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
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
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    ReconciliationAllocation,
    ReconciliationCandidate,
    ReconciliationControlTotal,
    ReconciliationException,
    ReconciliationMatch,
    ReconciliationMatchGroup,
    ReconciliationReport,
    ReconciliationRule,
    Tenant,
    ValidationIssue,
    ValidationRun,
)
from app.services.reconciliation_matching import (
    BankRecord,
    LedgerRecord,
    bounded_exact_groups,
    normalize_description,
    normalize_reference,
    score_candidate,
    stable_fingerprint,
)


class ReconciliationError(ValueError):
    pass


STEPS = (
    "resolve_inputs",
    "verify_ledger_checksum",
    "load_validation_context",
    "load_bank_transactions",
    "load_cash_ledger_entries",
    "derive_economic_direction",
    "exclude_critical_validation_failures",
    "detect_bank_duplicates",
    "detect_ledger_duplicates",
    "generate_one_to_one_candidates",
    "select_unambiguous_matches",
    "generate_grouped_candidates",
    "detect_partial_matches",
    "detect_reversals",
    "classify_unmatched_records",
    "calculate_control_totals",
    "generate_reports",
    "verify_reconciliation_integrity",
    "complete_reconciliation",
)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation as error:
        raise ReconciliationError(f"Invalid monetary amount: {value!r}") from error


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BankLedgerReconciliationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.amount_tolerance = Decimal(str(settings.RECONCILIATION_AMOUNT_TOLERANCE))

    def run(
        self,
        session: Session,
        tenant: Tenant,
        bank_account_id: int,
        date_from: date,
        date_to: date,
        generated_dataset_run_id: int | None = None,
        force_rerun: bool = False,
    ) -> tuple[BankLedgerReconciliationRun, bool]:
        if date_from > date_to:
            raise ReconciliationError("date_from must not be later than date_to")
        account = session.scalar(
            select(BankAccount).where(
                BankAccount.id == bank_account_id,
                BankAccount.tenant_id == tenant.id,
            )
        )
        if account is None:
            raise ReconciliationError("Bank account was not found for this tenant")
        financial_account = session.get(FinancialAccount, account.financial_account_id)
        if financial_account is None:
            raise ReconciliationError("The bank account has no financial account")
        generated_run, source_file = self._ledger_source(
            session, tenant.id, generated_dataset_run_id
        )
        validation_run = session.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.tenant_id == tenant.id,
                ValidationRun.generated_dataset_run_id == generated_run.id,
                ValidationRun.target_type == "generated_dataset",
                ValidationRun.status == "completed",
            )
            .order_by(ValidationRun.id.desc())
        )
        if validation_run is None:
            raise ReconciliationError(
                "A completed Phase 8 validation run is required for the generated dataset"
            )
        rules = list(
            session.scalars(
                select(ReconciliationRule)
                .where(
                    ReconciliationRule.tenant_id == tenant.id,
                    ReconciliationRule.version == self.settings.RECONCILIATION_VERSION,
                    ReconciliationRule.is_active.is_(True),
                )
                .order_by(ReconciliationRule.execution_order, ReconciliationRule.id)
            )
        )
        if not rules:
            raise ReconciliationError("Phase 9 reconciliation rules have not been seeded")
        rule_by_code = {rule.code: rule for rule in rules}
        path = self._data_root / source_file.relative_path
        if not path.is_file() or _sha256(path) != source_file.sha256_checksum:
            raise ReconciliationError("The generated general ledger checksum is invalid")
        issues = list(
            session.scalars(
                select(ValidationIssue).where(
                    ValidationIssue.validation_run_id == validation_run.id,
                    ValidationIssue.severity == "critical",
                    ValidationIssue.status == "open",
                )
            )
        )
        bank_records = self._load_bank(session, tenant.id, account.id, date_from, date_to)
        ledger_records = self._load_ledger(
            path, financial_account.account_code, date_from, date_to, issues
        )
        blocked_bank_ids = {
            int(issue.entity_key)
            for issue in issues
            if issue.entity_type in {"bank_transaction", "financial_transaction"}
            and issue.entity_key
            and issue.entity_key.isdigit()
        }
        bank_records = [
            BankRecord(
                **{
                    **record.__dict__,
                    "validation_blocked": record.bank_transaction_id in blocked_bank_ids,
                }
            )
            for record in bank_records
        ]
        ruleset_fingerprint = stable_fingerprint(
            {
                "rules": [
                    [
                        rule.code,
                        rule.version,
                        rule.execution_order,
                        rule.auto_accept,
                        str(rule.minimum_confidence),
                        rule.configuration_json,
                    ]
                    for rule in rules
                ]
            }
        )
        input_fingerprint = stable_fingerprint(
            {
                "bank_account_id": account.id,
                "date_from": date_from,
                "date_to": date_to,
                "generated_file": source_file.sha256_checksum,
                "validation": [
                    issue.issue_fingerprint for issue in sorted(issues, key=lambda item: item.id)
                ],
                "bank": [
                    [item.bank_transaction_id, item.canonical_hash, str(item.signed_amount)]
                    for item in bank_records
                ],
                "ledger": [
                    [item.ledger_record_id, item.row_hash, str(item.signed_amount)]
                    for item in ledger_records
                ],
            }
        )
        existing = session.scalar(
            select(BankLedgerReconciliationRun).where(
                BankLedgerReconciliationRun.tenant_id == tenant.id,
                BankLedgerReconciliationRun.input_fingerprint == input_fingerprint,
                BankLedgerReconciliationRun.ruleset_fingerprint == ruleset_fingerprint,
                BankLedgerReconciliationRun.reconciliation_version
                == self.settings.RECONCILIATION_VERSION,
            )
        )
        if existing is not None:
            if force_rerun:
                self.verify_integrity(session, existing)
            return existing, True
        now = datetime.now(UTC)
        definition = session.scalar(
            select(PipelineDefinition)
            .where(
                PipelineDefinition.code == "bank_ledger_reconciliation",
                PipelineDefinition.is_active.is_(True),
            )
            .order_by(PipelineDefinition.id.desc())
        )
        if definition is None:
            raise ReconciliationError("The reconciliation pipeline definition is not active")
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="bank_ledger_reconciliation",
            status="running",
            started_at=now,
            metadata_json={"version": self.settings.RECONCILIATION_VERSION},
        )
        pipeline.steps = [
            PipelineRunStep(
                step_name=name,
                step_order=order,
                status="completed" if order < len(STEPS) else "running",
                started_at=now,
                completed_at=now if order < len(STEPS) else None,
            )
            for order, name in enumerate(STEPS, 1)
        ]
        session.add(pipeline)
        session.flush()
        run = BankLedgerReconciliationRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            reconciliation_version=self.settings.RECONCILIATION_VERSION,
            status="running",
            date_from=date_from,
            date_to=date_to,
            bank_account_id=account.id,
            generated_source_file_id=source_file.id,
            validation_run_id=validation_run.id,
            included_bank_transaction_count=len(bank_records),
            included_ledger_line_count=len(ledger_records),
            input_fingerprint=input_fingerprint,
            ruleset_fingerprint=ruleset_fingerprint,
            started_at=now,
            metadata_json={
                "generated_dataset_run_id": generated_run.id,
                "ledger_filename": source_file.filename,
                "cash_account_code": financial_account.account_code,
                "validation_critical_issue_count": len(issues),
            },
        )
        session.add(run)
        session.flush()
        self._reconcile(session, run, bank_records, ledger_records, rule_by_code, issues)
        session.flush()
        self.refresh_controls(session, run, bank_records, ledger_records)
        self._reports(session, run, pipeline, bank_records, ledger_records)
        self.verify_integrity(session, run)
        completed = datetime.now(UTC)
        run.status = "completed"
        run.completed_at = completed
        pipeline.status = "completed"
        pipeline.completed_at = completed
        pipeline.records_extracted = len(bank_records) + len(ledger_records)
        pipeline.records_accepted = run.automatically_matched_count
        pipeline.steps[-1].status = "completed"
        pipeline.steps[-1].completed_at = completed
        session.commit()
        session.refresh(run)
        return run, False

    @property
    def _data_root(self) -> Path:
        return self.settings.GENERATED_DATA_DIRECTORY.parent

    def _ledger_source(
        self, session: Session, tenant_id: int, generated_dataset_run_id: int | None
    ) -> tuple[GeneratedDatasetRun, GeneratedSourceFile]:
        conditions = [
            GeneratedDatasetRun.tenant_id == tenant_id,
            GeneratedDatasetRun.status == "completed",
        ]
        if generated_dataset_run_id is not None:
            conditions.append(GeneratedDatasetRun.id == generated_dataset_run_id)
        statement = select(GeneratedDatasetRun).where(*conditions)
        if generated_dataset_run_id is None:
            statement = statement.join(
                ValidationRun,
                ValidationRun.generated_dataset_run_id == GeneratedDatasetRun.id,
            ).where(
                ValidationRun.target_type == "generated_dataset",
                ValidationRun.status == "completed",
            )
        run = session.scalar(statement.order_by(GeneratedDatasetRun.id.desc()))
        if run is None:
            raise ReconciliationError("No completed generated dataset is available")
        source = session.scalar(
            select(GeneratedSourceFile).where(
                GeneratedSourceFile.generated_dataset_run_id == run.id,
                GeneratedSourceFile.file_type == "general_ledger",
            )
        )
        if source is None:
            raise ReconciliationError("The generated dataset has no general ledger file")
        return run, source

    def _load_bank(
        self, session: Session, tenant_id: int, account_id: int, start: date, end: date
    ) -> list[BankRecord]:
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
        result: list[BankRecord] = []
        previous_balance: Decimal | None = None
        negative_words = ("payment", "purchase", "rent", "utility", "payroll", "fee", "withdrawal")
        for bank, transaction in rows:
            signed = _decimal(transaction.amount)
            if bank.credit_amount is not None and _decimal(bank.credit_amount) != 0:
                signed = abs(_decimal(bank.credit_amount))
            elif bank.debit_amount is not None and _decimal(bank.debit_amount) != 0:
                signed = -abs(_decimal(bank.debit_amount))
            elif bank.running_balance is not None and previous_balance is not None:
                delta = _decimal(bank.running_balance) - previous_balance
                signed = abs(signed) if delta >= 0 else -abs(signed)
            elif any(word in (transaction.description or "").casefold() for word in negative_words):
                signed = -abs(signed)
            else:
                signed = abs(signed)
            if bank.running_balance is not None:
                previous_balance = _decimal(bank.running_balance)
            if start <= transaction.transaction_date <= end and signed != 0:
                result.append(
                    BankRecord(
                        bank.id,
                        transaction.id,
                        transaction.transaction_date,
                        _money(signed),
                        transaction.reference_number or transaction.source_record_id or "",
                        transaction.description or "",
                        transaction.canonical_hash,
                        transaction.source_row_number,
                    )
                )
        return result

    def _load_ledger(
        self, path: Path, account_code: str, start: date, end: date, issues: list[ValidationIssue]
    ) -> list[LedgerRecord]:
        blocked_rows = {
            issue.row_number
            for issue in issues
            if issue.row_number is not None and issue.filename == path.name
        }
        result: list[LedgerRecord] = []
        seen_ids: Counter[str] = Counter()
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                if row.get("account_code") != account_code:
                    continue
                entry_date = date.fromisoformat(row.get("posting_date") or row["entry_date"])
                if not start <= entry_date <= end:
                    continue
                amount = _money(_decimal(row.get("debit")) - _decimal(row.get("credit")))
                if amount == 0:
                    continue
                record_id = row.get("journal_line_id") or f"row-{row_number}"
                seen_ids[record_id] += 1
                if seen_ids[record_id] > 1:
                    record_id = f"{record_id}#{seen_ids[record_id]}"
                row_hash = stable_fingerprint({key: row[key] for key in sorted(row)})
                result.append(
                    LedgerRecord(
                        record_id,
                        row_number,
                        entry_date,
                        amount,
                        row.get("reference_number") or "",
                        row.get("description") or "",
                        row.get("journal_entry_id") or "",
                        account_code,
                        row_hash,
                        row_number in blocked_rows,
                    )
                )
        return result

    def _reconcile(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
        rules: dict[str, ReconciliationRule],
        issues: list[ValidationIssue],
    ) -> None:
        for bank in banks:
            if bank.validation_blocked:
                self._exception(
                    session, run, "blocked_by_validation", "validation", "critical", bank=bank
                )
        for ledger in ledgers:
            if ledger.validation_blocked:
                self._exception(
                    session, run, "blocked_by_validation", "validation", "critical", ledger=ledger
                )
        bank_duplicate_ids = self._detect_bank_duplicates(session, run, banks, rules)
        ledger_duplicate_ids = self._detect_ledger_duplicates(session, run, ledgers, rules)
        eligible_banks = [
            b
            for b in banks
            if not b.validation_blocked and b.bank_transaction_id not in bank_duplicate_ids
        ]
        eligible_ledgers = [
            ledger
            for ledger in ledgers
            if not ledger.validation_blocked and ledger.ledger_record_id not in ledger_duplicate_ids
        ]
        candidates: list[tuple[BankRecord, LedgerRecord, ReconciliationCandidate]] = []
        for bank in eligible_banks:
            ranked: list[tuple[Any, LedgerRecord]] = []
            for ledger in eligible_ledgers:
                score = score_candidate(
                    bank,
                    ledger,
                    self.settings.RECONCILIATION_DATE_TOLERANCE_DAYS,
                    self.amount_tolerance,
                )
                if score is not None:
                    ranked.append((score, ledger))
            ranked.sort(
                key=lambda item: (
                    -item[0].confidence,
                    item[0].date_difference_days,
                    item[1].ledger_record_id,
                )
            )
            for score, ledger in ranked[: self.settings.RECONCILIATION_MAX_CANDIDATES_PER_RECORD]:
                rule = rules[score.rule_code]
                candidate = ReconciliationCandidate(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_rule_id=rule.id,
                    reconciliation_version=run.reconciliation_version,
                    bank_transaction_id=bank.bank_transaction_id,
                    ledger_record_id=ledger.ledger_record_id,
                    candidate_type="one_to_one",
                    amount_difference=score.amount_difference,
                    date_difference_days=score.date_difference_days,
                    reference_score=score.reference_score,
                    description_score=score.description_score,
                    amount_score=score.amount_score,
                    date_score=score.date_score,
                    total_confidence=score.confidence,
                    candidate_status="pending",
                    reason_json=score.reasons,
                    candidate_fingerprint=stable_fingerprint(
                        {
                            "bank": bank.bank_transaction_id,
                            "ledger": ledger.ledger_record_id,
                            "rule": score.rule_code,
                        }
                    ),
                )
                session.add(candidate)
                session.flush()
                candidates.append((bank, ledger, candidate))
        bank_counts = Counter(item[0].bank_transaction_id for item in candidates)
        ledger_counts = Counter(item[1].ledger_record_id for item in candidates)
        used_banks: set[int] = set()
        used_ledgers: set[str] = set()
        for bank, ledger, candidate in sorted(
            candidates,
            key=lambda item: (
                -item[2].total_confidence,
                item[0].bank_transaction_id,
                item[1].ledger_record_id,
            ),
        ):
            if bank.bank_transaction_id in used_banks or ledger.ledger_record_id in used_ledgers:
                candidate.candidate_status = "superseded"
                continue
            rule = next(
                value for value in rules.values() if value.id == candidate.reconciliation_rule_id
            )
            unique = (
                bank_counts[bank.bank_transaction_id] == 1
                and ledger_counts[ledger.ledger_record_id] == 1
            )
            auto = bool(
                rule.auto_accept
                and unique
                and candidate.total_confidence
                >= Decimal(str(self.settings.RECONCILIATION_MIN_AUTO_ACCEPT_CONFIDENCE))
            )
            candidate.candidate_status = "accepted" if auto else "suggested"
            group = self._group(
                session,
                run,
                rule,
                "one_to_one",
                "matched" if auto else "suggested",
                candidate.total_confidence,
                [bank],
                [ledger],
                auto,
            )
            self._match(session, run, group, bank, ledger, candidate, rule.code)
            if auto:
                self._allocation(
                    session,
                    run,
                    group,
                    bank,
                    ledger,
                    min(abs(bank.signed_amount), abs(ledger.signed_amount)),
                )
                used_banks.add(bank.bank_transaction_id)
                used_ledgers.add(ledger.ledger_record_id)
        remaining_banks = [b for b in eligible_banks if b.bank_transaction_id not in used_banks]
        remaining_ledgers = [
            ledger for ledger in eligible_ledgers if ledger.ledger_record_id not in used_ledgers
        ]
        self._grouped(session, run, remaining_banks, remaining_ledgers, rules)
        self._partials(session, run, remaining_banks, remaining_ledgers, rules)
        self._reversals(session, run, remaining_banks, remaining_ledgers, rules)
        grouped_bank_ids, grouped_ledger_ids = self._accepted_members(session, run.id)
        for bank in banks:
            if bank.bank_transaction_id not in grouped_bank_ids and not bank.validation_blocked:
                self._exception(
                    session, run, "unmatched_bank_transaction", "unmatched", "warning", bank=bank
                )
        for ledger in ledgers:
            if ledger.ledger_record_id not in grouped_ledger_ids and not ledger.validation_blocked:
                self._exception(
                    session, run, "unmatched_ledger_entry", "unmatched", "warning", ledger=ledger
                )

    def _detect_bank_duplicates(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord],
        rules: dict[str, ReconciliationRule],
    ) -> set[int]:
        grouped: defaultdict[tuple[Any, ...], list[BankRecord]] = defaultdict(list)
        for bank in banks:
            grouped[
                (
                    bank.transaction_date,
                    bank.signed_amount,
                    normalize_reference(bank.reference),
                    normalize_description(bank.description),
                )
            ].append(bank)
        duplicates: set[int] = set()
        for records in grouped.values():
            if len(records) < 2:
                continue
            for bank in records[1:]:
                duplicates.add(bank.bank_transaction_id)
                self._exception(
                    session, run, "duplicate_bank_record", "duplicate", "error", bank=bank
                )
                self._candidate_marker(
                    session, run, rules["duplicate_bank_detection"], bank, None, "duplicate"
                )
        return duplicates

    def _detect_ledger_duplicates(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        ledgers: list[LedgerRecord],
        rules: dict[str, ReconciliationRule],
    ) -> set[str]:
        seen: set[tuple[str, str]] = set()
        duplicates: set[str] = set()
        for ledger in ledgers:
            key = (ledger.journal_entry_id, ledger.ledger_record_id.split("#")[0])
            if key in seen:
                duplicates.add(ledger.ledger_record_id)
                self._exception(
                    session, run, "duplicate_ledger_record", "duplicate", "error", ledger=ledger
                )
                self._candidate_marker(
                    session, run, rules["duplicate_ledger_detection"], None, ledger, "duplicate"
                )
            seen.add(key)
        return duplicates

    def _grouped(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
        rules: dict[str, ReconciliationRule],
    ) -> None:
        claimed_banks: set[int] = set()
        claimed_ledgers: set[str] = set()
        ledger_tuples = [
            (item.ledger_record_id, item.signed_amount, item.entry_date) for item in ledgers
        ]
        ledger_by_id = {item.ledger_record_id: item for item in ledgers}
        for bank in banks:
            groups = bounded_exact_groups(
                bank.signed_amount,
                ledger_tuples,
                bank.transaction_date,
                self.settings.RECONCILIATION_MAX_GROUP_SIZE,
                self.settings.RECONCILIATION_DATE_TOLERANCE_DAYS,
                self.amount_tolerance,
            )
            if len(groups) == 1 and not (set(groups[0]) & claimed_ledgers):
                ledger_members = [ledger_by_id[key] for key in groups[0]]
                rule = rules["one_bank_to_many_ledger"]
                group = self._group(
                    session,
                    run,
                    rule,
                    "one_to_many",
                    "suggested",
                    Decimal("0.900000"),
                    [bank],
                    ledger_members,
                    False,
                )
                for ledger in ledger_members:
                    self._match(
                        session,
                        run,
                        group,
                        bank,
                        ledger,
                        None,
                        rule.code,
                        abs(ledger.signed_amount),
                    )
                claimed_banks.add(bank.bank_transaction_id)
                claimed_ledgers.update(groups[0])
        bank_tuples = [
            (str(item.bank_transaction_id), item.signed_amount, item.transaction_date)
            for item in banks
            if item.bank_transaction_id not in claimed_banks
        ]
        bank_by_id = {str(item.bank_transaction_id): item for item in banks}
        for ledger in ledgers:
            if ledger.ledger_record_id in claimed_ledgers:
                continue
            groups = bounded_exact_groups(
                ledger.signed_amount,
                bank_tuples,
                ledger.entry_date,
                self.settings.RECONCILIATION_MAX_GROUP_SIZE,
                self.settings.RECONCILIATION_DATE_TOLERANCE_DAYS,
                self.amount_tolerance,
            )
            if len(groups) == 1:
                bank_members = [bank_by_id[key] for key in groups[0]]
                rule = rules["many_bank_to_one_ledger"]
                group = self._group(
                    session,
                    run,
                    rule,
                    "many_to_one",
                    "suggested",
                    Decimal("0.900000"),
                    bank_members,
                    [ledger],
                    False,
                )
                for bank in bank_members:
                    self._match(
                        session, run, group, bank, ledger, None, rule.code, abs(bank.signed_amount)
                    )

    def _partials(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
        rules: dict[str, ReconciliationRule],
    ) -> None:
        grouped_bank_ids, grouped_ledger_ids = self._all_group_members(session, run.id)
        available_ledgers = [
            item for item in ledgers if item.ledger_record_id not in grouped_ledger_ids
        ]
        used_ledgers: set[str] = set()
        minimum = Decimal(str(self.settings.RECONCILIATION_PARTIAL_MATCH_MINIMUM_AMOUNT))
        for bank in banks:
            if bank.bank_transaction_id in grouped_bank_ids:
                continue
            options = [
                ledger
                for ledger in available_ledgers
                if ledger.ledger_record_id not in used_ledgers
                and bank.signed_amount * ledger.signed_amount > 0
                and abs((bank.transaction_date - ledger.entry_date).days)
                <= self.settings.RECONCILIATION_DATE_TOLERANCE_DAYS
                and min(abs(bank.signed_amount), abs(ledger.signed_amount)) >= minimum
            ]
            if not options:
                continue
            ledger = min(
                options,
                key=lambda item: (
                    abs(abs(bank.signed_amount) - abs(item.signed_amount)),
                    abs((bank.transaction_date - item.entry_date).days),
                    item.ledger_record_id,
                ),
            )
            rule = rules["exact_amount_date_tolerance"]
            matched = min(abs(bank.signed_amount), abs(ledger.signed_amount))
            confidence = (
                matched / max(abs(bank.signed_amount), abs(ledger.signed_amount))
            ).quantize(Decimal("0.000001"))
            group = self._group(
                session,
                run,
                rule,
                "partial",
                "partially_matched",
                confidence,
                [bank],
                [ledger],
                False,
            )
            self._match(session, run, group, bank, ledger, None, rule.code, matched)
            session.add(
                ReconciliationException(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    exception_code="partial_match",
                    exception_type="partial",
                    severity="warning",
                    bank_transaction_id=bank.bank_transaction_id,
                    ledger_record_id=ledger.ledger_record_id,
                    match_group_id=group.id,
                    message="Amounts partially cover one another and require review",
                    observed_value=str(matched),
                    expected_value=str(max(abs(bank.signed_amount), abs(ledger.signed_amount))),
                    status="open",
                    exception_fingerprint=stable_fingerprint(
                        {
                            "code": "partial_match",
                            "bank": bank.bank_transaction_id,
                            "ledger": ledger.ledger_record_id,
                        }
                    ),
                    metadata_json={"coverage": str(confidence)},
                )
            )
            used_ledgers.add(ledger.ledger_record_id)

    def _reversals(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
        rules: dict[str, ReconciliationRule],
    ) -> None:
        for bank in banks:
            for ledger in ledgers:
                if (
                    abs(abs(bank.signed_amount) - abs(ledger.signed_amount)) > self.amount_tolerance
                    or bank.signed_amount * ledger.signed_amount >= 0
                ):
                    continue
                if (
                    abs((bank.transaction_date - ledger.entry_date).days)
                    > self.settings.RECONCILIATION_REVERSAL_DATE_TOLERANCE_DAYS
                ):
                    continue
                if normalize_reference(bank.reference) != normalize_reference(ledger.reference):
                    continue
                self._exception(
                    session,
                    run,
                    "reversal_candidate",
                    "reversal",
                    "warning",
                    bank=bank,
                    ledger=ledger,
                )
                self._candidate_marker(
                    session, run, rules["reversed_transaction_detection"], bank, ledger, "reversal"
                )

    def _candidate_marker(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        rule: ReconciliationRule,
        bank: BankRecord | None,
        ledger: LedgerRecord | None,
        candidate_type: str,
    ) -> None:
        session.add(
            ReconciliationCandidate(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                reconciliation_rule_id=rule.id,
                reconciliation_version=run.reconciliation_version,
                bank_transaction_id=bank.bank_transaction_id if bank else None,
                ledger_record_id=ledger.ledger_record_id if ledger else None,
                candidate_type=candidate_type,
                amount_difference=0,
                date_difference_days=None,
                reference_score=1,
                description_score=0,
                amount_score=1,
                date_score=0,
                total_confidence=rule.minimum_confidence,
                candidate_status="needs_review",
                reason_json={"deterministic_rule": rule.code},
                candidate_fingerprint=stable_fingerprint(
                    {
                        "rule": rule.code,
                        "bank": bank.bank_transaction_id if bank else None,
                        "ledger": ledger.ledger_record_id if ledger else None,
                    }
                ),
            )
        )

    def _group(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        rule: ReconciliationRule,
        group_type: str,
        status: str,
        confidence: Decimal,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
        auto: bool,
    ) -> ReconciliationMatchGroup:
        bank_total = sum((abs(item.signed_amount) for item in banks), Decimal(0))
        ledger_total = sum((abs(item.signed_amount) for item in ledgers), Decimal(0))
        metadata = {
            "bank_records": [self._bank_json(item) for item in banks],
            "ledger_records": [self._ledger_json(item) for item in ledgers],
        }
        group = ReconciliationMatchGroup(
            tenant_id=run.tenant_id,
            reconciliation_run_id=run.id,
            reconciliation_rule_id=rule.id,
            reconciliation_version=run.reconciliation_version,
            group_type=group_type,
            status=status,
            confidence=confidence,
            matched_amount=min(bank_total, ledger_total),
            bank_total=bank_total,
            ledger_total=ledger_total,
            difference_amount=abs(bank_total - ledger_total),
            auto_accepted=auto,
            group_fingerprint=stable_fingerprint(
                {
                    "type": group_type,
                    "banks": [b.bank_transaction_id for b in banks],
                    "ledger": [ledger.ledger_record_id for ledger in ledgers],
                }
            ),
            metadata_json=metadata,
        )
        session.add(group)
        session.flush()
        return group

    def _match(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        group: ReconciliationMatchGroup,
        bank: BankRecord,
        ledger: LedgerRecord,
        candidate: ReconciliationCandidate | None,
        rule_code: str,
        amount: Decimal | None = None,
    ) -> None:
        session.add(
            ReconciliationMatch(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                match_group_id=group.id,
                bank_transaction_id=bank.bank_transaction_id,
                ledger_record_id=ledger.ledger_record_id,
                candidate_id=candidate.id if candidate else None,
                matched_amount=amount or min(abs(bank.signed_amount), abs(ledger.signed_amount)),
                confidence=group.confidence,
                status=group.status,
                rule_code=rule_code,
            )
        )

    def _allocation(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        group: ReconciliationMatchGroup,
        bank: BankRecord,
        ledger: LedgerRecord,
        amount: Decimal,
    ) -> None:
        session.add(
            ReconciliationAllocation(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                match_group_id=group.id,
                bank_transaction_id=bank.bank_transaction_id,
                ledger_record_id=ledger.ledger_record_id,
                allocated_amount=amount,
                allocation_direction="inflow" if bank.signed_amount > 0 else "outflow",
            )
        )

    def _exception(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        code: str,
        exception_type: str,
        severity: str,
        bank: BankRecord | None = None,
        ledger: LedgerRecord | None = None,
    ) -> None:
        identity = {
            "code": code,
            "bank": bank.bank_transaction_id if bank else None,
            "ledger": ledger.ledger_record_id if ledger else None,
        }
        session.add(
            ReconciliationException(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                exception_code=code,
                exception_type=exception_type,
                severity=severity,
                bank_transaction_id=bank.bank_transaction_id if bank else None,
                ledger_record_id=ledger.ledger_record_id if ledger else None,
                message=code.replace("_", " ").capitalize(),
                status="open",
                exception_fingerprint=stable_fingerprint(identity),
                metadata_json={
                    "bank": self._bank_json(bank) if bank else None,
                    "ledger": self._ledger_json(ledger) if ledger else None,
                },
            )
        )

    @staticmethod
    def _bank_json(record: BankRecord) -> dict[str, Any]:
        return {
            "id": record.bank_transaction_id,
            "date": record.transaction_date.isoformat(),
            "signed_amount": str(record.signed_amount),
            "reference": record.reference,
            "description": record.description,
        }

    @staticmethod
    def _ledger_json(record: LedgerRecord) -> dict[str, Any]:
        return {
            "id": record.ledger_record_id,
            "row_number": record.row_number,
            "date": record.entry_date.isoformat(),
            "signed_amount": str(record.signed_amount),
            "reference": record.reference,
            "description": record.description,
        }

    def _accepted_members(self, session: Session, run_id: int) -> tuple[set[int], set[str]]:
        rows = session.execute(
            select(ReconciliationMatch.bank_transaction_id, ReconciliationMatch.ledger_record_id)
            .join(
                ReconciliationMatchGroup,
                ReconciliationMatchGroup.id == ReconciliationMatch.match_group_id,
            )
            .where(
                ReconciliationMatch.reconciliation_run_id == run_id,
                ReconciliationMatchGroup.status.in_(("matched", "resolved")),
            )
        ).all()
        return {row[0] for row in rows}, {row[1] for row in rows}

    def _all_group_members(self, session: Session, run_id: int) -> tuple[set[int], set[str]]:
        rows = session.execute(
            select(
                ReconciliationMatch.bank_transaction_id,
                ReconciliationMatch.ledger_record_id,
            ).where(ReconciliationMatch.reconciliation_run_id == run_id)
        ).all()
        return {row[0] for row in rows}, {row[1] for row in rows}

    def refresh_controls(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        banks: list[BankRecord] | None = None,
        ledgers: list[LedgerRecord] | None = None,
    ) -> None:
        groups = list(
            session.scalars(
                select(ReconciliationMatchGroup).where(
                    ReconciliationMatchGroup.reconciliation_run_id == run.id
                )
            )
        )
        allocations = list(
            session.scalars(
                select(ReconciliationAllocation).where(
                    ReconciliationAllocation.reconciliation_run_id == run.id
                )
            )
        )
        exceptions = list(
            session.scalars(
                select(ReconciliationException).where(
                    ReconciliationException.reconciliation_run_id == run.id
                )
            )
        )
        matched_groups = [group for group in groups if group.status in {"matched", "resolved"}]
        matched_bank_ids, matched_ledger_ids = self._accepted_members(session, run.id)
        run.automatically_matched_count = sum(group.auto_accepted for group in matched_groups)
        run.suggested_match_count = sum(
            group.status in {"suggested", "needs_review", "reopened"} for group in groups
        )
        run.partially_matched_count = sum(group.status == "partially_matched" for group in groups)
        run.unmatched_bank_count = max(
            0, run.included_bank_transaction_count - len(matched_bank_ids)
        )
        run.unmatched_ledger_count = max(
            0, run.included_ledger_line_count - len(matched_ledger_ids)
        )
        run.duplicate_count = sum(item.exception_type == "duplicate" for item in exceptions)
        run.reversal_count = sum(item.exception_type == "reversal" for item in exceptions)
        run.exception_count = len(exceptions)
        if banks is not None:
            run.total_bank_amount = _money(
                sum((abs(item.signed_amount) for item in banks), Decimal(0))
            )
            run.total_unmatched_bank_amount = _money(
                sum(
                    (
                        abs(item.signed_amount)
                        for item in banks
                        if item.bank_transaction_id not in matched_bank_ids
                    ),
                    Decimal(0),
                )
            )
        if ledgers is not None:
            run.total_ledger_amount = _money(
                sum((abs(item.signed_amount) for item in ledgers), Decimal(0))
            )
            run.total_unmatched_ledger_amount = _money(
                sum(
                    (
                        abs(item.signed_amount)
                        for item in ledgers
                        if item.ledger_record_id not in matched_ledger_ids
                    ),
                    Decimal(0),
                )
            )
        run.total_matched_amount = _money(
            sum((item.allocated_amount for item in allocations), Decimal(0))
        )
        denominator = max(run.total_bank_amount, run.total_ledger_amount, Decimal(1))
        run.reconciliation_rate = min(Decimal(1), run.total_matched_amount / denominator).quantize(
            Decimal("0.000001")
        )
        session.execute(
            delete(ReconciliationControlTotal).where(
                ReconciliationControlTotal.reconciliation_run_id == run.id
            )
        )
        values = {
            "eligible_bank_record_count": (
                run.included_bank_transaction_count,
                len(matched_bank_ids),
            ),
            "eligible_ledger_record_count": (
                run.included_ledger_line_count,
                len(matched_ledger_ids),
            ),
            "bank_amount": (run.total_bank_amount, run.total_matched_amount),
            "ledger_amount": (run.total_ledger_amount, run.total_matched_amount),
            "matched_amount": (run.total_matched_amount, run.total_matched_amount),
            "unmatched_bank_amount": (
                run.total_bank_amount,
                run.total_bank_amount - run.total_unmatched_bank_amount,
            ),
            "unmatched_ledger_amount": (
                run.total_ledger_amount,
                run.total_ledger_amount - run.total_unmatched_ledger_amount,
            ),
            "allocation_balance": (
                run.total_matched_amount,
                sum((item.allocated_amount for item in allocations), Decimal(0)),
            ),
            "duplicate_count": (run.duplicate_count, run.duplicate_count),
            "reversal_count": (run.reversal_count, run.reversal_count),
            "automatic_match_rate": (
                1,
                Decimal(run.automatically_matched_count) / Decimal(max(1, len(groups))),
            ),
            "overall_reconciliation_rate": (1, run.reconciliation_rate),
            "exception_count": (run.exception_count, run.exception_count),
        }
        for name, (source, matched) in values.items():
            source_value, matched_value = Decimal(str(source)), Decimal(str(matched))
            difference = source_value - matched_value
            session.add(
                ReconciliationControlTotal(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    control_name=name,
                    source_value=source_value,
                    matched_value=matched_value,
                    unmatched_value=max(Decimal(0), difference),
                    difference_value=difference,
                    tolerance=self.amount_tolerance,
                    status="passed"
                    if abs(difference) <= self.amount_tolerance
                    or name.startswith(("unmatched", "automatic", "overall"))
                    else "attention",
                )
            )
        session.flush()

    def _reports(
        self,
        session: Session,
        run: BankLedgerReconciliationRun,
        pipeline: PipelineRun,
        banks: list[BankRecord],
        ledgers: list[LedgerRecord],
    ) -> None:
        root = self.settings.RECONCILIATION_REPORT_ROOT / f"run_{run.id:08d}"
        root.mkdir(parents=True, exist_ok=False)
        controls = list(
            session.scalars(
                select(ReconciliationControlTotal)
                .where(ReconciliationControlTotal.reconciliation_run_id == run.id)
                .order_by(ReconciliationControlTotal.control_name)
            )
        )
        groups = list(
            session.scalars(
                select(ReconciliationMatchGroup)
                .where(ReconciliationMatchGroup.reconciliation_run_id == run.id)
                .order_by(ReconciliationMatchGroup.id)
            )
        )
        exceptions = list(
            session.scalars(
                select(ReconciliationException)
                .where(ReconciliationException.reconciliation_run_id == run.id)
                .order_by(ReconciliationException.id)
            )
        )
        files: dict[str, tuple[str, list[dict[str, Any]] | dict[str, Any]]] = {
            "reconciliation_summary": (
                "reconciliation_summary.json",
                {
                    "version": run.reconciliation_version,
                    "run_id": run.id,
                    "status": "completed",
                    "bank_count": run.included_bank_transaction_count,
                    "ledger_count": run.included_ledger_line_count,
                    "reconciliation_rate": str(run.reconciliation_rate),
                },
            ),
            "matched_records": (
                "matched_records.csv",
                [
                    {
                        "group_id": group.id,
                        "type": group.group_type,
                        "status": group.status,
                        "amount": str(group.matched_amount),
                        "confidence": str(group.confidence),
                    }
                    for group in groups
                    if group.status in {"matched", "resolved"}
                ],
            ),
            "suggested_matches": (
                "suggested_matches.csv",
                [
                    {
                        "group_id": group.id,
                        "type": group.group_type,
                        "status": group.status,
                        "amount": str(group.matched_amount),
                        "confidence": str(group.confidence),
                    }
                    for group in groups
                    if group.status not in {"matched", "resolved", "rejected"}
                ],
            ),
            "unmatched_bank": (
                "unmatched_bank.csv",
                [
                    self._bank_json(item)
                    for item in banks
                    if any(
                        exc.bank_transaction_id == item.bank_transaction_id
                        and exc.exception_code == "unmatched_bank_transaction"
                        for exc in exceptions
                    )
                ],
            ),
            "unmatched_ledger": (
                "unmatched_ledger.csv",
                [
                    self._ledger_json(item)
                    for item in ledgers
                    if any(
                        exc.ledger_record_id == item.ledger_record_id
                        and exc.exception_code == "unmatched_ledger_entry"
                        for exc in exceptions
                    )
                ],
            ),
            "reconciliation_exceptions": (
                "reconciliation_exceptions.csv",
                [
                    {
                        "id": item.id,
                        "code": item.exception_code,
                        "severity": item.severity,
                        "bank_transaction_id": item.bank_transaction_id,
                        "ledger_record_id": item.ledger_record_id,
                        "status": item.status,
                    }
                    for item in exceptions
                ],
            ),
            "reconciliation_controls": (
                "reconciliation_controls.json",
                {
                    item.control_name: {
                        "source": str(item.source_value),
                        "matched": str(item.matched_value),
                        "difference": str(item.difference_value),
                        "status": item.status,
                    }
                    for item in controls
                },
            ),
            "duplicate_records": (
                "duplicate_records.csv",
                [
                    {
                        "id": item.id,
                        "code": item.exception_code,
                        "bank_transaction_id": item.bank_transaction_id,
                        "ledger_record_id": item.ledger_record_id,
                    }
                    for item in exceptions
                    if item.exception_type == "duplicate"
                ],
            ),
            "reversal_candidates": (
                "reversal_candidates.csv",
                [
                    {
                        "id": item.id,
                        "bank_transaction_id": item.bank_transaction_id,
                        "ledger_record_id": item.ledger_record_id,
                    }
                    for item in exceptions
                    if item.exception_type == "reversal"
                ],
            ),
        }
        for report_type, (filename, payload) in files.items():
            path = root / filename
            if filename.endswith(".json"):
                path.write_text(
                    json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                mime = "application/json"
            else:
                rows = payload if isinstance(payload, list) else []
                headers = sorted({key for row in rows for key in row}) or ["no_records"]
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                mime = "text/csv"
            relative = path.relative_to(self._data_root).as_posix()
            checksum = _sha256(path)
            session.add(
                ReconciliationReport(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_version=run.reconciliation_version,
                    report_type=report_type,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type=mime,
                    file_size_bytes=path.stat().st_size,
                )
            )
            session.add(
                PipelineRunArtifact(
                    tenant_id=run.tenant_id,
                    pipeline_run_id=pipeline.id,
                    artifact_type="reconciliation_report",
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
        self, session: Session, run: BankLedgerReconciliationRun
    ) -> dict[str, Any]:
        reports = list(
            session.scalars(
                select(ReconciliationReport).where(
                    ReconciliationReport.reconciliation_run_id == run.id
                )
            )
        )
        if reports and len(reports) != 9:
            raise ReconciliationError(f"Expected 9 reports, found {len(reports)}")
        for report in reports:
            path = self._data_root / report.relative_path
            if not path.is_file() or _sha256(path) != report.checksum:
                raise ReconciliationError(f"Report integrity failed: {report.report_type}")
        duplicate_allocations = session.execute(
            select(
                ReconciliationAllocation.bank_transaction_id,
                ReconciliationAllocation.ledger_record_id,
            ).where(ReconciliationAllocation.reconciliation_run_id == run.id)
        ).all()
        if len(duplicate_allocations) != len(set(duplicate_allocations)):
            raise ReconciliationError("Duplicate reconciliation allocations detected")
        return {"run_id": run.id, "report_count": len(reports), "integrity": "passed"}
