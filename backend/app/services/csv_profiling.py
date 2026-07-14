import csv
import hashlib
import io
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    DataQualityIssue,
    PipelineDefinition,
    PipelineRun,
    PipelineRunStep,
    SourceFile,
    SourceFileColumnProfile,
    SourceFileProfile,
)
from app.services.profile_parsing import parse_date, parse_decimal
from app.services.profiling_config import PROFILE_STEPS, identify_columns


class ProfilingError(Exception):
    pass


@dataclass
class IssueData:
    code: str
    issue_type: str
    severity: str
    message: str
    column: str | None = None
    row: int | None = None
    observed: str | None = None
    expected: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ColumnData:
    name: str
    position: int
    inferred_type: str
    row_count: int
    null_count: int
    unique_count: int
    minimum: str | None = None
    maximum: str | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    standard_deviation: Decimal | None = None
    minimum_length: int | None = None
    maximum_length: int | None = None
    average_length: Decimal | None = None
    earliest_date: date | None = None
    latest_date: date | None = None
    samples: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    encoding: str | None = None
    delimiter: str | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    empty_rows: int = 0
    duplicate_rows: int = 0
    columns: list[ColumnData] = field(default_factory=list)
    issues: list[IssueData] = field(default_factory=list)
    concepts: dict[str, str] = field(default_factory=dict)
    monetary_total: Decimal | None = None
    debit_total: Decimal | None = None
    credit_total: Decimal | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    calculated_closing_balance: Decimal | None = None
    running_balance_valid: bool | None = None


def issue_fingerprint(source_file_id: int, version: str, issue: IssueData) -> str:
    identity = f"{source_file_id}|{version}|{issue.code}|{issue.column or ''}|{issue.row or ''}"
    return hashlib.sha256(identity.encode()).hexdigest()


def detect_encoding(raw: bytes, supported: list[str]) -> tuple[str | None, str | None]:
    for encoding in supported:
        try:
            raw.decode(encoding)
            detected = (
                "utf-8-sig"
                if raw.startswith(b"\xef\xbb\xbf")
                else ("utf-8" if encoding == "utf-8-sig" else encoding)
            )
            return detected, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None, None


def detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _add_issue(analysis: Analysis, code: str, severity: str, message: str, **kwargs: Any) -> None:
    analysis.issues.append(IssueData(code, "data_quality", severity, message, **kwargs))


def inspect_csv(raw: bytes, settings: Settings) -> Analysis:
    analysis = Analysis()
    encoding, text = detect_encoding(raw, settings.supported_encodings)
    analysis.encoding = encoding
    if text is None:
        _add_issue(analysis, "unsupported_encoding", "critical", "CSV encoding is not supported.")
        return analysis
    if not text.strip():
        _add_issue(analysis, "empty_file", "critical", "The registered CSV is empty.")
        return analysis
    analysis.delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=analysis.delimiter)
    records = list(reader)
    if not records:
        _add_issue(analysis, "empty_file", "critical", "The registered CSV is empty.")
        return analysis
    analysis.headers = [header.strip() for header in records[0]]
    if not analysis.headers or all(not header for header in analysis.headers):
        _add_issue(
            analysis, "missing_header", "critical", "The CSV does not contain a usable header."
        )
        return analysis
    seen_headers = Counter(analysis.headers)
    for position, header in enumerate(analysis.headers):
        if not header:
            _add_issue(
                analysis,
                "blank_column_name",
                "error",
                "A column name is blank.",
                row=1,
                observed=str(position + 1),
            )
        elif seen_headers[header] > 1:
            _add_issue(
                analysis,
                "duplicate_column_name",
                "error",
                "A column name occurs more than once.",
                column=header,
            )
    for line_number, row in enumerate(records[1:], start=2):
        if not row or all(not value.strip() for value in row):
            analysis.empty_rows += 1
            _add_issue(
                analysis,
                "completely_empty_row",
                "info",
                "The row is completely empty.",
                row=line_number,
            )
            continue
        if len(row) > len(analysis.headers):
            _add_issue(
                analysis,
                "row_too_many_fields",
                "error",
                "The row has more fields than the header.",
                row=line_number,
                observed=str(len(row)),
                expected=str(len(analysis.headers)),
            )
            row = row[: len(analysis.headers)]
        elif len(row) < len(analysis.headers):
            _add_issue(
                analysis,
                "row_too_few_fields",
                "error",
                "The row has fewer fields than the header.",
                row=line_number,
                observed=str(len(row)),
                expected=str(len(analysis.headers)),
            )
            row = [*row, *([""] * (len(analysis.headers) - len(row)))]
        analysis.rows.append([value.strip() for value in row])
        if len(analysis.rows) >= settings.MAX_PROFILING_ROW_COUNT:
            _add_issue(
                analysis,
                "profiling_row_limit",
                "warning",
                "Profiling stopped at the configured row safety limit.",
            )
            break
    counts = Counter(tuple(row) for row in analysis.rows)
    analysis.duplicate_rows = sum(count - 1 for count in counts.values() if count > 1)
    if analysis.duplicate_rows:
        _add_issue(
            analysis,
            "duplicate_rows",
            "warning",
            f"Found {analysis.duplicate_rows} duplicate data row(s).",
            observed=str(analysis.duplicate_rows),
        )
    analysis.concepts = identify_columns(analysis.headers)
    if not ({"amount", "debit", "credit"} & analysis.concepts.keys()):
        _add_issue(
            analysis,
            "required_financial_field_not_found",
            "warning",
            "No amount, debit, or credit candidate column was found.",
        )
    return analysis


