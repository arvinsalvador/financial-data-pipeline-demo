import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import (
    BankTransaction,
    CanonicalRecordLineage,
    CreditCardTransaction,
    FinancialTransaction,
    PayrollEntry,
    PayrollRun,
)
from app.services.generated_sources import HEADERS
from app.services.messy.types import PRIMARY_KEYS
from app.services.validation_engine.types import (
    ValidationContext,
    ValidationDocument,
    ValidationFinding,
    ValidationRuleOutcome,
)

RuleFunction = Callable[[ValidationContext], ValidationRuleOutcome]
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")
REQUIRED: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id", "customer_name", "status"),
    "crm_deals": ("deal_id", "customer_id", "created_date", "pipeline_stage"),
    "invoices": (
        "invoice_id",
        "customer_id",
        "invoice_date",
        "due_date",
        "currency",
        "total_amount",
    ),
    "invoice_lines": ("invoice_line_id", "invoice_id", "line_total"),
    "customer_payments": (
        "payment_id",
        "payment_date",
        "currency",
        "payment_amount",
    ),
    "customer_payment_applications": (
        "payment_application_id",
        "payment_id",
        "invoice_id",
        "applied_amount",
    ),
    "vendors": ("vendor_id", "vendor_name", "status"),
    "accounts_payable": (
        "ap_bill_id",
        "vendor_id",
        "invoice_date",
        "due_date",
        "currency",
        "total_amount",
    ),
    "general_ledger": (
        "journal_entry_id",
        "journal_line_id",
        "entry_date",
        "account_code",
        "currency",
    ),
    "forecast_assumptions": (
        "assumption_id",
        "assumption_code",
        "scenario",
        "effective_date",
        "assumption_value",
    ),
}


def _out(
    findings: list[ValidationFinding], records: int, **details: object
) -> ValidationRuleOutcome:
    return ValidationRuleOutcome(findings, records, "failed" if findings else "passed", details)


def _finding(
    document: ValidationDocument,
    code: str,
    issue_type: str,
    message: str,
    row: int | None = None,
    column: str | None = None,
    observed: str | None = None,
    expected: str | None = None,
    entity_key: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code,
        issue_type,
        document.file_type,
        message,
        document.filename,
        document.source_file_id,
        row,
        column,
        entity_key,
        observed,
        expected,
    )


