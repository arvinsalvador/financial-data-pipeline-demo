from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import DefectScenario, DefectScenarioRule, Tenant


def main() -> None:
    with SessionLocal() as session:
        tenant = session.scalar(
            select(Tenant).where(Tenant.code == get_settings().DEFAULT_DEMO_TENANT_CODE)
        )
        if tenant is None:
            raise SystemExit("Default tenant not found")
        rows = session.execute(
            select(DefectScenario, func.count(DefectScenarioRule.id))
            .outerjoin(DefectScenarioRule)
            .where(DefectScenario.tenant_id == tenant.id)
            .group_by(DefectScenario.id)
            .order_by(DefectScenario.code)
        ).all()
        for scenario, count in rows:
            print(
                f"id={scenario.id} code={scenario.code} version={scenario.version} "
                f"active={str(scenario.is_active).lower()} rules={count} "
                f"description={scenario.description}"
            )


if __name__ == "__main__":
    main()
