import argparse

from sqlalchemy import exists, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import SourceFile, SourceFileProfile
from app.services.csv_profiling import ProfilingOrchestrationService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile registered CSV source files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-file-id", type=int)
    group.add_argument("--all-unprofiled", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    service = ProfilingOrchestrationService(settings)
    with SessionLocal() as session:
        if args.source_file_id is not None:
            source_ids = [args.source_file_id]
        else:
            profiled = exists().where(
                SourceFileProfile.source_file_id == SourceFile.id,
                SourceFileProfile.profile_version == settings.PROFILING_VERSION,
            )
            source_ids = list(session.scalars(select(SourceFile.id).where(~profiled)))
        for source_id in source_ids:
            profile = service.profile(session, source_id)
            print(f"source_file_id={source_id} profile_id={profile.id} status={profile.status}")


if __name__ == "__main__":
    main()