def _decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return Decimal(0)
    normalized = value.strip().replace(",", "")
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
    normalized = normalized.lstrip("$")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def schema_expected(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for document in context.documents.values():
        duplicate_headers = [name for name, count in Counter(document.headers).items() if count > 1]
        for header in duplicate_headers:
            findings.append(
                _finding(
                    document,
                    "DUPLICATE_COLUMN",
                    "schema",
                    "Duplicate column",
                    column=header,
                    observed=header,
                )
            )
        expected = list(HEADERS.get(document.file_type, ()))
        if expected:
            missing = [column for column in expected if column not in document.headers]
            unexpected = [column for column in document.headers if column not in expected]
            if missing:
                findings.append(
                    _finding(
                        document,
                        "MISSING_COLUMNS",
                        "schema",
                        "Required columns are missing",
                        observed=",".join(missing),
                        expected=",".join(expected),
                    )
                )
            if unexpected:
                findings.append(
                    _finding(
                        document,
                        "UNEXPECTED_COLUMNS",
                        "schema",
                        "Unexpected columns were found",
                        observed=",".join(unexpected),
                        expected=",".join(expected),
                    )
                )
            if not missing and not unexpected and document.headers != expected:
                findings.append(
                    _finding(
                        document,
                        "INVALID_COLUMN_ORDER",
                        "schema",
                        "Column order differs from the versioned schema",
                        observed=",".join(document.headers),
                        expected=",".join(expected),
                    )
                )
        for number, row in enumerate(document.rows, 2):
            if len(row) != len(document.headers):
                findings.append(
                    _finding(
                        document,
                        "MALFORMED_ROW",
                        "schema",
                        "Row field count differs from header",
                        number,
                        observed=str(len(row)),
                        expected=str(len(document.headers)),
                    )
                )
    return _out(findings, context.record_count)


def schema_nonempty(context: ValidationContext) -> ValidationRuleOutcome:
    findings = [
        _finding(document, "EMPTY_FILE", "schema", "File contains no data rows")
        for document in context.documents.values()
        if not document.rows
    ]
    return _out(findings, context.record_count)


def required_fields(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for document in context.documents.values():
        required = REQUIRED.get(document.file_type, ())
        for row_number, row in enumerate(document.dictionaries(), 2):
            key = row.get(PRIMARY_KEYS.get(document.file_type, ""))
            for column in required:
                if column in document.headers and not row.get(column, "").strip():
                    findings.append(
                        _finding(
                            document,
                            "MISSING_REQUIRED_FIELD",
                            "required_field",
                            f"Required field {column} is blank",
                            row_number,
                            column,
                            "",
                            "non-empty",
                            key,
                        )
                    )
    return _out(findings, context.record_count)


def identifiers(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    valid = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
    for document in context.documents.values():
        key_column = PRIMARY_KEYS.get(document.file_type)
        if not key_column or key_column not in document.headers:
            continue
        for row_number, row in enumerate(document.dictionaries(), 2):
            value = row.get(key_column, "")
            if not value:
                findings.append(
                    _finding(
                        document,
                        "BLANK_IDENTIFIER",
                        "identifier",
                        "Primary identifier is blank",
                        row_number,
                        key_column,
                        value,
                        "valid identifier",
                    )
                )
            elif not valid.fullmatch(value):
                findings.append(
                    _finding(
                        document,
                        "INVALID_IDENTIFIER",
                        "identifier",
                        "Identifier format or length is invalid",
                        row_number,
                        key_column,
                        value,
                        "1-255 safe characters",
                        value,
                    )
                )
    return _out(findings, context.record_count)


def dates(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for document in context.documents.values():
        date_columns = [
            column for column in document.headers if "date" in column or "period_" in column
        ]
        for row_number, row in enumerate(document.dictionaries(), 2):
            key = row.get(PRIMARY_KEYS.get(document.file_type, ""))
            for column in date_columns:
                value = row.get(column, "").strip()
                if not value:
                    continue
                parsed: date | None = None
                for date_format in DATE_FORMATS:
                    try:
                        parsed = datetime.strptime(value, date_format).date()
                        break
                    except ValueError:
                        pass
                if parsed is None:
                    findings.append(
                        _finding(
                            document,
                            "INVALID_DATE",
                            "date",
                            "Date cannot be parsed using supported formats",
                            row_number,
                            column,
                            value,
                            "ISO date",
                            key,
                        )
                    )
                elif parsed > date(2098, 12, 31):
                    findings.append(
                        _finding(
                            document,
                            "FUTURE_DATE",
                            "date",
                            "Date exceeds the deterministic future-date boundary",
                            row_number,
                            column,
                            value,
                            "on or before 2098-12-31",
                            key,
                        )
                    )
    return _out(findings, context.record_count)


def monetary(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    tokens = (
        "amount",
        "total",
        "balance",
        "debit",
        "credit",
        "price",
        "cost",
        "value",
        "limit",
        "contribution",
        "deduction",
    )
    for document in context.documents.values():
        columns = [
            column
            for column in document.headers
            if (
                any(token in column for token in tokens)
                or column in {"gross_pay", "net_pay", "regular_pay", "overtime_pay", "bonus_pay"}
            )
            and column not in {"payment_terms_days"}
        ]
        for row_number, row in enumerate(document.dictionaries(), 2):
            key = row.get(PRIMARY_KEYS.get(document.file_type, ""))
            for column in columns:
                value = row.get(column, "")
                parsed = _decimal(value)
                if parsed is None:
                    findings.append(
                        _finding(
                            document,
                            "INVALID_DECIMAL",
                            "monetary",
                            "Monetary value is invalid",
                            row_number,
                            column,
                            value,
                            "decimal",
                            key,
                        )
                    )
                else:
                    if parsed != parsed.quantize(Decimal("0.01")):
                        findings.append(
                            _finding(
                                document,
                                "ROUNDING_PROBLEM",
                                "monetary",
                                "Monetary value has more than two decimal places",
                                row_number,
                                column,
                                value,
                                "two decimal places",
                                key,
                            )
                        )
            currency = row.get("currency")
            if currency and not re.fullmatch(r"[A-Z]{3}", currency):
                findings.append(
                    _finding(
                        document,
                        "INVALID_CURRENCY",
                        "monetary",
                        "Currency must be a three-letter uppercase code",
                        row_number,
                        "currency",
                        currency,
                        "ISO-like currency code",
                        key,
                    )
                )
    return _out(findings, context.record_count)


def duplicate_rows(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for document in context.documents.values():
        seen: dict[tuple[str, ...], int] = {}
        for row_number, row in enumerate(document.rows, 2):
            value = tuple(row)
            if value in seen:
                findings.append(
                    _finding(
                        document,
                        "DUPLICATE_ROW",
                        "duplicate",
                        "Exact duplicate row",
                        row_number,
                        observed=str(seen[value]),
                        expected="unique row",
                    )
                )
            else:
                seen[value] = row_number
    return _out(findings, context.record_count)


def duplicate_identifiers(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for document in context.documents.values():
        column = PRIMARY_KEYS.get(document.file_type)
        if not column:
            continue
        seen: dict[str, int] = {}
        for row_number, row in enumerate(document.dictionaries(), 2):
            value = row.get(column, "")
            if value and value in seen:
                findings.append(
                    _finding(
                        document,
                        "DUPLICATE_IDENTIFIER",
                        "duplicate",
                        "Identifier is duplicated",
                        row_number,
                        column,
                        value,
                        "unique identifier",
                        value,
                    )
                )
            elif value:
                seen[value] = row_number
    return _out(findings, context.record_count)


def relationships(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    relationship_map = {
        "crm_deals": (("customer_id", "customers", "customer_id"),),
        "invoices": (
            ("customer_id", "customers", "customer_id"),
            ("deal_id", "crm_deals", "deal_id"),
        ),
        "invoice_lines": (("invoice_id", "invoices", "invoice_id"),),
        "customer_payment_applications": (
            ("payment_id", "customer_payments", "payment_id"),
            ("invoice_id", "invoices", "invoice_id"),
        ),
        "accounts_payable": (("vendor_id", "vendors", "vendor_id"),),
    }
    for file_type, links in relationship_map.items():
        document = context.documents.get(file_type)
        if document is None:
            continue
        for column, parent_type, parent_column in links:
            parent = context.documents.get(parent_type)
            if parent is None:
                continue
            valid = {row.get(parent_column, "") for row in parent.dictionaries()}
            for row_number, row in enumerate(document.dictionaries(), 2):
                value = row.get(column, "")
                if value and value not in valid:
                    findings.append(
                        _finding(
                            document,
                            "ORPHAN_RELATIONSHIP",
                            "relationship",
                            f"{column} does not reference {parent_type}",
                            row_number,
                            column,
                            value,
                            f"existing {parent_type}",
                            row.get(PRIMARY_KEYS.get(file_type, "")),
                        )
                    )
    return _out(findings, context.record_count)


def canonical_lineage(context: ValidationContext) -> ValidationRuleOutcome:
    expected = {
        "bank_transaction": set(
            context.session.scalars(
                select(BankTransaction.id).where(BankTransaction.tenant_id == context.tenant_id)
            )
        ),
        "credit_card_transaction": set(
            context.session.scalars(
                select(CreditCardTransaction.id).where(
                    CreditCardTransaction.tenant_id == context.tenant_id
                )
            )
        ),
        "payroll_entry": set(
            context.session.scalars(
                select(PayrollEntry.id).where(PayrollEntry.tenant_id == context.tenant_id)
            )
        ),
    }
    findings: list[ValidationFinding] = []
    for entity_type, identifiers in expected.items():
        lineage_ids = set(
            context.session.scalars(
                select(CanonicalRecordLineage.canonical_entity_id).where(
                    CanonicalRecordLineage.tenant_id == context.tenant_id,
                    CanonicalRecordLineage.canonical_entity_type == entity_type,
                )
            )
        )
        for identifier in sorted(identifiers - lineage_ids):
            findings.append(
                ValidationFinding(
                    "MISSING_LINEAGE",
                    "relationship",
                    entity_type,
                    f"Canonical {entity_type} has no lineage",
                    entity_key=str(identifier),
                    observed=str(identifier),
                    expected="lineage row",
                )
            )
    return _out(findings, sum(len(values) for values in expected.values()))


def invoice_totals(context: ValidationContext) -> ValidationRuleOutcome:
    invoices, lines = context.documents.get("invoices"), context.documents.get("invoice_lines")
    if not invoices or not lines:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "invoice files unavailable"})
    line_totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in lines.dictionaries():
        line_totals[row.get("invoice_id", "")] += _decimal(row.get("line_total")) or Decimal(0)
    findings: list[ValidationFinding] = []
    for number, row in enumerate(invoices.dictionaries(), 2):
        invoice_id = row.get("invoice_id", "")
        total = _decimal(row.get("total_amount"))
        if total is not None and total != line_totals[invoice_id]:
            findings.append(
                _finding(
                    invoices,
                    "INVOICE_LINE_TOTAL_MISMATCH",
                    "financial",
                    "Invoice total does not equal invoice lines",
                    number,
                    "total_amount",
                    str(total),
                    str(line_totals[invoice_id]),
                    invoice_id,
                )
            )
    return _out(findings, len(invoices.rows))


def payment_totals(context: ValidationContext) -> ValidationRuleOutcome:
    payments, applications = (
        context.documents.get("customer_payments"),
        context.documents.get("customer_payment_applications"),
    )
    if not payments or not applications:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "payment files unavailable"})
    applied: dict[str, Decimal] = defaultdict(Decimal)
    for row in applications.dictionaries():
        applied[row.get("payment_id", "")] += _decimal(row.get("applied_amount")) or Decimal(0)
    findings: list[ValidationFinding] = []
    for number, row in enumerate(payments.dictionaries(), 2):
        key = row.get("payment_id", "")
        amount = _decimal(row.get("payment_amount"))
        if amount is not None and amount != applied[key]:
            findings.append(
                _finding(
                    payments,
                    "PAYMENT_APPLICATION_MISMATCH",
                    "financial",
                    "Payment amount does not equal applications",
                    number,
                    "payment_amount",
                    str(amount),
                    str(applied[key]),
                    key,
                )
            )
    return _out(findings, len(payments.rows))


def ap_totals(context: ValidationContext) -> ValidationRuleOutcome:
    document = context.documents.get("accounts_payable")
    if document is None:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "AP file unavailable"})
    findings: list[ValidationFinding] = []
    for number, row in enumerate(document.dictionaries(), 2):
        key = row.get("ap_bill_id", "")
        total = _decimal(row.get("total_amount"))
        expected = (_decimal(row.get("subtotal")) or Decimal(0)) + (
            _decimal(row.get("tax_amount")) or Decimal(0)
        )
        if total is not None and total != expected:
            findings.append(
                _finding(
                    document,
                    "AP_TOTAL_MISMATCH",
                    "financial",
                    "AP total does not equal subtotal plus tax",
                    number,
                    "total_amount",
                    str(total),
                    str(expected),
                    key,
                )
            )
    return _out(findings, len(document.rows))


def gl_balanced(context: ValidationContext) -> ValidationRuleOutcome:
    document = context.documents.get("general_ledger")
    if document is None:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "GL file unavailable"})
    totals: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in document.dictionaries():
        entry = row.get("journal_entry_id", "")
        totals[entry][0] += _decimal(row.get("debit")) or Decimal(0)
        totals[entry][1] += _decimal(row.get("credit")) or Decimal(0)
    findings = [
        _finding(
            document,
            "UNBALANCED_JOURNAL",
            "financial",
            "Journal debits do not equal credits",
            column="journal_entry_id",
            observed=str(debit),
            expected=str(credit),
            entity_key=entry,
        )
        for entry, (debit, credit) in totals.items()
        if debit != credit
    ]
    return _out(findings, len(document.rows))


