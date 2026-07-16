from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.demo_environment import DemoEnvironmentError, bootstrap_demo


def main() -> None:
    settings = get_settings()
    try:
        with SessionLocal() as session:
            counts = bootstrap_demo(session, settings)
    except DemoEnvironmentError as error:
        raise SystemExit(str(error)) from error
    print(f"environment={settings.ENVIRONMENT} bootstrap=completed counts={counts}")


if __name__ == "__main__":
    main()
