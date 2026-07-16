import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.demo_environment import (
    DemoEnvironmentError,
    cleanup_files,
    database_counts,
    remove_files,
    require_development,
    reset_database_records,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely reset local demonstration data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-records", action="store_true")
    parser.add_argument("--uploaded-files", action="store_true")
    parser.add_argument("--generated-clean", action="store_true")
    parser.add_argument("--generated-messy", action="store_true")
    parser.add_argument("--reports", action="store_true")
    parser.add_argument("--manifests", action="store_true")
    parser.add_argument("--all-demo-data", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    try:
        require_development(settings)
        modes = {
            name
            for name in (
                "uploaded_files",
                "generated_clean",
                "generated_messy",
                "reports",
                "manifests",
            )
            if getattr(args, name) or args.all_demo_data
        }
        database = args.database_records or args.all_demo_data
        files = cleanup_files(settings, modes)
        with SessionLocal() as session:
            counts = database_counts(session) if database else {}
            print(
                f"environment={settings.ENVIRONMENT} dry_run={args.dry_run} "
                f"confirmed={args.confirm}"
            )
            print(f"database_records={sum(counts.values())} tables={len(counts)}")
            for table, count in counts.items():
                if count:
                    print(f"database table={table} records={count}")
            print(f"files={len(files)}")
            for item in files:
                print(f"file mode={item.mode} path={item.path}")
            if not database and not files:
                print("No reset modes selected; no changes made.")
                return
            if args.dry_run:
                print("Dry run complete; no changes made.")
                return
            if not args.confirm:
                raise DemoEnvironmentError("Refusing destructive reset without --confirm")
            if database:
                reset_database_records(session)
            remove_files(files)
            print("Reset completed.")
    except DemoEnvironmentError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