def payroll_totals(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    runs = context.session.scalars(
        select(PayrollRun).where(PayrollRun.tenant_id == context.tenant_id)
    ).all()
    for run in runs:
        entries = context.session.scalars(
            select(PayrollEntry).where(PayrollEntry.payroll_run_id == run.id)
        ).all()
        gross = sum((entry.gross_pay or Decimal(0) for entry in entries), Decimal(0))
        net = sum((entry.net_pay or Decimal(0) for entry in entries), Decimal(0))
        if run.gross_pay_total is not None and gross != run.gross_pay_total:
            findings.append(
                ValidationFinding(
                    "PAYROLL_GROSS_MISMATCH",
                    "financial",
                    "payroll",
                    "Payroll gross total differs from entries",
                    entity_key=str(run.id),
                    observed=str(run.gross_pay_total),
                    expected=str(gross),
                )
            )
        if run.net_pay_total is not None and net != run.net_pay_total:
            findings.append(
                ValidationFinding(
                    "PAYROLL_NET_MISMATCH",
                    "financial",
                    "payroll",
                    "Payroll net total differs from entries",
                    entity_key=str(run.id),
                    observed=str(run.net_pay_total),
                    expected=str(net),
                )
            )
    return _out(findings, len(runs))


def running_balances(context: ValidationContext) -> ValidationRuleOutcome:
    rows = context.session.execute(
        select(BankTransaction, FinancialTransaction)
        .join(
            FinancialTransaction,
            FinancialTransaction.id == BankTransaction.financial_transaction_id,
        )
        .where(BankTransaction.tenant_id == context.tenant_id)
        .order_by(
            BankTransaction.bank_account_id,
            FinancialTransaction.source_row_number,
        )
    ).all()
    findings: list[ValidationFinding] = []
    previous: dict[int, Decimal] = {}
    for bank, transaction in rows:
        if bank.running_balance is None:
            continue
        prior = previous.get(bank.bank_account_id)
        if prior is not None:
            observed_movement = abs(bank.running_balance - prior)
            expected_movement = abs(transaction.amount)
            if abs(observed_movement - expected_movement) > Decimal("0.01"):
                findings.append(
                    ValidationFinding(
                        "RUNNING_BALANCE_MISMATCH",
                        "financial",
                        "bank_transaction",
                        "Opening balance plus or minus movement does not equal closing balance",
                        entity_key=str(bank.id),
                        observed=str(observed_movement),
                        expected=str(expected_movement),
                    )
                )
        previous[bank.bank_account_id] = bank.running_balance
    return _out(findings, len(rows))


def control_rule(name: str) -> RuleFunction:
    def validate(context: ValidationContext) -> ValidationRuleOutcome:
        if name == "ingestion:" and context.target_type not in {
            "tenant",
            "pipeline",
            "source_file",
        }:
            return ValidationRuleOutcome([], 0, "skipped", {"reason": "not an ingestion target"})
        relevant = {
            key: value for key, value in context.control_statuses.items() if key.startswith(name)
        }
        findings = [
            ValidationFinding(
                "CONTROL_TOTAL_MISMATCH",
                "control",
                "pipeline",
                f"Control {key} did not pass",
                entity_key=key,
                observed=value,
                expected="passed",
            )
            for key, value in relevant.items()
            if value not in {"passed", "matched"}
        ]
        return _out(findings, len(relevant), controls=relevant)

    return validate


def messy_expected(context: ValidationContext) -> ValidationRuleOutcome:
    if context.target_type != "messy_dataset":
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "not a messy dataset"})
    findings = []
    if context.expected_exception_count != context.applied_mutation_count:
        findings.append(
            ValidationFinding(
                "MESSY_EXPECTED_COUNT_MISMATCH",
                "control",
                "messy_dataset",
                "Expected exceptions do not equal applied mutations",
                entity_key=str(context.target_id),
                observed=str(context.expected_exception_count),
                expected=str(context.applied_mutation_count),
            )
        )
    return _out(findings, context.applied_mutation_count)


