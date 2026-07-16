from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AccountsReceivableAgingBucket,
    AccountsReceivableAgingSnapshot,
    AuditEvent,
    BankAccount,
    BankTransaction,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedSourceFile,
    InvoiceCollectionsAllocation,
    InvoiceCollectionsCandidate,
    InvoiceCollectionsControlTotal,
    InvoiceCollectionsDecision,
    InvoiceCollectionsException,
    InvoiceCollectionsMatch,
    InvoiceCollectionsMatchGroup,
    InvoiceCollectionsReconciliationRule,
    InvoiceCollectionsReconciliationRun,
    InvoiceCollectionsReport,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    Tenant,
    ValidationRun,
)
from app.services.reconciliation_matching import bounded_exact_groups, stable_fingerprint

VERSION = "1.0.0"
LOGIC_REVISION = "2026-07-17.5"
SOURCE_TYPES = (
    "customers",
    "crm_deals",
    "invoices",
    "invoice_lines",
    "customer_payments",
    "customer_payment_applications",
    "general_ledger",
)
STEPS = (
    "validate_tenant_and_permissions",
    "load_reconciliation_configuration",
    "select_eligible_customers_and_deals",
    "select_eligible_invoices_and_lines",
    "validate_invoice_internal_totals",
    "select_eligible_payments_and_applications",
    "validate_payment_applications",
    "select_eligible_bank_deposits",
    "select_eligible_ar_and_cash_gl_records",
    "verify_validation_status",
    "calculate_input_and_ruleset_fingerprints",
    "detect_duplicate_invoices_and_payments",
    "generate_deal_to_invoice_candidates",
    "generate_invoice_payment_candidates",
    "generate_payment_deposit_candidates",
    "generate_invoice_and_payment_to_gl_candidates",
    "generate_grouped_collection_candidates",
    "score_and_rank_candidates",
    "resolve_candidate_conflicts",
    "auto_accept_exact_matches",
    "create_suggested_and_partial_matches",
    "create_unmatched_and_balance_exceptions",
    "calculate_allocations",
    "calculate_ar_aging",
    "calculate_control_totals",
    "validate_reconciliation_invariants",
    "generate_reports_and_artifacts",
    "finalize_invoice_collections_reconciliation",
)


class InvoiceCollectionsError(ValueError):
    pass


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