def _infer_column(
    name: str, position: int, values: list[str], analysis: Analysis, settings: Settings
) -> ColumnData:
    non_null = [value for value in values if value != ""]
    unique_values = list(dict.fromkeys(non_null))
    concept = next((key for key, header in analysis.concepts.items() if header == name), None)
    numeric_values: list[Decimal] = []
    parsed_dates = []
    date_formats: list[str] = []
    ambiguous_dates = 0
    for row_number, value in enumerate(values, start=2):
        if not value:
            if concept in {"transaction_date", "amount", "debit", "credit", "balance"}:
                _add_issue(
                    analysis,
                    "unexpected_null_value",
                    "warning",
                    "A financial candidate column contains a null value.",
                    column=name,
                    row=row_number,
                )
            continue
        if concept in {"amount", "debit", "credit", "balance"}:
            parsed = parse_decimal(value, currency=True)
            if parsed is None:
                _add_issue(
                    analysis,
                    "invalid_monetary_value",
                    "error",
                    "Value cannot be parsed as money.",
                    column=name,
                    row=row_number,
                    observed=value,
                )
            else:
                numeric_values.append(parsed)
        else:
            parsed = parse_decimal(value)
            if parsed is not None:
                numeric_values.append(parsed)
        date_result = parse_date(value)
        if date_result.ambiguous:
            ambiguous_dates += 1
            if concept == "transaction_date":
                _add_issue(
                    analysis,
                    "invalid_date_value",
                    "warning",
                    "Date is ambiguous and was not accepted.",
                    column=name,
                    row=row_number,
                    observed=value,
                )
        elif date_result.value is not None:
            parsed_dates.append(date_result.value)
            if date_result.format_name:
                date_formats.append(date_result.format_name)
        elif concept == "transaction_date":
            _add_issue(
                analysis,
                "invalid_date_value",
                "error",
                "Value cannot be parsed as a supported date.",
                column=name,
                row=row_number,
                observed=value,
            )
    if (
        concept is None
        and numeric_values
        and len(numeric_values) < len(non_null)
        and len(numeric_values) / len(non_null) >= 0.8
    ):
        for row_number, value in enumerate(values, start=2):
            if value and parse_decimal(value) is None:
                _add_issue(
                    analysis,
                    "invalid_numeric_value",
                    "error",
                    "Value is inconsistent with the numeric values in this column.",
                    column=name,
                    row=row_number,
                    observed=value,
                )
    inferred = "text"
    if concept == "identifier":
        inferred = "identifier"
    elif non_null and len(numeric_values) == len(non_null):
        inferred = (
            "currency"
            if concept in {"amount", "debit", "credit", "balance"}
            else (
                "integer"
                if all(value == value.to_integral() for value in numeric_values)
                else "decimal"
            )
        )
    elif non_null and len(parsed_dates) + ambiguous_dates == len(non_null):
        inferred = (
            "date"
            if all(value.time().isoformat() == "00:00:00" for value in parsed_dates)
            else "datetime"
        )
    elif non_null and all(
        value.lower() in {"true", "false", "yes", "no", "0", "1"} for value in non_null
    ):
        inferred = "boolean"
    if concept == "transaction_date" and parsed_dates:
        inferred = "date"
    if len(set(date_formats)) > 1:
        _add_issue(
            analysis,
            "inconsistent_date_formats",
            "warning",
            "Column contains multiple date formats.",
            column=name,
            observed=", ".join(sorted(set(date_formats))),
        )
    null_count = len(values) - len(non_null)
    if not non_null:
        _add_issue(
            analysis, "all_null_column", "warning", "Column contains only null values.", column=name
        )
    elif len(set(non_null)) == 1 and len(non_null) > 1:
        _add_issue(
            analysis,
            "constant_value_column",
            "info",
            "Column contains one constant value.",
            column=name,
            observed=non_null[0],
        )
    null_percentage = (null_count / len(values) * 100) if values else 0
    if null_percentage >= settings.NULL_PERCENTAGE_WARNING_THRESHOLD and non_null:
        _add_issue(
            analysis,
            "high_null_percentage",
            "warning",
            "Column null percentage exceeds the configured threshold.",
            column=name,
            observed=f"{null_percentage:.2f}%",
            expected=f"<{settings.NULL_PERCENTAGE_WARNING_THRESHOLD:.2f}%",
        )
    if concept == "identifier":
        for row_number, value in enumerate(values, start=2):
            if not value:
                _add_issue(
                    analysis,
                    "missing_transaction_identifier",
                    "error",
                    "Transaction identifier is missing.",
                    column=name,
                    row=row_number,
                )
        duplicates = {value for value, count in Counter(non_null).items() if count > 1}
        for row_number, value in enumerate(values, start=2):
            if value in duplicates:
                _add_issue(
                    analysis,
                    "duplicate_transaction_identifier",
                    "error",
                    "Transaction identifier is duplicated.",
                    column=name,
                    row=row_number,
                    observed=value,
                )
    column = ColumnData(
        name=name,
        position=position,
        inferred_type=inferred,
        row_count=len(values),
        null_count=null_count,
        unique_count=len(set(non_null)),
        samples=unique_values[: settings.MAX_SAMPLED_VALUES_PER_COLUMN],
    )
    if inferred in {"integer", "decimal", "currency"} and numeric_values:
        column.minimum = str(min(numeric_values))
        column.maximum = str(max(numeric_values))
        column.mean = sum(numeric_values, Decimal()) / Decimal(len(numeric_values))
        column.median = Decimal(str(statistics.median(numeric_values)))
        column.standard_deviation = (
            Decimal(str(statistics.pstdev(numeric_values)))
            if len(numeric_values) > 1
            else Decimal("0")
        )
        column.formats = [
            "currency"
            if any(
                any(symbol in value.upper() for symbol in ("$", "PHP", "₱")) for value in non_null
            )
            else "numeric"
        ]
    elif inferred in {"date", "datetime"} and parsed_dates:
        column.earliest_date = min(parsed_dates).date()
        column.latest_date = max(parsed_dates).date()
        column.minimum = column.earliest_date.isoformat()
        column.maximum = column.latest_date.isoformat()
        column.formats = sorted(set(date_formats))
    elif inferred in {"text", "identifier", "unknown"} and non_null:
        lengths = [len(value) for value in non_null]
        column.minimum = min(non_null)
        column.maximum = max(non_null)
        column.minimum_length = min(lengths)
        column.maximum_length = max(lengths)
        column.average_length = Decimal(sum(lengths)) / len(lengths)
    return column