def invoice_date_order(context: ValidationContext) -> ValidationRuleOutcome:
    document = context.documents.get("invoices")
    if document is None:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "invoice file unavailable"})
    findings: list[ValidationFinding] = []
    for number, row in enumerate(document.dictionaries(), 2):
        try:
            issued, due = (
                date.fromisoformat(row.get("invoice_date", "")),
                date.fromisoformat(row.get("due_date", "")),
            )
        except ValueError:
            continue
        if due < issued:
            findings.append(
                _finding(
                    document,
                    "DUE_BEFORE_INVOICE",
                    "business",
                    "Invoice due date precedes issue date",
                    number,
                    "due_date",
                    due.isoformat(),
                    f"on or after {issued.isoformat()}",
                    row.get("invoice_id"),
                )
            )
    return _out(findings, len(document.rows))


def payment_after_invoice(context: ValidationContext) -> ValidationRuleOutcome:
    payments, applications, invoices = (
        context.documents.get("customer_payments"),
        context.documents.get("customer_payment_applications"),
        context.documents.get("invoices"),
    )
    if not payments or not applications or not invoices:
        return ValidationRuleOutcome(
            [], 0, "skipped", {"reason": "payment relationship files unavailable"}
        )
    invoice_dates = {
        row.get("invoice_id", ""): row.get("invoice_date", "") for row in invoices.dictionaries()
    }
    payment_dates = {
        row.get("payment_id", ""): row.get("payment_date", "") for row in payments.dictionaries()
    }
    findings: list[ValidationFinding] = []
    for number, row in enumerate(applications.dictionaries(), 2):
        payment_date, invoice_date = (
            payment_dates.get(row.get("payment_id", ""), ""),
            invoice_dates.get(row.get("invoice_id", ""), ""),
        )
        if payment_date and invoice_date and payment_date < invoice_date:
            findings.append(
                _finding(
                    applications,
                    "PAYMENT_BEFORE_INVOICE",
                    "business",
                    "Customer payment precedes invoice",
                    number,
                    "payment_id",
                    payment_date,
                    f"on or after {invoice_date}",
                    row.get("payment_application_id"),
                )
            )
    return _out(findings, len(applications.rows))


