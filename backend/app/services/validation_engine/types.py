from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ValidationDocument:
    file_type: str
    filename: str
    source_file_id: int | None
    headers: list[str]
    rows: list[list[str]]

    def dictionaries(self) -> list[dict[str, str]]:
        return [
            {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(self.headers)
            }
            for row in self.rows
        ]


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    issue_type: str
    entity_type: str
    message: str
    filename: str | None = None
    source_file_id: int | None = None
    row_number: int | None = None
    column: str | None = None
    entity_key: str | None = None
    observed: str | None = None
    expected: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationRuleOutcome:
    findings: list[ValidationFinding]
    records_evaluated: int
    status: str = "passed"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationContext:
    session: Session
    tenant_id: int
    target_type: str
    target_id: int | None
    documents: dict[str, ValidationDocument]
    control_statuses: dict[str, str]
    expected_exception_count: int = 0
    applied_mutation_count: int = 0

    @property
    def record_count(self) -> int:
        return sum(len(document.rows) for document in self.documents.values())