def optional_money(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return money(value)


def invoice_header_total(row: dict[str, str]) -> Decimal | None:
    subtotal = optional_money(row.get("subtotal"))
    tax = optional_money(row.get("tax_amount"))
    discount = optional_money(row.get("discount_amount"))
    if subtotal is None or tax is None or discount is None:
        return None
    return money(subtotal + tax - discount)


def aging_bucket(as_of: date, due: date) -> tuple[str, int]:
    days = max((as_of - due).days, 0)
    if as_of <= due:
        return "current", 0
    if days <= 30:
        return "1_30", days
    if days <= 60:
        return "31_60", days
    if days <= 90:
        return "61_90", days
    return "over_90", days


def invoice_line_total(row: dict[str, str]) -> Decimal:
    return (
        money(row.get("quantity")) * money(row.get("unit_price"))
        - money(row.get("line_discount"))
        + money(row.get("line_tax"))
    ).quantize(Decimal("0.000001"))


class InvoiceCollectionsReconciliationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tolerance = money(settings.INVOICE_COLLECTIONS_AMOUNT_TOLERANCE)

    @property
    def data_root(self) -> Path:
        return self.settings.GENERATED_DATA_DIRECTORY.parent

    @staticmethod
    def _sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _sources(
        self, session: Session, tenant_id: int
    ) -> tuple[GeneratedDatasetRun, ValidationRun, dict[str, GeneratedSourceFile]]:
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
            raise InvoiceCollectionsError(
                "A completed validation run for generated data is required"
            )
        generated = session.get(GeneratedDatasetRun, validation.generated_dataset_run_id)
        assert generated is not None
        files = {
            item.file_type: item
            for item in session.scalars(
                select(GeneratedSourceFile).where(
                    GeneratedSourceFile.generated_dataset_run_id == generated.id,
                    GeneratedSourceFile.file_type.in_(SOURCE_TYPES),
                )
            )
        }
        missing = sorted(set(SOURCE_TYPES) - set(files))
        if missing:
            raise InvoiceCollectionsError(f"Missing required generated files: {', '.join(missing)}")
        for item in files.values():
            path = self.data_root / item.relative_path
            if not path.is_file() or self._sha(path) != item.sha256_checksum:
                raise InvoiceCollectionsError(
                    f"Generated source checksum is invalid: {item.filename}"
                )
        return generated, validation, files

    def _read(self, item: GeneratedSourceFile) -> list[dict[str, str]]:
        with (self.data_root / item.relative_path).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def _deposits(
        self, session: Session, tenant_id: int, account_id: int, start: date, end: date
    ) -> dict[int, dict[str, Any]]:
        rows = session.execute(
            select(BankTransaction, FinancialTransaction)
            .join(
                FinancialTransaction,
                FinancialTransaction.id == BankTransaction.financial_transaction_id,
            )
            .where(
                BankTransaction.tenant_id == tenant_id,
                BankTransaction.bank_account_id == account_id,
                BankTransaction.is_internal_transfer.is_(False),
                FinancialTransaction.transaction_date >= start - timedelta(days=3),
                FinancialTransaction.transaction_date <= end + timedelta(days=3),
            )
            .order_by(FinancialTransaction.transaction_date, BankTransaction.id)
        )
        result: dict[int, dict[str, Any]] = {}
        for bank, transaction in rows:
            amount = money(bank.credit_amount or 0)
            if bank.transaction_direction != "inflow" and amount <= 0:
                continue
            result[bank.id] = {
                "id": bank.id,
                "date": transaction.transaction_date,
                "amount": amount or abs(money(transaction.amount)),
                "reference": transaction.reference_number or "",
                "description": transaction.description or "",
                "hash": transaction.canonical_hash,
            }
        return result

    def run(
        self,
        session: Session,
        tenant: Tenant,
        account_id: int,
        date_from: date,
        date_to: date,
        aging_as_of_date: date,
        force_rerun: bool = False,
    ) -> tuple[InvoiceCollectionsReconciliationRun, bool]:
        if date_from > date_to or aging_as_of_date < date_from:
            raise InvoiceCollectionsError("Invalid reconciliation or aging date range")
        account = session.scalar(
            select(BankAccount).where(
                BankAccount.id == account_id, BankAccount.tenant_id == tenant.id
            )
        )
        if account is None:
            raise InvoiceCollectionsError("Bank account was not found for this tenant")
        generated, validation, files = self._sources(session, tenant.id)
        customers = self._read(files["customers"])
        deals = self._read(files["crm_deals"])
        invoices = [
            row
            for row in self._read(files["invoices"])
            if date_from <= date.fromisoformat(row["invoice_date"]) <= date_to
        ]
        invoice_ids = {row["invoice_id"] for row in invoices}
        lines = [r for r in self._read(files["invoice_lines"]) if r["invoice_id"] in invoice_ids]
        payments = [
            row
            for row in self._read(files["customer_payments"])
            if date_from <= date.fromisoformat(row["payment_date"]) <= date_to
        ]
        payment_ids = {row["payment_id"] for row in payments}
        applications = [
            row
            for row in self._read(files["customer_payment_applications"])
            if row["invoice_id"] in invoice_ids and row["payment_id"] in payment_ids
        ]
        gl = [
            row
            for row in self._read(files["general_ledger"])
            if row.get("invoice_id") in invoice_ids or row.get("source_record_id") in payment_ids
        ]
        deposits = self._deposits(session, tenant.id, account.id, date_from, date_to)
        rules = list(
            session.scalars(
                select(InvoiceCollectionsReconciliationRule)
                .where(
                    InvoiceCollectionsReconciliationRule.tenant_id == tenant.id,
                    InvoiceCollectionsReconciliationRule.version == VERSION,
                    InvoiceCollectionsReconciliationRule.is_active.is_(True),
                )
                .order_by(InvoiceCollectionsReconciliationRule.execution_order)
            )
        )
        if len(rules) != 22:
            raise InvoiceCollectionsError("Phase 11 reconciliation rules are not fully seeded")
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
                "aging_buckets": self.settings.INVOICE_COLLECTIONS_AGING_BUCKETS,
            }
        )
        base_fingerprint = stable_fingerprint(
            {
                "period": [date_from, date_to, aging_as_of_date],
                "account": account.id,
                "files": [[key, files[key].sha256_checksum] for key in sorted(files)],
                "deposits": [[key, value["hash"]] for key, value in sorted(deposits.items())],
                "validation": validation.input_fingerprint,
                "version": VERSION,
                "logic_revision": LOGIC_REVISION,
            }
        )
        fingerprint = base_fingerprint
        forced_at: str | None = None
        if force_rerun:
            forced_at = datetime.now(UTC).isoformat()
            fingerprint = stable_fingerprint(
                {"base_fingerprint": base_fingerprint, "forced_at": forced_at}
            )
        existing = session.scalar(
            select(InvoiceCollectionsReconciliationRun).where(
                InvoiceCollectionsReconciliationRun.tenant_id == tenant.id,
                InvoiceCollectionsReconciliationRun.input_fingerprint == fingerprint,
                InvoiceCollectionsReconciliationRun.ruleset_fingerprint == ruleset,
                InvoiceCollectionsReconciliationRun.reconciliation_version == VERSION,
            )
        )
        if existing is not None:
            self.verify_integrity(session, existing)
            return existing, True
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "invoice_collections_reconciliation",
                PipelineDefinition.is_active.is_(True),
            )
        )
        if definition is None:
            raise InvoiceCollectionsError("Invoice collections pipeline is not active")
        now = datetime.now(UTC)
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="invoice_collections_reconciliation",
            status="running",
            started_at=now,
            metadata_json={"version": VERSION, "force_rerun": force_rerun},
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
        run = InvoiceCollectionsReconciliationRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            reconciliation_version=VERSION,
            status="running",
            date_from=date_from,
            date_to=date_to,
            aging_as_of_date=aging_as_of_date,
            bank_account_id=account.id,
            generated_dataset_run_id=generated.id,
            validation_run_id=validation.id,
            included_customer_count=len(customers),
            included_deal_count=len(deals),
            included_invoice_count=len(invoices),
            included_payment_count=len(payments),
            included_bank_deposit_count=len(deposits),
            included_gl_record_count=len(gl),
            input_fingerprint=fingerprint,
            ruleset_fingerprint=ruleset,
            started_at=now,
            metadata_json={
                "source_files": {key: value.id for key, value in files.items()},
                "base_input_fingerprint": base_fingerprint,
                "force_rerun": force_rerun,
                "forced_at": forced_at,
                "logic_revision": LOGIC_REVISION,
            },
        )
        session.add(run)
        session.flush()
        self._reconcile(
            session,
            run,
            customers,
            deals,
            invoices,
            lines,
            payments,
            applications,
            deposits,
            gl,
            rules,
        )
        self._aging(session, run, invoices, applications)
        self._controls(session, run)
        self._reports(session, tenant.code, run, pipeline)
        self._record_reconciliation_audit_events(session, run, pipeline)
        self.verify_integrity(session, run)
        completed = datetime.now(UTC)
        run.status = "completed_with_exceptions" if run.exception_count else "completed"
        run.completed_at = completed
        pipeline.status = run.status
        pipeline.completed_at = completed
        pipeline.records_extracted = len(invoices) + len(payments) + len(deposits) + len(gl)
        pipeline.records_accepted = run.automatically_matched_count
        pipeline.steps[-1].status = "completed"
        pipeline.steps[-1].completed_at = completed
        session.commit()
        return run, False

    def _reconcile(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        customers: list[dict[str, str]],
        deals: list[dict[str, str]],
        invoices: list[dict[str, str]],
        lines: list[dict[str, str]],
        payments: list[dict[str, str]],
        applications: list[dict[str, str]],
        deposits: dict[int, dict[str, Any]],
        gl: list[dict[str, str]],
        rules: list[InvoiceCollectionsReconciliationRule],
    ) -> None:
        rule = {item.code: item for item in rules}
        deal_ids = {item["deal_id"] for item in deals}
        deal_by_id = {item["deal_id"]: item for item in deals}
        payment_by_id = {item["payment_id"]: item for item in payments}
        apps_by_invoice: dict[str, list[dict[str, str]]] = defaultdict(list)
        apps_by_payment: dict[str, list[dict[str, str]]] = defaultdict(list)
        lines_by_invoice: dict[str, list[dict[str, str]]] = defaultdict(list)
        gl_by_invoice: dict[str, list[dict[str, str]]] = defaultdict(list)
        gl_by_payment: dict[str, list[dict[str, str]]] = defaultdict(list)
        for item in applications:
            apps_by_invoice[item["invoice_id"]].append(item)
            apps_by_payment[item["payment_id"]].append(item)
        for item in lines:
            lines_by_invoice[item["invoice_id"]].append(item)
        for item in gl:
            if item.get("invoice_id"):
                gl_by_invoice[item["invoice_id"]].append(item)
            if item.get("source_record_id"):
                gl_by_payment[item["source_record_id"]].append(item)
        duplicate_invoices = {
            key
            for key, count in Counter(i["invoice_number"] for i in invoices).items()
            if count > 1
        }
        duplicate_payments = {
            key
            for key, count in Counter(p["payment_reference"] for p in payments).items()
            if count > 1
        }
        used_deposits: set[int] = set()
        deposit_allocated: dict[int, Decimal] = defaultdict(Decimal)
        deposit_by_application: dict[str, Decimal] = {}
        gl_allocated: dict[str, Decimal] = defaultdict(Decimal)
        used_gl: set[str] = set()
        matched_payment_ids: set[str] = set()
        run.invoice_total = sum((money(i["total_amount"]) for i in invoices), Decimal(0))
        run.invoice_paid_total = sum((money(i["amount_paid"]) for i in invoices), Decimal(0))
        run.invoice_balance_total = sum((money(i["balance_due"]) for i in invoices), Decimal(0))
        run.payment_total = sum((money(p["payment_amount"]) for p in payments), Decimal(0))
        run.applied_payment_total = sum(
            (money(a["applied_amount"]) for a in applications), Decimal(0)
        )
        run.unapplied_payment_total = sum(
            (money(p["unapplied_amount"]) for p in payments), Decimal(0)
        )
        run.bank_deposit_total = sum((d["amount"] for d in deposits.values()), Decimal(0))
        component_totals = {
            "invoice_subtotal": sum((money(i.get("subtotal")) for i in invoices), Decimal(0)),
            "invoice_tax": sum((money(i.get("tax_amount")) for i in invoices), Decimal(0)),
            "invoice_discount": sum(
                (money(i.get("discount_amount")) for i in invoices), Decimal(0)
            ),
            "line_subtotal": sum(
                (money(x.get("quantity")) * money(x.get("unit_price")) for x in lines),
                Decimal(0),
            ),
            "line_tax": sum((money(x.get("line_tax")) for x in lines), Decimal(0)),
            "line_discount": sum((money(x.get("line_discount")) for x in lines), Decimal(0)),
            "deal_value": sum(
                (
                    money(deal_by_id[i["deal_id"]].get("deal_value"))
                    for i in invoices
                    if i.get("deal_id") in deal_by_id
                ),
                Decimal(0),
            ),
        }
        run.metadata_json = {
            **(run.metadata_json or {}),
            "component_totals": {key: str(value) for key, value in component_totals.items()},
        }
        for invoice in invoices:
            invoice_id = invoice["invoice_id"]
            invoice_total = money(invoice["total_amount"])
            apps = apps_by_invoice[invoice_id]
            applied = sum((money(item["applied_amount"]) for item in apps), Decimal(0))
            invoice_lines = lines_by_invoice[invoice_id]
            line_sum = sum((money(item["line_total"]) for item in invoice_lines), Decimal(0))
            line_subtotal = sum(
                (money(item["quantity"]) * money(item["unit_price"]) for item in invoice_lines),
                Decimal(0),
            )
            line_formula_valid = all(
                abs(invoice_line_total(item) - money(item["line_total"])) <= self.tolerance
                for item in invoice_lines
            )
            subtotal_valid = abs(line_subtotal - money(invoice.get("subtotal"))) <= self.tolerance
            header_total = invoice_header_total(invoice)
            header_valid = (
                header_total is not None and abs(header_total - invoice_total) <= self.tolerance
            )
            line_total_valid = abs(line_sum - invoice_total) <= self.tolerance
            internal_valid = (
                line_formula_valid and subtotal_valid and header_valid and line_total_valid
            )
            relationship_valid = not invoice.get("deal_id") or invoice["deal_id"] in deal_ids
            is_duplicate = invoice["invoice_number"] in duplicate_invoices
            deposit_total = Decimal(0)
            invoice_gl = [
                item
                for item in gl_by_invoice[invoice_id]
                if item.get("source_type") == "customer_invoice"
            ]
            invoice_gl_total = sum(
                (
                    money(item.get("debit")) - money(item.get("credit"))
                    for item in invoice_gl
                    if item.get("account_code") == "1100"
                ),
                Decimal(0),
            )
            payment_gl_total = Decimal(0)
            exact_deposits = True
            for app in apps:
                payment = payment_by_id.get(app["payment_id"])
                if payment is None:
                    exact_deposits = False
                    continue
                matched_payment_ids.add(payment["payment_id"])
                bank_id = (
                    int(payment["canonical_bank_transaction_id"])
                    if payment.get("canonical_bank_transaction_id")
                    else None
                )
                deposit = deposits.get(bank_id or -1)
                if deposit is None:
                    exact_deposits = False
                else:
                    available = max(
                        deposit["amount"] - deposit_allocated[deposit["id"]], Decimal(0)
                    )
                    deposit_part = min(money(app["applied_amount"]), available)
                    deposit_by_application[app["payment_application_id"]] = deposit_part
                    deposit_allocated[deposit["id"]] += deposit_part
                    deposit_total += deposit_part
                    if deposit_part > 0:
                        used_deposits.add(deposit["id"])
                    if deposit_part + self.tolerance < money(app["applied_amount"]):
                        exact_deposits = False
                payment_gl = gl_by_payment[payment["payment_id"]]
                payment_gl_total += min(
                    money(app["applied_amount"]),
                    sum(
                        (
                            money(x.get("debit"))
                            for x in payment_gl
                            if x.get("account_code") == "1000"
                        ),
                        Decimal(0),
                    ),
                )
                used_gl.update(
                    x.get("journal_line_id") or x.get("source_record_id") or "" for x in payment_gl
                )
            used_gl.update(
                x.get("journal_line_id") or x.get("source_record_id") or "" for x in invoice_gl
            )
            blockers = not internal_valid or not relationship_valid or is_duplicate
            complete = abs(applied - invoice_total) <= self.tolerance
            gl_valid = (
                abs(invoice_gl_total - invoice_total) <= self.tolerance
                and abs(payment_gl_total - applied) <= self.tolerance
            )
            auto = complete and exact_deposits and gl_valid and not blockers
            status = "matched" if auto else "partially_matched" if applied > 0 else "unmatched"
            group_rule = rule["invoice_to_payment_application_exact"]
            group = InvoiceCollectionsMatchGroup(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                reconciliation_version=VERSION,
                group_type="invoice_to_multiple_payments"
                if len(apps) > 1
                else "invoice_to_single_payment",
                status=status,
                confidence=Decimal("1.000000")
                if auto
                else Decimal("0.850000")
                if applied
                else Decimal("0"),
                invoice_total=invoice_total,
                payment_total=applied,
                deposit_total=deposit_total,
                gl_total=min(invoice_gl_total, payment_gl_total)
                if payment_gl_total
                else invoice_gl_total,
                matched_amount=min(invoice_total, applied, deposit_total)
                if deposit_total
                else min(invoice_total, applied),
                remaining_amount=max(invoice_total - applied, Decimal(0)),
                difference_amount=applied - invoice_total,
                reconciliation_rule_id=group_rule.id,
                auto_accepted=auto,
                group_fingerprint=stable_fingerprint({"version": VERSION, "invoice": invoice_id}),
                metadata_json={
                    "invoice": invoice,
                    "invoice_lines": invoice_lines,
                    "payment_applications": apps,
                    "payments": [
                        payment_by_id[a["payment_id"]]
                        for a in apps
                        if a["payment_id"] in payment_by_id
                    ],
                    "invoice_gl": invoice_gl,
                    "deal": deal_by_id.get(invoice.get("deal_id", "")),
                    "invoice_controls": {
                        "line_formula_valid": line_formula_valid,
                        "subtotal_valid": subtotal_valid,
                        "header_total_valid": header_valid,
                        "line_total_valid": line_total_valid,
                    },
                    "internal_total_valid": internal_valid,
                    "gl_valid": gl_valid,
                },
            )
            session.add(group)
            session.flush()
            deal = deal_by_id.get(invoice.get("deal_id", ""))
            if relationship_valid and deal is not None:
                session.add(
                    InvoiceCollectionsMatch(
                        tenant_id=run.tenant_id,
                        reconciliation_run_id=run.id,
                        match_group_id=group.id,
                        reconciliation_version=VERSION,
                        customer_id=invoice["customer_id"],
                        crm_deal_id=invoice.get("deal_id"),
                        invoice_id=invoice_id,
                        payment_id=None,
                        payment_application_id=None,
                        bank_transaction_id=None,
                        gl_record_id=None,
                        candidate_id=None,
                        matched_amount=min(money(deal.get("deal_value")), invoice_total),
                        match_component="deal_value",
                        confidence=Decimal("1"),
                        status=status,
                        rule_code="crm_deal_to_invoice_exact",
                        metadata_json={"relationship_key": invoice.get("deal_id")},
                    )
                )
            for gl_line in invoice_gl:
                if gl_line.get("account_code") != "1100":
                    continue
                gl_record_id = gl_line.get("journal_line_id") or gl_line.get("source_record_id")
                gl_amount = money(gl_line.get("debit"))
                if not gl_record_id or gl_amount <= 0:
                    continue
                allocated_gl_amount = min(
                    max(gl_amount - gl_allocated[gl_record_id], Decimal(0)), invoice_total
                )
                if allocated_gl_amount <= 0:
                    continue
                gl_allocated[gl_record_id] += allocated_gl_amount
                session.add(
                    InvoiceCollectionsMatch(
                        tenant_id=run.tenant_id,
                        reconciliation_run_id=run.id,
                        match_group_id=group.id,
                        reconciliation_version=VERSION,
                        customer_id=invoice["customer_id"],
                        crm_deal_id=invoice.get("deal_id"),
                        invoice_id=invoice_id,
                        payment_id=None,
                        payment_application_id=None,
                        bank_transaction_id=None,
                        gl_record_id=gl_record_id,
                        candidate_id=None,
                        matched_amount=allocated_gl_amount,
                        match_component="accounts_receivable",
                        confidence=Decimal("1") if gl_valid else Decimal("0.85"),
                        status=status,
                        rule_code="invoice_to_gl_receivable_exact",
                        metadata_json={"account_code": "1100"},
                    )
                )
                session.add(
                    InvoiceCollectionsAllocation(
                        tenant_id=run.tenant_id,
                        reconciliation_run_id=run.id,
                        match_group_id=group.id,
                        reconciliation_version=VERSION,
                        invoice_id=invoice_id,
                        payment_id=None,
                        payment_application_id=None,
                        bank_transaction_id=None,
                        gl_record_id=gl_record_id,
                        allocation_type="invoice_to_ar_gl",
                        allocated_amount=allocated_gl_amount,
                    )
                )
            self._candidate(
                session,
                run,
                group_rule,
                invoice,
                None,
                None,
                "invoice_to_payment",
                Decimal("1") if apps else Decimal(0),
            )
            self._candidate(
                session,
                run,
                rule["crm_deal_to_invoice_exact"],
                invoice,
                None,
                None,
                "deal_to_invoice",
                Decimal("1") if relationship_valid else Decimal(0),
            )
            self._candidate(
                session,
                run,
                rule["invoice_to_gl_receivable_exact"],
                invoice,
                None,
                None,
                "invoice_to_gl",
                Decimal("1")
                if abs(invoice_gl_total - invoice_total) <= self.tolerance
                else Decimal(0),
            )
            for app in apps:
                payment = payment_by_id.get(app["payment_id"])
                if payment is None:
                    continue
                amount = money(app["applied_amount"])
                bank_id = (
                    int(payment["canonical_bank_transaction_id"])
                    if payment.get("canonical_bank_transaction_id")
                    else None
                )
                session.add(
                    InvoiceCollectionsMatch(
                        tenant_id=run.tenant_id,
                        reconciliation_run_id=run.id,
                        match_group_id=group.id,
                        reconciliation_version=VERSION,
                        customer_id=invoice["customer_id"],
                        crm_deal_id=invoice.get("deal_id"),
                        invoice_id=invoice_id,
                        payment_id=payment["payment_id"],
                        payment_application_id=app["payment_application_id"],
                        bank_transaction_id=bank_id if bank_id in deposits else None,
                        gl_record_id=None,
                        candidate_id=None,
                        matched_amount=amount,
                        match_component="payment_application",
                        confidence=Decimal("1"),
                        status=status,
                        rule_code="invoice_to_payment_application_exact",
                        metadata_json={
                            "application_date": app["application_date"],
                            "payment": payment,
                        },
                    )
                )
                self._candidate(
                    session,
                    run,
                    rule["payment_to_bank_deposit_exact"],
                    invoice,
                    payment,
                    bank_id if bank_id in deposits else None,
                    "payment_to_deposit",
                    Decimal("1")
                    if deposit_by_application.get(app["payment_application_id"], 0)
                    else Decimal(0),
                )
                self._candidate(
                    session,
                    run,
                    rule["payment_to_gl_cash_and_ar_exact"],
                    invoice,
                    payment,
                    None,
                    "payment_to_gl",
                    Decimal("1") if gl_by_payment[payment["payment_id"]] else Decimal(0),
                )
                session.add(
                    InvoiceCollectionsAllocation(
                        tenant_id=run.tenant_id,
                        reconciliation_run_id=run.id,
                        match_group_id=group.id,
                        reconciliation_version=VERSION,
                        invoice_id=invoice_id,
                        payment_id=payment["payment_id"],
                        payment_application_id=app["payment_application_id"],
                        bank_transaction_id=None,
                        gl_record_id=None,
                        allocation_type="payment_to_invoice",
                        allocated_amount=amount,
                    )
                )
                deposit_part = deposit_by_application.get(app["payment_application_id"], Decimal(0))
                if bank_id in deposits and deposit_part > 0:
                    session.add(
                        InvoiceCollectionsMatch(
                            tenant_id=run.tenant_id,
                            reconciliation_run_id=run.id,
                            match_group_id=group.id,
                            reconciliation_version=VERSION,
                            customer_id=invoice["customer_id"],
                            crm_deal_id=invoice.get("deal_id"),
                            invoice_id=invoice_id,
                            payment_id=payment["payment_id"],
                            payment_application_id=app["payment_application_id"],
                            bank_transaction_id=bank_id,
                            gl_record_id=None,
                            candidate_id=None,
                            matched_amount=deposit_part,
                            match_component="bank_deposit",
                            confidence=Decimal("1"),
                            status=status,
                            rule_code="payment_to_bank_deposit_exact",
                            metadata_json={"deposit_reference": deposits[bank_id]["reference"]},
                        )
                    )
                    session.add(
                        InvoiceCollectionsAllocation(
                            tenant_id=run.tenant_id,
                            reconciliation_run_id=run.id,
                            match_group_id=group.id,
                            reconciliation_version=VERSION,
                            invoice_id=invoice_id,
                            payment_id=payment["payment_id"],
                            payment_application_id=app["payment_application_id"],
                            bank_transaction_id=bank_id,
                            gl_record_id=None,
                            allocation_type="payment_to_deposit",
                            allocated_amount=deposit_part,
                        )
                    )
                for gl_line in gl_by_payment[payment["payment_id"]]:
                    account_code = gl_line.get("account_code")
                    if account_code not in {"1000", "1100"}:
                        continue
                    gl_record_id = gl_line.get("journal_line_id") or gl_line.get("source_record_id")
                    gl_amount = (
                        money(gl_line.get("debit"))
                        if account_code == "1000"
                        else money(gl_line.get("credit"))
                    )
                    if not gl_record_id or gl_amount <= 0:
                        continue
                    allocated_gl_amount = min(
                        max(gl_amount - gl_allocated[gl_record_id], Decimal(0)), amount
                    )
                    if allocated_gl_amount <= 0:
                        continue
                    gl_allocated[gl_record_id] += allocated_gl_amount
                    component = "cash" if account_code == "1000" else "accounts_receivable"
                    allocation_type = (
                        "payment_to_cash_gl" if account_code == "1000" else "payment_to_ar_gl"
                    )
                    session.add(
                        InvoiceCollectionsMatch(
                            tenant_id=run.tenant_id,
                            reconciliation_run_id=run.id,
                            match_group_id=group.id,
                            reconciliation_version=VERSION,
                            customer_id=invoice["customer_id"],
                            crm_deal_id=invoice.get("deal_id"),
                            invoice_id=invoice_id,
                            payment_id=payment["payment_id"],
                            payment_application_id=app["payment_application_id"],
                            bank_transaction_id=None,
                            gl_record_id=gl_record_id,
                            candidate_id=None,
                            matched_amount=allocated_gl_amount,
                            match_component=component,
                            confidence=Decimal("1") if gl_valid else Decimal("0.85"),
                            status=status,
                            rule_code="payment_to_gl_cash_and_ar_exact",
                            metadata_json={"account_code": account_code},
                        )
                    )
                    session.add(
                        InvoiceCollectionsAllocation(
                            tenant_id=run.tenant_id,
                            reconciliation_run_id=run.id,
                            match_group_id=group.id,
                            reconciliation_version=VERSION,
                            invoice_id=invoice_id,
                            payment_id=payment["payment_id"],
                            payment_application_id=app["payment_application_id"],
                            bank_transaction_id=None,
                            gl_record_id=gl_record_id,
                            allocation_type=allocation_type,
                            allocated_amount=allocated_gl_amount,
                        )
                    )
            for code, condition, message, severity in (
                (
                    "invoice_line_total_mismatch",
                    not line_formula_valid or not line_total_valid,
                    "Invoice line totals do not reconcile to invoice total",
                    "error",
                ),
                (
                    "invoice_balance_mismatch",
                    not header_valid or not subtotal_valid,
                    "Invoice header amounts do not reconcile",
                    "error",
                ),
                (
                    "missing_deal",
                    not relationship_valid,
                    "Invoice references a missing CRM deal",
                    "error",
                ),
                ("duplicate_invoice", is_duplicate, "Duplicate invoice number detected", "error"),
                ("missing_payment", not apps, "Invoice has no payment application", "warning"),
                (
                    "invoice_underpaid",
                    applied + self.tolerance < invoice_total and applied > 0,
                    "Invoice is underpaid",
                    "warning",
                ),
                (
                    "invoice_overpaid",
                    applied - self.tolerance > invoice_total,
                    "Invoice is overpaid",
                    "warning",
                ),
                (
                    "missing_bank_deposit",
                    bool(apps) and not exact_deposits,
                    "Applied payment has no exact bank deposit",
                    "error",
                ),
                (
                    "invoice_gl_mismatch",
                    not gl_valid,
                    "Invoice or collection GL posting does not reconcile",
                    "error",
                ),
            ):
                if condition:
                    self._exception(
                        session, run, group.id, code, severity, message, invoice_id=invoice_id
                    )
        for payment in payments:
            if payment["payment_reference"] in duplicate_payments:
                self._exception(
                    session,
                    run,
                    None,
                    "duplicate_payment",
                    "error",
                    "Duplicate payment reference detected",
                    payment_id=payment["payment_id"],
                )
            if payment["payment_id"] not in matched_payment_ids:
                code = (
                    "unapplied_payment"
                    if money(payment.get("unapplied_amount")) > 0
                    else "unmatched_payment"
                )
                self._exception(
                    session,
                    run,
                    None,
                    code,
                    "warning",
                    "Payment is not applied to an eligible invoice",
                    payment_id=payment["payment_id"],
                )
        self._grouped_candidates(
            session,
            run,
            rule,
            invoices,
            payments,
            applications,
            deposits,
            used_deposits,
            deposit_by_application,
        )
        for deposit_id in sorted(set(deposits) - used_deposits):
            self._exception(
                session,
                run,
                None,
                "unmatched_bank_deposit",
                "warning",
                "Bank deposit is not linked to an eligible payment",
                bank_transaction_id=deposit_id,
            )
        for item in gl:
            key = item.get("journal_line_id") or item.get("source_record_id") or ""
            if key not in used_gl:
                self._exception(
                    session,
                    run,
                    None,
                    "unmatched_ar_gl",
                    "warning",
                    "Receivable or cash GL line is unmatched",
                    gl_record_id=key,
                )
        session.flush()
        groups = list(
            session.scalars(
                select(InvoiceCollectionsMatchGroup).where(
                    InvoiceCollectionsMatchGroup.reconciliation_run_id == run.id
                )
            )
        )
        run.automatically_matched_count = sum(item.auto_accepted for item in groups)
        run.suggested_match_count = sum(item.status == "suggested" for item in groups)
        run.partially_matched_count = sum(item.status == "partially_matched" for item in groups)
        run.unmatched_invoice_count = sum(item.status == "unmatched" for item in groups)
        run.unmatched_payment_count = len(payments) - len(matched_payment_ids)
        run.unmatched_deposit_count = len(deposits) - len(used_deposits)
        run.unmatched_gl_count = len(gl) - len(used_gl)
        run.duplicate_invoice_count = len(duplicate_invoices)
        run.duplicate_payment_count = len(duplicate_payments)
        run.exception_count = (
            session.scalar(
                select(func.count())
                .select_from(InvoiceCollectionsException)
                .where(InvoiceCollectionsException.reconciliation_run_id == run.id)
            )
            or 0
        )
        run.matched_collection_total = sum(
            (item.matched_amount for item in groups if item.auto_accepted), Decimal(0)
        )
        run.reconciliation_rate = (
            (run.matched_collection_total / run.invoice_total).quantize(Decimal("0.000001"))
            if run.invoice_total
            else Decimal(0)
        )
        run.gl_receivable_total = sum(
            (
                money(x.get("debit")) - money(x.get("credit"))
                for x in gl
                if x.get("account_code") == "1100" and x.get("source_type") == "customer_invoice"
            ),
            Decimal(0),
        )
        run.gl_cash_total = sum(
            (
                money(x.get("debit")) - money(x.get("credit"))
                for x in gl
                if x.get("account_code") == "1000"
            ),
            Decimal(0),
        )
        allocated_deposits = sum(deposit_allocated.values(), Decimal(0))
        invoice_application_rate = (
            Decimal(sum(bool(apps_by_invoice[i["invoice_id"]]) for i in invoices))
            / Decimal(len(invoices))
            if invoices
            else Decimal(0)
        )
        payment_allocation_rate = (
            run.applied_payment_total / run.payment_total if run.payment_total else Decimal(0)
        )
        deposit_match_rate = (
            allocated_deposits / run.bank_deposit_total if run.bank_deposit_total else Decimal(0)
        )
        eligible_gl_total = run.gl_receivable_total + run.gl_cash_total
        matched_gl_total = sum(
            (min(item.invoice_total, item.gl_total) for item in groups), Decimal(0)
        )
        gl_match_rate = matched_gl_total / eligible_gl_total if eligible_gl_total else Decimal(0)
        run.metadata_json = {
            **(run.metadata_json or {}),
            "rates": {
                "invoice_application_rate": str(
                    invoice_application_rate.quantize(Decimal("0.000001"))
                ),
                "payment_allocation_rate": str(
                    payment_allocation_rate.quantize(Decimal("0.000001"))
                ),
                "deposit_match_rate": str(deposit_match_rate.quantize(Decimal("0.000001"))),
                "gl_match_rate": str(gl_match_rate.quantize(Decimal("0.000001"))),
                "overall_collections_reconciliation_rate": str(run.reconciliation_rate),
            },
            "allocated_deposit_total": str(allocated_deposits),
        }

    def _candidate(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        rule: InvoiceCollectionsReconciliationRule,
        invoice: dict[str, str],
        payment: dict[str, str] | None,
        bank_id: int | None,
        kind: str,
        confidence: Decimal,
    ) -> None:
        session.add(
            InvoiceCollectionsCandidate(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                reconciliation_rule_id=rule.id,
                reconciliation_version=VERSION,
                customer_id=invoice.get("customer_id"),
                crm_deal_id=invoice.get("deal_id"),
                invoice_id=invoice.get("invoice_id"),
                payment_id=payment.get("payment_id") if payment else None,
                bank_transaction_id=bank_id,
                gl_record_id=None,
                candidate_type=kind,
                match_group_key=invoice.get("invoice_id"),
                amount_difference=Decimal(0),
                date_difference_days=0,
                reference_score=confidence,
                customer_score=confidence,
                description_score=Decimal(0),
                amount_score=confidence,
                date_score=confidence,
                total_confidence=confidence,
                candidate_status=(
                    "accepted_automatically"
                    if confidence >= Decimal("0.98")
                    else "suggested"
                    if confidence > 0
                    else "generated"
                ),
                reason_json={"authoritative_application": True},
                candidate_fingerprint=stable_fingerprint(
                    {
                        "version": VERSION,
                        "kind": kind,
                        "invoice": invoice.get("invoice_id"),
                        "payment": payment.get("payment_id") if payment else None,
                        "bank": bank_id,
                    }
                ),
            )
        )

    def _grouped_candidates(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        rules: dict[str, InvoiceCollectionsReconciliationRule],
        invoices: list[dict[str, str]],
        payments: list[dict[str, str]],
        applications: list[dict[str, str]],
        deposits: dict[int, dict[str, Any]],
        used_deposits: set[int],
        deposit_by_application: dict[str, Decimal],
    ) -> None:
        invoice_by_id = {item["invoice_id"]: item for item in invoices}
        applications_by_payment: dict[str, list[dict[str, str]]] = defaultdict(list)
        for application in applications:
            applications_by_payment[application["payment_id"]].append(application)
        allocated_by_payment: dict[str, Decimal] = defaultdict(Decimal)
        for application in applications:
            allocated_by_payment[application["payment_id"]] += deposit_by_application.get(
                application["payment_application_id"], Decimal(0)
            )
        uncovered = [
            payment
            for payment in payments
            if allocated_by_payment[payment["payment_id"]] + self.tolerance
            < money(payment["payment_amount"])
        ]
        available_deposits = [
            (str(key), value["amount"], value["date"])
            for key, value in sorted(deposits.items())
            if key not in used_deposits
        ]
        for payment in uncovered:
            payment_id = payment["payment_id"]
            apps = applications_by_payment[payment_id]
            if not apps or apps[0]["invoice_id"] not in invoice_by_id:
                continue
            invoice = invoice_by_id[apps[0]["invoice_id"]]
            groups = bounded_exact_groups(
                money(payment["payment_amount"]) - allocated_by_payment[payment_id],
                available_deposits,
                date.fromisoformat(payment["payment_date"]),
                self.settings.INVOICE_COLLECTIONS_MAX_DEPOSITS_PER_PAYMENT,
                self.settings.INVOICE_COLLECTIONS_DATE_TOLERANCE_DAYS,
                self.tolerance,
                self.settings.INVOICE_COLLECTIONS_MAX_CANDIDATES_PER_RECORD,
            )
            for keys in groups:
                deposit_total = sum((deposits[int(key)]["amount"] for key in keys), Decimal(0))
                group = InvoiceCollectionsMatchGroup(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_version=VERSION,
                    group_type="payment_to_split_deposits",
                    status="suggested" if len(groups) == 1 else "needs_review",
                    confidence=Decimal("0.850000") if len(groups) == 1 else Decimal("0.700000"),
                    invoice_total=money(invoice["total_amount"]),
                    payment_total=money(payment["payment_amount"]),
                    deposit_total=deposit_total,
                    gl_total=Decimal(0),
                    matched_amount=Decimal(0),
                    remaining_amount=money(payment["payment_amount"]),
                    difference_amount=deposit_total - money(payment["payment_amount"]),
                    reconciliation_rule_id=rules["one_payment_to_split_deposits"].id,
                    auto_accepted=False,
                    group_fingerprint=stable_fingerprint(
                        {
                            "version": VERSION,
                            "type": "split_deposit",
                            "payment": payment_id,
                            "deposits": keys,
                        }
                    ),
                    metadata_json={
                        "payment": payment,
                        "deposit_ids": list(keys),
                        "ambiguous": len(groups) > 1,
                    },
                )
                session.add(group)
                for key in keys:
                    self._candidate(
                        session,
                        run,
                        rules["one_payment_to_split_deposits"],
                        invoice,
                        payment,
                        int(key),
                        "suggestion",
                        group.confidence,
                    )
        uncovered_records = [
            (
                payment["payment_id"],
                money(payment["payment_amount"]) - allocated_by_payment[payment["payment_id"]],
                date.fromisoformat(payment["payment_date"]),
            )
            for payment in uncovered
        ]
        payment_by_id = {item["payment_id"]: item for item in payments}
        for deposit_id, deposit in sorted(deposits.items()):
            if deposit_id in used_deposits:
                continue
            groups = bounded_exact_groups(
                deposit["amount"],
                uncovered_records,
                deposit["date"],
                self.settings.INVOICE_COLLECTIONS_MAX_PAYMENTS_PER_DEPOSIT,
                self.settings.INVOICE_COLLECTIONS_DATE_TOLERANCE_DAYS,
                self.tolerance,
                self.settings.INVOICE_COLLECTIONS_MAX_CANDIDATES_PER_RECORD,
            )
            for keys in groups:
                first_apps = applications_by_payment[keys[0]]
                if not first_apps or first_apps[0]["invoice_id"] not in invoice_by_id:
                    continue
                invoice = invoice_by_id[first_apps[0]["invoice_id"]]
                group = InvoiceCollectionsMatchGroup(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_version=VERSION,
                    group_type="multiple_payments_to_combined_deposit",
                    status="suggested" if len(groups) == 1 else "needs_review",
                    confidence=Decimal("0.850000") if len(groups) == 1 else Decimal("0.700000"),
                    invoice_total=sum(
                        (
                            money(invoice_by_id[a[0]["invoice_id"]]["total_amount"])
                            for key in keys
                            if (a := applications_by_payment[key])
                            and a[0]["invoice_id"] in invoice_by_id
                        ),
                        Decimal(0),
                    ),
                    payment_total=sum(
                        (money(payment_by_id[key]["payment_amount"]) for key in keys), Decimal(0)
                    ),
                    deposit_total=deposit["amount"],
                    gl_total=Decimal(0),
                    matched_amount=Decimal(0),
                    remaining_amount=deposit["amount"],
                    difference_amount=Decimal(0),
                    reconciliation_rule_id=rules["multiple_payments_to_combined_deposit"].id,
                    auto_accepted=False,
                    group_fingerprint=stable_fingerprint(
                        {
                            "version": VERSION,
                            "type": "combined_deposit",
                            "payments": keys,
                            "deposit": deposit_id,
                        }
                    ),
                    metadata_json={
                        "payment_ids": list(keys),
                        "deposit_id": deposit_id,
                        "ambiguous": len(groups) > 1,
                    },
                )
                session.add(group)
                for key in keys:
                    apps = applications_by_payment[key]
                    linked_invoice = invoice_by_id[apps[0]["invoice_id"]]
                    self._candidate(
                        session,
                        run,
                        rules["multiple_payments_to_combined_deposit"],
                        linked_invoice,
                        payment_by_id[key],
                        deposit_id,
                        "payment_group_to_deposit",
                        group.confidence,
                    )

    def _exception(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        group_id: int | None,
        code: str,
        severity: str,
        message: str,
        invoice_id: str | None = None,
        payment_id: str | None = None,
        bank_transaction_id: int | None = None,
        gl_record_id: str | None = None,
    ) -> None:
        session.add(
            InvoiceCollectionsException(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                reconciliation_version=VERSION,
                exception_code=code,
                exception_type="reconciliation",
                severity=severity,
                customer_id=None,
                crm_deal_id=None,
                invoice_id=invoice_id,
                payment_id=payment_id,
                bank_transaction_id=bank_transaction_id,
                gl_record_id=gl_record_id,
                match_group_id=group_id,
                message=message,
                observed_value=None,
                expected_value=None,
                status="open",
                exception_fingerprint=stable_fingerprint(
                    {
                        "version": VERSION,
                        "code": code,
                        "invoice": invoice_id,
                        "payment": payment_id,
                        "bank": bank_transaction_id,
                        "gl": gl_record_id,
                    }
                ),
                metadata_json={},
            )
        )

    def _aging(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        invoices: list[dict[str, str]],
        applications: list[dict[str, str]],
    ) -> None:
        applied: dict[str, Decimal] = defaultdict(Decimal)
        for item in applications:
            applied[item["invoice_id"]] += money(item["applied_amount"])
        by_customer: dict[str, list[tuple[dict[str, str], Decimal, str, int]]] = defaultdict(list)
        for invoice in invoices:
            outstanding = max(
                money(invoice["total_amount"]) - applied[invoice["invoice_id"]], Decimal(0)
            )
            if outstanding <= self.tolerance:
                continue
            bucket, days = aging_bucket(
                run.aging_as_of_date, date.fromisoformat(invoice["due_date"])
            )
            by_customer[invoice["customer_id"]].append((invoice, outstanding, bucket, days))
        for customer_id, items in sorted(by_customer.items()):
            totals = {
                key: sum((amount for _, amount, bucket, _ in items if bucket == key), Decimal(0))
                for key in ("current", "1_30", "31_60", "61_90", "over_90")
            }
            snapshot = AccountsReceivableAgingSnapshot(
                tenant_id=run.tenant_id,
                reconciliation_run_id=run.id,
                reconciliation_version=VERSION,
                as_of_date=run.aging_as_of_date,
                customer_id=customer_id,
                invoice_count=len(items),
                current_amount=totals["current"],
                days_1_30_amount=totals["1_30"],
                days_31_60_amount=totals["31_60"],
                days_61_90_amount=totals["61_90"],
                over_90_days_amount=totals["over_90"],
                total_outstanding=sum(totals.values(), Decimal(0)),
                disputed_amount=Decimal(0),
                unapplied_credit_amount=Decimal(0),
                metadata_json={},
            )
            session.add(snapshot)
            session.flush()
            for invoice, outstanding, bucket, days in items:
                session.add(
                    AccountsReceivableAgingBucket(
                        tenant_id=run.tenant_id,
                        aging_snapshot_id=snapshot.id,
                        reconciliation_version=VERSION,
                        invoice_id=invoice["invoice_id"],
                        customer_id=customer_id,
                        invoice_date=date.fromisoformat(invoice["invoice_date"]),
                        due_date=date.fromisoformat(invoice["due_date"]),
                        days_outstanding=days,
                        aging_bucket=bucket,
                        original_amount=money(invoice["total_amount"]),
                        applied_payment_amount=applied[invoice["invoice_id"]],
                        outstanding_amount=outstanding,
                        status="overdue" if bucket != "current" else "current",
                    )
                )

    def _controls(self, session: Session, run: InvoiceCollectionsReconciliationRun) -> None:
        components = {
            key: money(value)
            for key, value in ((run.metadata_json or {}).get("component_totals") or {}).items()
        }
        allocation_total = session.scalar(
            select(func.coalesce(func.sum(InvoiceCollectionsAllocation.allocated_amount), 0)).where(
                InvoiceCollectionsAllocation.reconciliation_run_id == run.id,
                InvoiceCollectionsAllocation.allocation_type == "payment_to_invoice",
            )
        )
        expected_invoice_total = (
            components.get("invoice_subtotal", Decimal(0))
            + components.get("invoice_tax", Decimal(0))
            - components.get("invoice_discount", Decimal(0))
        )
        controls = (
            (
                "invoice_line_subtotal",
                components.get("invoice_subtotal", 0),
                components.get("line_subtotal", 0),
                "invoice",
            ),
            (
                "invoice_tax_total",
                components.get("invoice_tax", 0),
                components.get("line_tax", 0),
                "invoice",
            ),
            (
                "invoice_discount_total",
                components.get("invoice_discount", 0),
                components.get("line_discount", 0),
                "invoice",
            ),
            ("invoice_total", expected_invoice_total, run.invoice_total, "invoice"),
            ("applied_payment_total", run.invoice_paid_total, run.applied_payment_total, "payment"),
            (
                "invoice_balance",
                run.invoice_total - run.applied_payment_total,
                run.invoice_balance_total,
                "invoice",
            ),
            (
                "payment_total",
                run.payment_total,
                run.applied_payment_total + run.unapplied_payment_total,
                "payment",
            ),
            (
                "payment_application_total",
                run.invoice_paid_total,
                run.applied_payment_total,
                "payment",
            ),
            (
                "unapplied_payment_total",
                run.payment_total - run.applied_payment_total,
                run.unapplied_payment_total,
                "payment",
            ),
            ("bank_deposit_total", run.payment_total, run.bank_deposit_total, "deposit"),
            ("gl_accounts_receivable_total", run.invoice_total, run.gl_receivable_total, "gl"),
            ("gl_cash_total", run.payment_total, run.gl_cash_total, "gl"),
            (
                "deal_value_vs_invoice_total",
                components.get("deal_value", 0),
                run.invoice_total,
                "invoice",
            ),
            (
                "invoice_vs_payment_difference",
                run.invoice_total,
                run.applied_payment_total,
                "payment",
            ),
            ("payment_vs_deposit_difference", run.payment_total, run.bank_deposit_total, "deposit"),
            ("invoice_vs_gl_difference", run.invoice_total, run.gl_receivable_total, "gl"),
            ("payment_vs_gl_difference", run.payment_total, run.gl_cash_total, "gl"),
            ("allocation_balance", run.applied_payment_total, money(allocation_total), "payment"),
            (
                "reconciliation_rate",
                run.matched_collection_total / run.invoice_total
                if run.invoice_total
                else Decimal(0),
                run.reconciliation_rate,
                "rate",
            ),
        )
        for name, expected_value, actual_value, dimension in controls:
            expected, actual = money(expected_value), money(actual_value)
            difference = money(actual - expected)
            session.add(
                InvoiceCollectionsControlTotal(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_version=VERSION,
                    customer_id=None,
                    invoice_id=None,
                    control_name=name,
                    invoice_value=expected if dimension in {"invoice", "rate"} else None,
                    payment_value=actual
                    if dimension in {"invoice", "payment", "rate"}
                    else expected,
                    deposit_value=actual if dimension == "deposit" else None,
                    gl_value=actual if dimension == "gl" else None,
                    difference_value=difference,
                    tolerance=self.tolerance,
                    status="matched" if abs(difference) <= self.tolerance else "mismatch",
                    metadata_json={
                        "dimension": dimension,
                        "expected": str(expected),
                        "actual": str(actual),
                    },
                )
            )
        session.flush()

    def _reports(
        self,
        session: Session,
        tenant_code: str,
        run: InvoiceCollectionsReconciliationRun,
        pipeline: PipelineRun,
    ) -> None:
        root = (
            self.settings.INVOICE_COLLECTIONS_REPORT_ROOT
            / tenant_code
            / f"run_{run.id:08d}_{run.input_fingerprint[:8]}"
        )
        root.mkdir(parents=True, exist_ok=False)
        groups = list(
            session.scalars(
                select(InvoiceCollectionsMatchGroup)
                .where(InvoiceCollectionsMatchGroup.reconciliation_run_id == run.id)
                .order_by(InvoiceCollectionsMatchGroup.id)
            )
        )
        exceptions = list(
            session.scalars(
                select(InvoiceCollectionsException)
                .where(InvoiceCollectionsException.reconciliation_run_id == run.id)
                .order_by(InvoiceCollectionsException.id)
            )
        )
        controls = list(
            session.scalars(
                select(InvoiceCollectionsControlTotal)
                .where(InvoiceCollectionsControlTotal.reconciliation_run_id == run.id)
                .order_by(InvoiceCollectionsControlTotal.control_name)
            )
        )
        aging = list(
            session.scalars(
                select(AccountsReceivableAgingBucket)
                .join(AccountsReceivableAgingSnapshot)
                .where(AccountsReceivableAgingSnapshot.reconciliation_run_id == run.id)
                .order_by(AccountsReceivableAgingBucket.invoice_id)
            )
        )
        matches = list(
            session.scalars(
                select(InvoiceCollectionsMatch)
                .where(InvoiceCollectionsMatch.reconciliation_run_id == run.id)
                .order_by(InvoiceCollectionsMatch.id)
            )
        )
        allocations = list(
            session.scalars(
                select(InvoiceCollectionsAllocation)
                .where(InvoiceCollectionsAllocation.reconciliation_run_id == run.id)
                .order_by(InvoiceCollectionsAllocation.id)
            )
        )
        group_rows = [
            {
                "group_id": g.id,
                "invoice_id": (g.metadata_json or {}).get("invoice", {}).get("invoice_id"),
                "status": g.status,
                "invoice_total": g.invoice_total,
                "payment_total": g.payment_total,
                "deposit_total": g.deposit_total,
                "gl_total": g.gl_total,
                "matched_amount": g.matched_amount,
                "confidence": g.confidence,
            }
            for g in groups
        ]
        exception_rows = [
            {
                "id": e.id,
                "code": e.exception_code,
                "severity": e.severity,
                "invoice_id": e.invoice_id,
                "payment_id": e.payment_id,
                "bank_transaction_id": e.bank_transaction_id,
                "gl_record_id": e.gl_record_id,
                "status": e.status,
                "message": e.message,
            }
            for e in exceptions
        ]
        payment_rows = [
            {
                "payment_id": m.payment_id,
                "invoice_id": m.invoice_id,
                "payment_application_id": m.payment_application_id,
                "bank_transaction_id": m.bank_transaction_id,
                "matched_amount": m.matched_amount,
                "status": m.status,
            }
            for m in matches
            if m.payment_id and m.match_component == "payment_application"
        ]
        application_rows = [
            {
                "payment_application_id": m.payment_application_id,
                "payment_id": m.payment_id,
                "invoice_id": m.invoice_id,
                "applied_amount": m.matched_amount,
                "status": m.status,
            }
            for m in matches
            if m.payment_application_id and m.match_component == "payment_application"
        ]
        deposit_rows = [
            {
                "payment_id": item.payment_id,
                "invoice_id": item.invoice_id,
                "bank_transaction_id": item.bank_transaction_id,
                "allocated_amount": item.allocated_amount,
            }
            for item in allocations
            if item.allocation_type == "payment_to_deposit"
        ]
        payloads: dict[str, tuple[str, Any]] = {
            "invoice_collections_summary": (
                "invoice_collections_summary.json",
                {
                    "run_id": run.id,
                    "version": VERSION,
                    "status": "completed_with_exceptions" if run.exception_count else "completed",
                    "invoice_total": str(run.invoice_total),
                    "matched_collection_total": str(run.matched_collection_total),
                    "reconciliation_rate": str(run.reconciliation_rate),
                },
            ),
            "invoice_reconciliation": ("invoice_reconciliation.csv", group_rows),
            "customer_payment_reconciliation": (
                "customer_payment_reconciliation.csv",
                payment_rows,
            ),
            "payment_applications": ("payment_applications.csv", application_rows),
            "bank_deposit_matches": ("bank_deposit_matches.csv", deposit_rows),
            "invoice_collections_suggestions": (
                "invoice_collections_suggestions.csv",
                [x for x in group_rows if x["status"] in {"suggested", "partially_matched"}],
            ),
            "invoice_collections_exceptions": (
                "invoice_collections_exceptions.csv",
                exception_rows,
            ),
            "unmatched_invoices": (
                "unmatched_invoices.csv",
                [x for x in group_rows if x["status"] == "unmatched"],
            ),
            "unmatched_payments": (
                "unmatched_payments.csv",
                [
                    x
                    for x in exception_rows
                    if x["code"]
                    in {"unmatched_payment", "unapplied_payment", "payment_without_invoice"}
                ],
            ),
            "unmatched_deposits": (
                "unmatched_deposits.csv",
                [x for x in exception_rows if x["code"] == "unmatched_bank_deposit"],
            ),
            "unmatched_ar_gl": (
                "unmatched_ar_gl.csv",
                [x for x in exception_rows if x["code"] == "unmatched_ar_gl"],
            ),
            "accounts_receivable_aging": (
                "accounts_receivable_aging.csv",
                [
                    {
                        "invoice_id": x.invoice_id,
                        "customer_id": x.customer_id,
                        "bucket": x.aging_bucket,
                        "days_outstanding": x.days_outstanding,
                        "outstanding_amount": x.outstanding_amount,
                    }
                    for x in aging
                ],
            ),
            "invoice_collections_controls": (
                "invoice_collections_controls.json",
                {
                    c.control_name: {
                        "invoice": str(c.invoice_value) if c.invoice_value is not None else None,
                        "payment": str(c.payment_value) if c.payment_value is not None else None,
                        "deposit": str(c.deposit_value) if c.deposit_value is not None else None,
                        "gl": str(c.gl_value) if c.gl_value is not None else None,
                        "difference": str(c.difference_value),
                        "status": c.status,
                    }
                    for c in controls
                },
            ),
            "duplicate_invoices": (
                "duplicate_invoices.csv",
                [x for x in exception_rows if x["code"] == "duplicate_invoice"],
            ),
            "duplicate_payments": (
                "duplicate_payments.csv",
                [x for x in exception_rows if x["code"] == "duplicate_payment"],
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
                headers = sorted({key for row in payload for key in row}) or ["no_records"]
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(payload)
                mime = "text/csv"
            relative = path.relative_to(self.data_root).as_posix()
            checksum = self._sha(path)
            session.add(
                InvoiceCollectionsReport(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    reconciliation_version=VERSION,
                    report_type=report_type,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type=mime,
                    file_size_bytes=path.stat().st_size,
                    metadata_json={
                        "tenant": tenant_code,
                        "row_count": len(payload) if isinstance(payload, list) else 1,
                    },
                )
            )
            session.add(
                PipelineRunArtifact(
                    tenant_id=run.tenant_id,
                    pipeline_run_id=pipeline.id,
                    artifact_type="invoice_collections_report",
                    name=filename,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type=mime,
                    file_size_bytes=path.stat().st_size,
                    metadata_json={"report_type": report_type},
                )
            )
        session.flush()

    def _record_reconciliation_audit_events(
        self,
        session: Session,
        run: InvoiceCollectionsReconciliationRun,
        pipeline: PipelineRun,
    ) -> None:
        groups = list(
            session.scalars(
                select(InvoiceCollectionsMatchGroup).where(
                    InvoiceCollectionsMatchGroup.reconciliation_run_id == run.id
                )
            )
        )
        exceptions = Counter(
            session.scalars(
                select(InvoiceCollectionsException.exception_code).where(
                    InvoiceCollectionsException.reconciliation_run_id == run.id
                )
            )
        )
        controls_mismatched = session.scalar(
            select(func.count())
            .select_from(InvoiceCollectionsControlTotal)
            .where(
                InvoiceCollectionsControlTotal.reconciliation_run_id == run.id,
                InvoiceCollectionsControlTotal.status == "mismatch",
            )
        )
        snapshot_count = session.scalar(
            select(func.count())
            .select_from(AccountsReceivableAgingSnapshot)
            .where(AccountsReceivableAgingSnapshot.reconciliation_run_id == run.id)
        )

        def record(event_type: str, description: str, count: int) -> None:
            if count <= 0:
                return
            session.add(
                AuditEvent(
                    tenant_id=run.tenant_id,
                    actor_user_id=None,
                    actor_type="system",
                    event_type=f"invoice_collections_reconciliation.{event_type}",
                    entity_type="invoice_collections_reconciliation_run",
                    entity_id=str(run.id),
                    action=event_type,
                    description=description,
                    pipeline_run_id=pipeline.id,
                    source_file_id=None,
                    metadata_json={"count": count, "version": VERSION},
                    occurred_at=datetime.now(UTC),
                )
            )

        automatic_count = sum(item.auto_accepted for item in groups)
        record("exact_invoice_match_accepted", "Exact invoice matches accepted", automatic_count)
        record("exact_payment_match_accepted", "Exact payment matches accepted", automatic_count)
        record(
            "exact_deposit_match_accepted",
            "Exact deposit matches accepted",
            sum(item.auto_accepted and item.deposit_total > 0 for item in groups),
        )
        record(
            "grouped_collection_match_created",
            "Grouped collection matches created",
            sum(
                item.group_type
                in {"multiple_payments_to_combined_deposit", "payment_to_split_deposits"}
                for item in groups
            ),
        )
        record(
            "partial_match_created",
            "Partial invoice collection matches created",
            sum(item.status == "partially_matched" for item in groups),
        )
        for exception_code, event_type in {
            "invoice_overpaid": "overpayment_detected",
            "invoice_underpaid": "underpayment_detected",
            "duplicate_invoice": "duplicate_invoice_detected",
            "duplicate_payment": "duplicate_payment_detected",
        }.items():
            record(
                event_type, event_type.replace("_", " ").capitalize(), exceptions[exception_code]
            )
        record("ar_aging_generated", "Accounts receivable aging generated", snapshot_count or 0)
        record(
            "control_total_mismatch",
            "Invoice collection control-total mismatches detected",
            controls_mismatched or 0,
        )
        reports = list(
            session.scalars(
                select(InvoiceCollectionsReport).where(
                    InvoiceCollectionsReport.reconciliation_run_id == run.id
                )
            )
        )
        for report in reports:
            session.add(
                AuditEvent(
                    tenant_id=run.tenant_id,
                    actor_user_id=None,
                    actor_type="system",
                    event_type="invoice_collections_reconciliation.report_generated",
                    entity_type="invoice_collections_report",
                    entity_id=str(report.id),
                    action="generate",
                    description="Invoice collections report generated",
                    pipeline_run_id=pipeline.id,
                    source_file_id=None,
                    metadata_json={"report_type": report.report_type, "version": VERSION},
                    occurred_at=datetime.now(UTC),
                )
            )
        session.flush()

    def verify_integrity(
        self, session: Session, run: InvoiceCollectionsReconciliationRun
    ) -> dict[str, Any]:
        reports = list(
            session.scalars(
                select(InvoiceCollectionsReport).where(
                    InvoiceCollectionsReport.reconciliation_run_id == run.id
                )
            )
        )
        if len(reports) != 15:
            raise InvoiceCollectionsError(f"Expected 15 reports, found {len(reports)}")
        expected_report_names = {
            "invoice_collections_summary.json",
            "invoice_reconciliation.csv",
            "customer_payment_reconciliation.csv",
            "payment_applications.csv",
            "bank_deposit_matches.csv",
            "invoice_collections_suggestions.csv",
            "invoice_collections_exceptions.csv",
            "unmatched_invoices.csv",
            "unmatched_payments.csv",
            "unmatched_deposits.csv",
            "unmatched_ar_gl.csv",
            "accounts_receivable_aging.csv",
            "invoice_collections_controls.json",
            "duplicate_invoices.csv",
            "duplicate_payments.csv",
        }
        if {Path(item.relative_path).name for item in reports} != expected_report_names:
            raise InvoiceCollectionsError("Registered report inventory is incomplete")
        for report in reports:
            if Path(report.relative_path).is_absolute():
                raise InvoiceCollectionsError("Absolute report path stored")
            path = self.data_root / report.relative_path
            if not path.is_file() or self._sha(path) != report.checksum:
                raise InvoiceCollectionsError(f"Report integrity failed: {report.report_type}")
            if path.suffix == ".csv":
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    actual_rows = sum(1 for _ in csv.DictReader(stream))
            else:
                actual_rows = 1
            if actual_rows != (report.metadata_json or {}).get("row_count"):
                raise InvoiceCollectionsError(f"Report row count failed: {report.report_type}")
        tenant_models = (
            InvoiceCollectionsCandidate,
            InvoiceCollectionsMatchGroup,
            InvoiceCollectionsMatch,
            InvoiceCollectionsAllocation,
            InvoiceCollectionsException,
            InvoiceCollectionsControlTotal,
            InvoiceCollectionsDecision,
            InvoiceCollectionsReport,
            AccountsReceivableAgingSnapshot,
        )
        for model in tenant_models:
            foreign_tenant_count = session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.reconciliation_run_id == run.id,
                    model.tenant_id != run.tenant_id,
                )
            )
            if foreign_tenant_count:
                raise InvoiceCollectionsError(
                    f"Cross-tenant records detected in {model.__tablename__}"
                )
        groups = list(
            session.scalars(
                select(InvoiceCollectionsMatchGroup).where(
                    InvoiceCollectionsMatchGroup.reconciliation_run_id == run.id
                )
            )
        )
        for group in groups:
            metadata = group.metadata_json or {}
            if group.group_type == "payment_to_split_deposits":
                expected = stable_fingerprint(
                    {
                        "version": VERSION,
                        "type": "split_deposit",
                        "payment": (metadata.get("payment") or {}).get("payment_id"),
                        "deposits": tuple(metadata.get("deposit_ids") or ()),
                    }
                )
            elif group.group_type == "multiple_payments_to_combined_deposit":
                expected = stable_fingerprint(
                    {
                        "version": VERSION,
                        "type": "combined_deposit",
                        "payments": tuple(metadata.get("payment_ids") or ()),
                        "deposit": metadata.get("deposit_id"),
                    }
                )
            else:
                invoice_id = (metadata.get("invoice") or {}).get("invoice_id")
                expected = stable_fingerprint({"version": VERSION, "invoice": invoice_id})
            if group.group_fingerprint != expected:
                raise InvoiceCollectionsError("Unstable match-group fingerprint")
            if group.matched_amount > min(group.invoice_total, group.payment_total):
                raise InvoiceCollectionsError("Match group over-allocates invoice or payment")
            if group.group_type.startswith("invoice_to_") and (
                abs(
                    group.remaining_amount
                    - max(group.invoice_total - group.payment_total, Decimal(0))
                )
                > self.tolerance
            ):
                raise InvoiceCollectionsError("Match group remaining balance is invalid")
            if group.auto_accepted and (
                group.status != "matched"
                or group.confidence
                < Decimal(str(self.settings.INVOICE_COLLECTIONS_MIN_AUTO_ACCEPT_CONFIDENCE))
                or not (group.metadata_json or {}).get("internal_total_valid")
                or not (group.metadata_json or {}).get("gl_valid")
            ):
                raise InvoiceCollectionsError("Auto-accepted group violates policy")
        candidates = list(
            session.scalars(
                select(InvoiceCollectionsCandidate).where(
                    InvoiceCollectionsCandidate.reconciliation_run_id == run.id
                )
            )
        )
        for candidate in candidates:
            expected = stable_fingerprint(
                {
                    "version": VERSION,
                    "kind": candidate.candidate_type,
                    "invoice": candidate.invoice_id,
                    "payment": candidate.payment_id,
                    "bank": candidate.bank_transaction_id,
                }
            )
            if candidate.candidate_fingerprint != expected:
                raise InvoiceCollectionsError("Unstable candidate fingerprint")
        allocations = list(
            session.scalars(
                select(InvoiceCollectionsAllocation).where(
                    InvoiceCollectionsAllocation.reconciliation_run_id == run.id
                )
            )
        )
        by_payment: dict[str, Decimal] = defaultdict(Decimal)
        by_deposit: dict[int, Decimal] = defaultdict(Decimal)
        by_gl: dict[str, Decimal] = defaultdict(Decimal)
        by_group_invoice: dict[int, Decimal] = defaultdict(Decimal)
        for item in allocations:
            if item.allocation_type == "payment_to_invoice" and item.payment_id:
                by_payment[item.payment_id] += item.allocated_amount
                by_group_invoice[item.match_group_id] += item.allocated_amount
            if item.allocation_type == "payment_to_deposit" and item.bank_transaction_id:
                by_deposit[item.bank_transaction_id] += item.allocated_amount
            if item.gl_record_id:
                by_gl[item.gl_record_id] += item.allocated_amount
        source_ids = (run.metadata_json or {}).get("source_files") or {}
        source_files = {
            key: session.get(GeneratedSourceFile, value) for key, value in source_ids.items()
        }
        source_checksums: dict[str, str] = {}
        for key, source in source_files.items():
            if source is None or source.tenant_id != run.tenant_id:
                raise InvoiceCollectionsError(f"Invalid selected source file: {key}")
            path = self.data_root / source.relative_path
            if not path.is_file() or self._sha(path) != source.sha256_checksum:
                raise InvoiceCollectionsError(f"Selected source integrity failed: {key}")
            source_checksums[key] = source.sha256_checksum
        validation = session.get(ValidationRun, run.validation_run_id)
        if validation is None or validation.tenant_id != run.tenant_id:
            raise InvoiceCollectionsError("Invalid validation run provenance")
        selected_deposits = self._deposits(
            session,
            run.tenant_id,
            run.bank_account_id,
            run.date_from,
            run.date_to,
        )
        recomputed_base_fingerprint = stable_fingerprint(
            {
                "period": [run.date_from, run.date_to, run.aging_as_of_date],
                "account": run.bank_account_id,
                "files": [[key, source_checksums[key]] for key in sorted(source_checksums)],
                "deposits": [
                    [key, value["hash"]] for key, value in sorted(selected_deposits.items())
                ],
                "validation": validation.input_fingerprint,
                "version": VERSION,
                "logic_revision": LOGIC_REVISION,
            }
        )
        run_metadata = run.metadata_json or {}
        if run_metadata.get("base_input_fingerprint") != recomputed_base_fingerprint:
            raise InvoiceCollectionsError("Input fingerprint provenance is invalid")
        if run_metadata.get("force_rerun"):
            forced_at = run_metadata.get("forced_at")
            expected_input_fingerprint = stable_fingerprint(
                {
                    "base_fingerprint": recomputed_base_fingerprint,
                    "forced_at": forced_at,
                }
            )
        else:
            expected_input_fingerprint = recomputed_base_fingerprint
        if run.input_fingerprint != expected_input_fingerprint:
            raise InvoiceCollectionsError("Stored input fingerprint is invalid")
        payment_source = source_files.get("customer_payments")
        invoice_source = source_files.get("invoices")
        line_source = source_files.get("invoice_lines")
        application_source = source_files.get("customer_payment_applications")
        gl_source = source_files.get("general_ledger")
        invoice_totals: dict[str, Decimal] = {}
        if invoice_source is not None:
            invoice_rows = self._read(invoice_source)
            invoice_totals = {
                source_invoice["invoice_id"]: money(source_invoice["total_amount"])
                for source_invoice in invoice_rows
            }
            for source_invoice in invoice_rows:
                expected_total = invoice_header_total(source_invoice)
                if expected_total is None or (
                    abs(expected_total - money(source_invoice["total_amount"])) > self.tolerance
                ):
                    raise InvoiceCollectionsError("Source invoice header does not balance")
        if line_source is not None:
            for source_line in self._read(line_source):
                if (
                    abs(invoice_line_total(source_line) - money(source_line["line_total"]))
                    > self.tolerance
                ):
                    raise InvoiceCollectionsError("Source invoice line does not balance")
        valid_payments: set[str] = set()
        if payment_source is not None:
            payment_totals = {
                source_payment["payment_id"]: money(source_payment["payment_amount"])
                for source_payment in self._read(payment_source)
            }
            valid_payments = set(payment_totals)
            if any(
                total > payment_totals.get(key, Decimal(0)) + self.tolerance
                for key, total in by_payment.items()
            ):
                raise InvoiceCollectionsError("Payment allocations exceed source payment amount")
        if application_source is not None:
            for source_application in self._read(application_source):
                if (
                    source_application["invoice_id"] not in invoice_totals
                    or source_application["payment_id"] not in valid_payments
                ):
                    raise InvoiceCollectionsError(
                        "Payment application references an invalid source"
                    )
        if gl_source is not None:
            gl_amounts: dict[str, Decimal] = {}
            for source_gl in self._read(gl_source):
                gl_record_id = source_gl.get("journal_line_id") or source_gl.get("source_record_id")
                if gl_record_id:
                    gl_amounts[gl_record_id] = max(
                        money(source_gl.get("debit")), money(source_gl.get("credit"))
                    )
            if any(
                allocated > gl_amounts.get(gl_record_id, Decimal(0)) + self.tolerance
                for gl_record_id, allocated in by_gl.items()
            ):
                raise InvoiceCollectionsError("GL record is over-allocated")
        by_invoice: dict[str, Decimal] = defaultdict(Decimal)
        for item in allocations:
            if item.allocation_type == "payment_to_invoice" and item.invoice_id:
                by_invoice[item.invoice_id] += item.allocated_amount
        overpaid_invoice_ids = {
            item.invoice_id
            for item in session.scalars(
                select(InvoiceCollectionsException).where(
                    InvoiceCollectionsException.reconciliation_run_id == run.id,
                    InvoiceCollectionsException.exception_code == "invoice_overpaid",
                )
            )
            if item.invoice_id
        }
        for invoice_id, allocated in by_invoice.items():
            if (
                allocated > invoice_totals.get(invoice_id, Decimal(0)) + self.tolerance
                and invoice_id not in overpaid_invoice_ids
            ):
                raise InvoiceCollectionsError("Invoice allocation exceeds source total")
        for group in groups:
            allocated = by_group_invoice.get(group.id, Decimal(0))
            if group.payment_total > 0 and abs(allocated - group.payment_total) > self.tolerance:
                raise InvoiceCollectionsError("Group payment allocations do not balance")
        for bank_id, allocated in by_deposit.items():
            bank = session.get(BankTransaction, bank_id)
            if bank is None or bank.tenant_id != run.tenant_id:
                raise InvoiceCollectionsError("Invalid bank-deposit allocation")
            transaction = session.get(FinancialTransaction, bank.financial_transaction_id)
            deposit_amount = money(bank.credit_amount or 0)
            if deposit_amount <= 0 and transaction is not None:
                deposit_amount = abs(money(transaction.amount))
            if allocated > deposit_amount + self.tolerance:
                raise InvoiceCollectionsError("Bank deposit is over-allocated")
        exceptions = list(
            session.scalars(
                select(InvoiceCollectionsException).where(
                    InvoiceCollectionsException.reconciliation_run_id == run.id
                )
            )
        )
        for exception in exceptions:
            expected = stable_fingerprint(
                {
                    "version": VERSION,
                    "code": exception.exception_code,
                    "invoice": exception.invoice_id,
                    "payment": exception.payment_id,
                    "bank": exception.bank_transaction_id,
                    "gl": exception.gl_record_id,
                }
            )
            if exception.exception_fingerprint != expected:
                raise InvoiceCollectionsError("Unstable exception fingerprint")
        decisions = list(
            session.scalars(
                select(InvoiceCollectionsDecision).where(
                    InvoiceCollectionsDecision.reconciliation_run_id == run.id
                )
            )
        )
        if decisions:
            group_ids = {str(item.match_group_id) for item in decisions}
            audit_count = session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == run.tenant_id,
                    AuditEvent.entity_type == "invoice_collections_match_group",
                    AuditEvent.entity_id.in_(group_ids),
                    AuditEvent.event_type.like("invoice_collections_reconciliation.%"),
                )
            )
            if (audit_count or 0) < len(decisions):
                raise InvoiceCollectionsError("Decision audit trail is incomplete")
        controls = list(
            session.scalars(
                select(InvoiceCollectionsControlTotal).where(
                    InvoiceCollectionsControlTotal.reconciliation_run_id == run.id
                )
            )
        )
        if len(controls) != 19:
            raise InvoiceCollectionsError(f"Expected 19 controls, found {len(controls)}")
        for control in controls:
            metadata = control.metadata_json or {}
            expected_difference = money(metadata.get("actual")) - money(metadata.get("expected"))
            if abs(expected_difference - money(control.difference_value)) > self.tolerance:
                raise InvoiceCollectionsError("Stored control-total difference is invalid")
        snapshots = list(
            session.scalars(
                select(AccountsReceivableAgingSnapshot).where(
                    AccountsReceivableAgingSnapshot.reconciliation_run_id == run.id
                )
            )
        )
        for snapshot in snapshots:
            total = (
                snapshot.current_amount
                + snapshot.days_1_30_amount
                + snapshot.days_31_60_amount
                + snapshot.days_61_90_amount
                + snapshot.over_90_days_amount
            )
            if abs(total - snapshot.total_outstanding) > self.tolerance:
                raise InvoiceCollectionsError("AR aging snapshot does not balance")
            buckets = list(
                session.scalars(
                    select(AccountsReceivableAgingBucket).where(
                        AccountsReceivableAgingBucket.aging_snapshot_id == snapshot.id
                    )
                )
            )
            bucket_total = sum((bucket.outstanding_amount for bucket in buckets), Decimal(0))
            if abs(bucket_total - snapshot.total_outstanding) > self.tolerance:
                raise InvoiceCollectionsError("AR aging invoice detail does not balance")
            for bucket in buckets:
                if bucket.outstanding_amount <= self.tolerance:
                    raise InvoiceCollectionsError("Paid invoice appears in AR aging")
                if (
                    abs(
                        bucket.original_amount
                        - bucket.applied_payment_amount
                        - bucket.outstanding_amount
                    )
                    > self.tolerance
                ):
                    raise InvoiceCollectionsError("AR aging remaining balance is invalid")
        active_rules = list(
            session.scalars(
                select(InvoiceCollectionsReconciliationRule)
                .where(
                    InvoiceCollectionsReconciliationRule.tenant_id == run.tenant_id,
                    InvoiceCollectionsReconciliationRule.version == VERSION,
                    InvoiceCollectionsReconciliationRule.is_active.is_(True),
                )
                .order_by(InvoiceCollectionsReconciliationRule.execution_order)
            )
        )
        current_ruleset = stable_fingerprint(
            {
                "rules": [
                    [
                        item.code,
                        item.version,
                        item.execution_order,
                        item.auto_accept,
                        str(item.minimum_confidence),
                        item.configuration_json,
                    ]
                    for item in active_rules
                ],
                "aging_buckets": self.settings.INVOICE_COLLECTIONS_AGING_BUCKETS,
            }
        )
        if current_ruleset != run.ruleset_fingerprint:
            raise InvoiceCollectionsError(
                "Ruleset fingerprint no longer matches active configuration"
            )
        summary = next(
            item for item in reports if item.report_type == "invoice_collections_summary"
        )
        summary_payload = json.loads(
            (self.data_root / summary.relative_path).read_text(encoding="utf-8")
        )
        if summary_payload.get("run_id") != run.id or money(
            summary_payload.get("invoice_total")
        ) != money(run.invoice_total):
            raise InvoiceCollectionsError("Summary report does not match database totals")
        return {
            "reports": len(reports),
            "aging_snapshots": len(snapshots),
            "groups": len(groups),
            "allocations": len(allocations),
            "controls": len(controls),
            "status": "passed",
        }