def lost_deal(context: ValidationContext) -> ValidationRuleOutcome:
    document = context.documents.get("crm_deals")
    if document is None:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "CRM file unavailable"})
    findings = [
        _finding(
            document,
            "LOST_DEAL_INVOICED",
            "business",
            "Closed-lost deal references an invoice",
            number,
            "related_invoice_id",
            row.get("related_invoice_id"),
            "blank",
            row.get("deal_id"),
        )
        for number, row in enumerate(document.dictionaries(), 2)
        if row.get("pipeline_stage") == "closed_lost" and row.get("related_invoice_id")
    ]
    return _out(findings, len(document.rows))


def inactive_relationships(context: ValidationContext) -> ValidationRuleOutcome:
    findings: list[ValidationFinding] = []
    for file_type in ("customers", "vendors"):
        document = context.documents.get(file_type)
        if document is None:
            continue
        for number, row in enumerate(document.dictionaries(), 2):
            if row.get("status") == "inactive":
                findings.append(
                    _finding(
                        document,
                        "INACTIVE_MASTER_RECORD",
                        "business",
                        "Inactive master record is present in active dataset",
                        number,
                        "status",
                        "inactive",
                        "active",
                        row.get(PRIMARY_KEYS.get(file_type, "")),
                    )
                )
    return _out(findings, context.record_count)


