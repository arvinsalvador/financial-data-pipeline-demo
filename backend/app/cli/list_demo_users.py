from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import User


def main() -> None:
    with SessionLocal() as session:
        for user in session.scalars(
            select(User).where(User.email.endswith("@demo.local")).order_by(User.email)
        ):
            print(
                f"{user.id}\t{user.email}\t{user.status}\tplatform_admin={user.is_platform_admin}"
            )


if __name__ == "__main__":
    main()
