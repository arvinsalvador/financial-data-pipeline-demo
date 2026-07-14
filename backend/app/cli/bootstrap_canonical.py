from app.db.session import SessionLocal
from app.services.canonical_seed import seed_canonical_data


def main() -> None:
    with SessionLocal() as session:
        print("Canonical bootstrap applied idempotently:", seed_canonical_data(session))


if __name__ == "__main__":
    main()
