from sqlalchemy import inspect, text

from app.db.session import engine


def test_database_connectivity() -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1


def test_initial_migration_created_system_checks_table() -> None:
    assert "system_checks" in inspect(engine).get_table_names()


def test_migration_is_at_head() -> None:
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))

    assert revision == "240ac0e252e1"


def test_phase_2a_tables_exist() -> None:
    table_names = set(inspect(engine).get_table_names())

    assert {"source_systems", "source_files", "pipeline_runs", "pipeline_run_steps"} <= table_names


def test_phase_5_canonical_tables_exist() -> None:
    table_names = set(inspect(engine).get_table_names())
    assert {
        "currencies",
        "financial_accounts",
        "financial_transactions",
        "bank_transactions",
        "credit_card_transactions",
        "payroll_runs",
        "payroll_entries",
        "canonical_record_lineage",
        "normalization_exceptions",
    } <= table_names
