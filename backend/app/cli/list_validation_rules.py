from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Tenant, ValidationRule, ValidationRuleSet


def main() -> None:
    with SessionLocal() as session:
        tenant = session.scalar(
            select(Tenant).where(Tenant.code == get_settings().DEFAULT_DEMO_TENANT_CODE)
        )
        if tenant is None:
            raise SystemExit("Default tenant not found")
        rules = session.execute(
            select(ValidationRule, ValidationRuleSet.code)
            .join(ValidationRuleSet)
            .where(ValidationRuleSet.tenant_id == tenant.id)
            .order_by(ValidationRule.execution_order)
        ).all()
        for rule, rule_set in rules:
            print(
                f"order={rule.execution_order} rule_set={rule_set} code={rule.code} "
                f"group={rule.rule_group} target={rule.target_entity} severity={rule.severity} "
                f"version={rule.version} enabled={str(rule.is_enabled).lower()}"
            )


if __name__ == "__main__":
    main()
