import hashlib
import random
from decimal import Decimal

from app.models import DefectScenarioRule
from app.services.messy.types import CsvDocument, CsvRow, PlannedMutation


class MutationPlanner:
    def plan(
        self,
        documents: dict[str, CsvDocument],
        rules: list[DefectScenarioRule],
        seed: int,
        maximum: int,
    ) -> list[PlannedMutation]:
        plans: list[PlannedMutation] = []
        for rule in sorted(rules, key=lambda item: (item.rule_order, item.id)):
            if not rule.is_enabled:
                plans.append(self._skip(rule, "rule_disabled"))
                continue
            document = documents.get(rule.target_file_type)
            if document is None:
                plans.append(self._skip(rule, "target_file_missing"))
                continue
            if rule.target_column and document.column_index(rule.target_column) is None:
                plans.append(self._skip(rule, "target_column_missing"))
                continue
            eligible = self._eligible(document, rule)
            count = rule.requested_count or self._percentage_count(rule, len(eligible))
            if count <= 0:
                plans.append(self._skip(rule, "requested_count_zero"))
                continue
            rule_seed = int(
                hashlib.sha256(f"{seed}:{rule.rule_code}".encode()).hexdigest()[:16], 16
            )
            selected = random.Random(rule_seed).sample(eligible, min(count, len(eligible)))
            selected.sort(
                key=lambda row: (row.clean_row_number or 0, document.record_key(row) or "")
            )
            for row in selected:
                plans.append(
                    PlannedMutation(
                        rule_id=rule.id,
                        rule_code=rule.rule_code,
                        rule_order=rule.rule_order,
                        defect_type=rule.defect_type,
                        file_type=rule.target_file_type,
                        filename=f"{rule.target_file_type}.csv",
                        clean_row_number=row.clean_row_number,
                        record_key=document.record_key(row),
                        column=rule.target_column,
                        original_value=document.value(row, rule.target_column),
                        proposed_value=self._proposed(
                            rule, document.value(row, rule.target_column)
                        ),
                        severity=rule.severity,
                        expected_codes=(rule.defect_type.upper(),),
                        configuration=rule.configuration_json or {},
                    )
                )
            for _ in range(count - len(selected)):
                plans.append(self._skip(rule, "insufficient_eligible_rows"))
            if len(plans) >= maximum:
                break
        return plans[:maximum]

    def _eligible(self, document: CsvDocument, rule: DefectScenarioRule) -> list[CsvRow]:
        config = rule.configuration_json or {}
        rows = list(document.rows)
        if source_type := config.get("filter_source_type"):
            rows = [row for row in rows if document.value(row, "source_type") == source_type]
        if account := config.get("filter_account_code"):
            rows = [row for row in rows if document.value(row, "account_code") == account]
        return rows

    @staticmethod
    def _percentage_count(rule: DefectScenarioRule, eligible: int) -> int:
        return int(Decimal(eligible) * (rule.requested_percentage or Decimal(0)) / Decimal(100))

    @staticmethod
    def _proposed(rule: DefectScenarioRule, original: str | None) -> str | None:
        config = rule.configuration_json or {}
        return str(config["value"]) if "value" in config else original

    @staticmethod
    def _skip(rule: DefectScenarioRule, reason: str) -> PlannedMutation:
        return PlannedMutation(
            rule_id=rule.id,
            rule_code=rule.rule_code,
            rule_order=rule.rule_order,
            defect_type=rule.defect_type,
            file_type=rule.target_file_type,
            filename=f"{rule.target_file_type}.csv",
            clean_row_number=None,
            record_key=None,
            column=rule.target_column,
            original_value=None,
            proposed_value=None,
            severity=rule.severity,
            expected_codes=(rule.defect_type.upper(),),
            status="skipped",
            reason=reason,
            configuration=rule.configuration_json or {},
        )


class MutationConflictResolver:
    def resolve(self, plans: list[PlannedMutation], policy: str) -> list[PlannedMutation]:
        occupied: set[tuple[str, int | None, str | None]] = set()
        resolved: list[PlannedMutation] = []
        compatible = {
            "exact_duplicate_row",
            "near_duplicate_row",
            "duplicate_invoice",
            "duplicate_ap_bill",
        }
        for plan in plans:
            target = (plan.file_type, plan.clean_row_number, plan.column)
            if (
                plan.status == "planned"
                and target in occupied
                and plan.defect_type not in compatible
            ):
                if policy == "fail":
                    raise ValueError(f"Mutation conflict: {target}")
                resolved.append(
                    PlannedMutation(
                        **{**plan.__dict__, "status": "skipped", "reason": "target_conflict"}
                    )
                )
                continue
            if plan.status == "planned":
                occupied.add(target)
            resolved.append(plan)
        return resolved
