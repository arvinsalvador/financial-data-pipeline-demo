from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Tenant


def main() -> None:
    with SessionLocal() as session:
        for tenant in session.scalars(select(Tenant).order_by(Tenant.code)):
            print(f"{tenant.id}\t{tenant.code}\t{tenant.status}\t{tenant.display_name}")


if __name__ == "__main__":
    main()