def cross_relationship(context: ValidationContext) -> ValidationRuleOutcome:
    return relationships(context)


def cross_forecast(context: ValidationContext) -> ValidationRuleOutcome:
    document = context.documents.get("forecast_assumptions")
    if document is None:
        return ValidationRuleOutcome([], 0, "skipped", {"reason": "forecast file unavailable"})
    findings: list[ValidationFinding] = []
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(document.dictionaries(), 2):
        key = (row.get("assumption_category", ""), row.get("scenario", ""))
        if key in seen:
            findings.append(
                _finding(
                    document,
                    "DUPLICATE_FORECAST_ASSUMPTION",
                    "cross_file",
                    "Forecast category and scenario are duplicated",
                    number,
                    entity_key=row.get("assumption_id"),
                )
            )
        seen.add(key)
        if row.get("scenario") not in {"base", "conservative", "optimistic"}:
            findings.append(
                _finding(
                    document,
                    "INVALID_FORECAST_SCENARIO",
                    "cross_file",
                    "Forecast scenario is unsupported",
                    number,
                    "scenario",
                    row.get("scenario"),
                    "base, conservative, or optimistic",
                    row.get("assumption_id"),
                )
            )
    return _out(findings, len(document.rows))


def skipped(_context: ValidationContext) -> ValidationRuleOutcome:
    return ValidationRuleOutcome(
        [], 0, "skipped", {"reason": "target does not expose this measure"}
    )


@dataclass(frozen=True)
class ValidationRulePlugin:
    code: str
    execute: RuleFunction


class ValidationRuleRegistry:
    def __init__(self) -> None:
        functions: dict[str, RuleFunction] = {
            "schema_expected_columns": schema_expected,
            "schema_nonempty": schema_nonempty,
            "required_fields": required_fields,
            "identifier_presence_format": identifiers,
            "date_values": dates,
            "monetary_values": monetary,
            "duplicate_rows": duplicate_rows,
            "duplicate_identifiers": duplicate_identifiers,
            "relationships": relationships,
            "canonical_lineage": canonical_lineage,
            "invoice_totals": invoice_totals,
            "payment_totals": payment_totals,
            "ap_totals": ap_totals,
            "gl_balanced": gl_balanced,
            "payroll_totals": payroll_totals,
            "running_balances": running_balances,
            "ingestion_control_reconciliation": control_rule("ingestion:"),
            "generated_controls": control_rule("generated:"),
            "messy_expected_counts": messy_expected,
            "invoice_date_order": invoice_date_order,
            "payment_after_invoice": payment_after_invoice,
            "lost_deal_not_invoiced": lost_deal,
            "inactive_relationships": inactive_relationships,
            "cross_file_payment_links": cross_relationship,
            "cross_file_ap_vendor": cross_relationship,
            "cross_file_forecast": cross_forecast,
        }
        self.plugins = {
            code: ValidationRulePlugin(code, function) for code, function in functions.items()
        }

    def get(self, code: str) -> ValidationRulePlugin | None:
        return self.plugins.get(code)
