from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.demo_environment import DemoEnvironmentError, verify_demo


def main() -> None:
    settings = get_settings()
    try:
        with SessionLocal() as session:
            issues = verify_demo(session, settings)
    except DemoEnvironmentError as error:
        raise SystemExit(str(error)) from error
    print(f"environment={settings.ENVIRONMENT} issues={len(issues)}")
    for issue in issues:
        print(issue)
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
