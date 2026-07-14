import hashlib
import json
from dataclasses import dataclass

from app.services.messy.types import MutationResult


@dataclass(frozen=True)
class ExpectedIssue:
    code: str
    issue_type: str
    severity: str
    file_type: str
    filename: str
    row_number: int | None
    record_key: str | None
    column: str | None
    message_pattern: str
    fingerprint: str
    metadata: dict[str, object]


class ExpectedExceptionBuilder:
    def build(
        self, tenant_id: int, input_fingerprint: str, result: MutationResult, ordinal: int
    ) -> ExpectedIssue:
        plan = result.plan
        payload = {
            "tenant_id": tenant_id,
            "input_fingerprint": input_fingerprint,
            "rule_code": plan.rule_code,
            "defect_type": plan.defect_type,
            "file": plan.filename,
            "row": plan.clean_row_number,
            "record_key": plan.record_key,
            "column": plan.column,
            "ordinal": ordinal,
            "metadata": result.metadata,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ExpectedIssue(
            code=plan.expected_codes[0],
            issue_type=plan.defect_type,
            severity=plan.severity,
            file_type=plan.file_type,
            filename=plan.filename,
            row_number=plan.clean_row_number,
            record_key=plan.record_key,
            column=plan.column,
            message_pattern=f"Expected controlled {plan.defect_type.replace('_', ' ')}",
            fingerprint=fingerprint,
            metadata={**result.metadata, "rule_code": plan.rule_code},
        )
