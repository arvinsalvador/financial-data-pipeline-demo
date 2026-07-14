import csv
import io
from dataclasses import dataclass, field
from typing import Any

PRIMARY_KEYS = {
    "customers": "customer_id",
    "crm_deals": "deal_id",
    "invoices": "invoice_id",
    "invoice_lines": "invoice_line_id",
    "customer_payments": "payment_id",
    "customer_payment_applications": "payment_application_id",
    "vendors": "vendor_id",
    "accounts_payable": "ap_bill_id",
    "general_ledger": "journal_line_id",
    "forecast_assumptions": "assumption_id",
}


@dataclass
class CsvRow:
    values: list[str]
    clean_row_number: int | None


@dataclass
class CsvDocument:
    file_type: str
    headers: list[str]
    rows: list[CsvRow]

    @classmethod
    def parse(cls, file_type: str, content: bytes) -> "CsvDocument":
        parsed = list(csv.reader(io.StringIO(content.decode("utf-8"), newline="")))
        return cls(
            file_type, parsed[0], [CsvRow(row, index) for index, row in enumerate(parsed[1:], 2)]
        )

    def column_index(self, name: str | None) -> int | None:
        if name is None:
            return None
        try:
            return self.headers.index(name)
        except ValueError:
            return None

    def value(self, row: CsvRow, column: str | None) -> str | None:
        index = self.column_index(column)
        return row.values[index] if index is not None and index < len(row.values) else None

    def set_value(self, row: CsvRow, column: str, value: str) -> None:
        index = self.column_index(column)
        if index is None:
            raise ValueError(f"Column not found: {column}")
        while len(row.values) <= index:
            row.values.append("")
        row.values[index] = value

    def record_key(self, row: CsvRow) -> str | None:
        return self.value(row, PRIMARY_KEYS.get(self.file_type))

    def serialize(self) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(self.headers)
        writer.writerows(row.values for row in self.rows)
        return stream.getvalue().encode("utf-8")


@dataclass(frozen=True)
class PlannedMutation:
    rule_id: int
    rule_code: str
    rule_order: int
    defect_type: str
    file_type: str
    filename: str
    clean_row_number: int | None
    record_key: str | None
    column: str | None
    original_value: str | None
    proposed_value: str | None
    severity: str
    expected_codes: tuple[str, ...]
    status: str = "planned"
    reason: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MutationResult:
    plan: PlannedMutation
    original_value: str | None
    mutated_value: str | None
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
