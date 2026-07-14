from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.governance_seed import seed_governance_data


def main() -> None:
    with SessionLocal() as session:
        counts = seed_governance_data(session, get_settings())
        print("Governance seed applied idempotently:", counts)


if __name__ == "__main__":
    main()
