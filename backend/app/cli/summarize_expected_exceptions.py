import argparse

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ExpectedException


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize expected exceptions for a messy run")
    parser.add_argument("--messy-dataset-run-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        rows = session.execute(
            select(
                ExpectedException.expected_exception_code,
                ExpectedException.expected_severity,
                func.count(),
            )
            .where(ExpectedException.messy_dataset_run_id == args.messy_dataset_run_id)
            .group_by(
                ExpectedException.expected_exception_code, ExpectedException.expected_severity
            )
            .order_by(ExpectedException.expected_exception_code)
        ).all()
        if not rows:
            raise SystemExit("No expected exceptions found")
        for code, severity, count in rows:
            print(f"code={code} severity={severity} expected={count}")


if __name__ == "__main__":
    main()