def calculate_columns(analysis: Analysis, settings: Settings) -> None:
    for position, name in enumerate(analysis.headers):
        values = [row[position] for row in analysis.rows]
        analysis.columns.append(_infer_column(name, position, values, analysis, settings))


def _money_values(analysis: Analysis, concept: str) -> list[Decimal]:
    header = analysis.concepts.get(concept)
    if header is None:
        return []
    position = analysis.headers.index(header)
    return [
        parsed
        for row in analysis.rows
        if (parsed := parse_decimal(row[position], currency=True)) is not None
    ]


def calculate_financial_controls(analysis: Analysis, tolerance: Decimal) -> None:
    amounts = _money_values(analysis, "amount")
    debits = _money_values(analysis, "debit")
    credits = _money_values(analysis, "credit")
    balances = _money_values(analysis, "balance")
    analysis.monetary_total = sum(amounts, Decimal()) if amounts else None
    analysis.debit_total = sum(debits, Decimal()) if debits else None
    analysis.credit_total = sum(credits, Decimal()) if credits else None
    balance_header = analysis.concepts.get("balance")
    if not balances or balance_header is None:
        return
    balance_position = analysis.headers.index(balance_header)
    balance_rows = [parse_decimal(row[balance_position], currency=True) for row in analysis.rows]
    movements: list[Decimal] = []
    amount_header = analysis.concepts.get("amount")
    if amount_header is not None:
        amount_position = analysis.headers.index(amount_header)
        amount_rows = [parse_decimal(row[amount_position], currency=True) for row in analysis.rows]
        if all(value is not None for value in amount_rows):
            movements = [value for value in amount_rows if value is not None]
    elif "debit" in analysis.concepts or "credit" in analysis.concepts:
        debit_position = (
            analysis.headers.index(analysis.concepts["debit"])
            if "debit" in analysis.concepts
            else None
        )
        credit_position = (
            analysis.headers.index(analysis.concepts["credit"])
            if "credit" in analysis.concepts
            else None
        )
        for row in analysis.rows:
            debit_raw = row[debit_position] if debit_position is not None else ""
            credit_raw = row[credit_position] if credit_position is not None else ""
            debit = parse_decimal(debit_raw, currency=True) if debit_raw else Decimal()
            credit = parse_decimal(credit_raw, currency=True) if credit_raw else Decimal()
            if debit is None or credit is None:
                movements = []
                break
            movements.append(credit - debit)
    analysis.closing_balance = balances[-1]
    if (
        not movements
        or len(movements) != len(analysis.rows)
        or any(value is None for value in balance_rows)
    ):
        _add_issue(
            analysis,
            "running_balance_not_verifiable",
            "warning",
            "Running balance cannot be reliably validated from available columns.",
        )
        return
    reported_balances = [value for value in balance_rows if value is not None]
    analysis.opening_balance = reported_balances[0] - movements[0]
    analysis.calculated_closing_balance = analysis.opening_balance + sum(movements, Decimal())
    analysis.running_balance_valid = (
        abs(analysis.calculated_closing_balance - reported_balances[-1]) <= tolerance
    )
    expected = analysis.opening_balance
    for row_number, (movement, reported) in enumerate(
        zip(movements, reported_balances, strict=True), start=2
    ):
        expected += movement
        if abs(expected - reported) > tolerance:
            analysis.running_balance_valid = False
            _add_issue(
                analysis,
                "invalid_running_balance",
                "error",
                "Reported running balance does not match calculated balance.",
                column=analysis.concepts["balance"],
                row=row_number,
                observed=str(reported),
                expected=str(expected),
            )
        if reported < 0:
            _add_issue(
                analysis,
                "unexpected_negative_balance",
                "warning",
                "Running balance is negative.",
                column=analysis.concepts["balance"],
                row=row_number,
                observed=str(reported),
            )


class ProfilingOrchestrationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def profile(self, session: Session, source_file_id: int, tenant_id: int) -> SourceFileProfile:
        source_file = session.scalar(
            select(SourceFile).where(
                SourceFile.id == source_file_id, SourceFile.tenant_id == tenant_id
            )
        )
        if source_file is None:
            raise ProfilingError("Source file not found")
        run = self._start_run(session, source_file_id, tenant_id)
        try:
            path = self.settings.REGISTERED_RAW_DIRECTORY / source_file.stored_filename
            if not path.is_file():
                raise ProfilingError("Registered source file is missing")
            raw = Path(path).read_bytes()
            self._complete_step(session, run, 1, {"file_size_bytes": len(raw)})
            analysis = inspect_csv(raw, self.settings)
            self._complete_step(
                session, run, 2, {"encoding": analysis.encoding, "delimiter": analysis.delimiter}
            )
            self._complete_step(session, run, 3, {"columns": analysis.headers})
            self._complete_step(
                session,
                run,
                4,
                {"row_count": len(analysis.rows), "duplicate_row_count": analysis.duplicate_rows},
            )
            calculate_columns(analysis, self.settings)
            self._complete_step(session, run, 5, {"column_count": len(analysis.columns)})
            self._complete_step(session, run, 6, {"issue_count": len(analysis.issues)})
            calculate_financial_controls(
                analysis, Decimal(str(self.settings.RUNNING_BALANCE_TOLERANCE))
            )
            self._complete_step(
                session, run, 7, {"running_balance_valid": analysis.running_balance_valid}
            )
            profile = self._persist(session, source_file, run, analysis)
            self._complete_step(session, run, 8, {"profile_id": profile.id})
            run.status = profile.status
            run.completed_at = datetime.now(UTC)
            run.records_extracted = len(analysis.rows)
            self._complete_step(session, run, 9, {"status": profile.status})
            session.commit()
            session.refresh(profile)
            return profile
        except Exception as error:
            session.rollback()
            failed_run = session.get(PipelineRun, run.id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.completed_at = datetime.now(UTC)
                failed_run.error_message = str(error)
                active = next((step for step in failed_run.steps if step.status == "running"), None)
                if active is not None:
                    active.status = "failed"
                    active.completed_at = datetime.now(UTC)
                    active.error_message = str(error)
                session.commit()
            raise ProfilingError(str(error)) from error

    @staticmethod
    def _start_run(session: Session, source_file_id: int, tenant_id: int) -> PipelineRun:
        now = datetime.now(UTC)
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "csv_profile", PipelineDefinition.is_active.is_(True)
            )
        )
        if definition is None:
            raise ProfilingError("CSV profile pipeline definition is not active")
        run = PipelineRun(
            tenant_id=tenant_id,
            pipeline_definition_id=definition.id,
            run_type="csv_profile",
            status="running",
            started_at=now,
            source_file_id=source_file_id,
        )
        run.steps = [
            PipelineRunStep(
                step_name=name,
                step_order=index,
                status="running" if index == 1 else "pending",
                started_at=now,
                metadata_json={},
            )
            for index, name in enumerate(PROFILE_STEPS, start=1)
        ]
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def _complete_step(
        session: Session, run: PipelineRun, order: int, metadata: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC)
        step = run.steps[order - 1]
        step.status = "completed"
        step.completed_at = now
        step.metadata_json = metadata
        if order < len(run.steps):
            run.steps[order].status = "running"
            run.steps[order].started_at = now
        session.flush()

    def _persist(
        self, session: Session, source_file: SourceFile, run: PipelineRun, analysis: Analysis
    ) -> SourceFileProfile:
        profile = session.scalar(
            select(SourceFileProfile).where(
                SourceFileProfile.source_file_id == source_file.id,
                SourceFileProfile.profile_version == self.settings.PROFILING_VERSION,
            )
        )
        if profile is None:
            profile = SourceFileProfile(
                tenant_id=source_file.tenant_id,
                source_file_id=source_file.id,
                pipeline_run_id=run.id,
                profile_version=self.settings.PROFILING_VERSION,
                status="pending",
                file_size_bytes=source_file.file_size_bytes,
                generated_at=datetime.now(UTC),
            )
            session.add(profile)
            session.flush()
        else:
            session.execute(
                delete(DataQualityIssue).where(
                    DataQualityIssue.source_file_profile_id == profile.id
                )
            )
            session.execute(
                delete(SourceFileColumnProfile).where(
                    SourceFileColumnProfile.source_file_profile_id == profile.id
                )
            )
            session.flush()
        issue_severities = {issue.severity for issue in analysis.issues}
        profile.pipeline_run_id = run.id
        profile.status = (
            "blocked"
            if "critical" in issue_severities
            else ("completed_with_warnings" if issue_severities else "completed")
        )
        profile.encoding = analysis.encoding
        profile.delimiter = analysis.delimiter
        profile.row_count = len(analysis.rows)
        profile.column_count = len(analysis.headers)
        profile.empty_row_count = analysis.empty_rows
        profile.duplicate_row_count = analysis.duplicate_rows
        profile.total_null_count = sum(column.null_count for column in analysis.columns)
        profile.total_non_null_count = sum(
            column.row_count - column.null_count for column in analysis.columns
        )
        profile.total_numeric_columns = sum(
            column.inferred_type in {"integer", "decimal", "currency"}
            for column in analysis.columns
        )
        profile.total_date_columns = sum(
            column.inferred_type in {"date", "datetime"} for column in analysis.columns
        )
        profile.total_text_columns = sum(
            column.inferred_type in {"text", "identifier", "unknown"} for column in analysis.columns
        )
        profile.total_boolean_columns = sum(
            column.inferred_type == "boolean" for column in analysis.columns
        )
        earliest_dates = [
            column.earliest_date for column in analysis.columns if column.earliest_date is not None
        ]
        latest_dates = [
            column.latest_date for column in analysis.columns if column.latest_date is not None
        ]
        profile.date_range_start = min(earliest_dates, default=None)
        profile.date_range_end = max(latest_dates, default=None)
        profile.monetary_total = analysis.monetary_total
        profile.debit_total = analysis.debit_total
        profile.credit_total = analysis.credit_total
        profile.opening_balance = analysis.opening_balance
        profile.closing_balance = analysis.closing_balance
        profile.calculated_closing_balance = analysis.calculated_closing_balance
        profile.running_balance_valid = analysis.running_balance_valid
        profile.generated_at = datetime.now(UTC)
        profile.profile_metadata_json = {
            "column_names": analysis.headers,
            "identified_columns": analysis.concepts,
            "running_balance_tolerance": self.settings.RUNNING_BALANCE_TOLERANCE,
        }
        for column in analysis.columns:
            session.add(
                SourceFileColumnProfile(
                    source_file_profile_id=profile.id,
                    column_name=column.name,
                    column_position=column.position,
                    inferred_data_type=column.inferred_type,
                    original_data_type="string",
                    row_count=column.row_count,
                    null_count=column.null_count,
                    non_null_count=column.row_count - column.null_count,
                    null_percentage=Decimal(
                        str((column.null_count / column.row_count * 100) if column.row_count else 0)
                    ),
                    unique_count=column.unique_count,
                    duplicate_value_count=max(
                        0, column.row_count - column.null_count - column.unique_count
                    ),
                    minimum_value=column.minimum,
                    maximum_value=column.maximum,
                    mean_value=column.mean,
                    median_value=column.median,
                    standard_deviation=column.standard_deviation,
                    minimum_length=column.minimum_length,
                    maximum_length=column.maximum_length,
                    average_length=column.average_length,
                    earliest_date=column.earliest_date,
                    latest_date=column.latest_date,
                    sample_values_json=column.samples,
                    detected_formats_json=column.formats,
                )
            )
        session.flush()
        for issue in analysis.issues:
            session.add(
                DataQualityIssue(
                    tenant_id=source_file.tenant_id,
                    source_file_id=source_file.id,
                    source_file_profile_id=profile.id,
                    pipeline_run_id=run.id,
                    column_name=issue.column,
                    row_number=issue.row,
                    issue_code=issue.code,
                    issue_type=issue.issue_type,
                    severity=issue.severity,
                    message=issue.message,
                    observed_value=issue.observed,
                    expected_value=issue.expected,
                    status="open",
                    issue_fingerprint=issue_fingerprint(
                        source_file.id, self.settings.PROFILING_VERSION, issue
                    ),
                    metadata_json=issue.metadata,
                    detected_at=datetime.now(UTC),
                )
            )
        session.flush()
        return profile
