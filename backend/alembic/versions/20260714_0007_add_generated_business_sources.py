"""Add deterministic generated business source tracking.

Revision ID: 9f4b7143843e
Revises: 34851fb5b835
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9f4b7143843e"
down_revision: str | None = "34851fb5b835"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_dataset_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("generator_version", sa.String(30), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("generation_date", sa.Date(), nullable=False),
        sa.Column("base_date_start", sa.Date()),
        sa.Column("base_date_end", sa.Date()),
        sa.Column("source_bank_transaction_count", sa.Integer(), nullable=False),
        sa.Column("source_credit_card_transaction_count", sa.Integer(), nullable=False),
        sa.Column("source_payroll_run_count", sa.Integer(), nullable=False),
        sa.Column("generated_customer_count", sa.Integer(), nullable=False),
        sa.Column("generated_vendor_count", sa.Integer(), nullable=False),
        sa.Column("generated_deal_count", sa.Integer(), nullable=False),
        sa.Column("generated_invoice_count", sa.Integer(), nullable=False),
        sa.Column("generated_payment_count", sa.Integer(), nullable=False),
        sa.Column("generated_ap_bill_count", sa.Integer(), nullable=False),
        sa.Column("generated_gl_entry_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "tenant_id",
            "input_fingerprint",
            "generator_version",
            "random_seed",
            name="uq_generated_dataset_inputs",
        ),
    )
    op.create_index(
        "ix_generated_dataset_tenant_generation_date",
        "generated_dataset_runs",
        ["tenant_id", "generation_date"],
    )
    op.create_index(
        "ix_generated_dataset_tenant_seed",
        "generated_dataset_runs",
        ["tenant_id", "random_seed"],
    )
    op.create_index(
        "ix_generated_dataset_tenant_version",
        "generated_dataset_runs",
        ["tenant_id", "generator_version"],
    )
    op.create_index("ix_generated_dataset_runs_status", "generated_dataset_runs", ["status"])
    op.create_index(
        "ix_generated_dataset_runs_input_fingerprint",
        "generated_dataset_runs",
        ["input_fingerprint"],
    )

    op.create_table(
        "generated_source_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("generated_dataset_run_id", sa.Integer(), nullable=False),
        sa.Column("source_system_id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False, unique=True),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generated_dataset_run_id"], ["generated_dataset_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"], ["source_systems.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "generated_dataset_run_id", "file_type", name="uq_generated_file_type"
        ),
    )
    for column in (
        "tenant_id",
        "generated_dataset_run_id",
        "source_system_id",
        "source_file_id",
        "file_type",
        "sha256_checksum",
    ):
        op.create_index(f"ix_generated_source_files_{column}", "generated_source_files", [column])

    op.create_table(
        "generated_record_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("generated_dataset_run_id", sa.Integer(), nullable=False),
        sa.Column("generated_file_type", sa.String(100), nullable=False),
        sa.Column("generated_record_key", sa.String(255), nullable=False),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("related_entity_type", sa.String(100), nullable=False),
        sa.Column("related_entity_id", sa.String(255), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generated_dataset_run_id"], ["generated_dataset_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "generated_dataset_run_id",
            "generated_record_key",
            "relationship_type",
            "related_entity_type",
            "related_entity_id",
            name="uq_generated_record_link",
        ),
    )
    for column in (
        "tenant_id",
        "generated_dataset_run_id",
        "generated_file_type",
        "generated_record_key",
        "relationship_type",
        "related_entity_type",
        "related_entity_id",
    ):
        op.create_index(f"ix_generated_record_links_{column}", "generated_record_links", [column])

    op.create_table(
        "generation_control_totals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("generated_dataset_run_id", sa.Integer(), nullable=False),
        sa.Column("control_name", sa.String(120), nullable=False),
        sa.Column("expected_value", sa.Numeric(30, 6), nullable=False),
        sa.Column("actual_value", sa.Numeric(30, 6), nullable=False),
        sa.Column("difference", sa.Numeric(30, 6), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("details_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generated_dataset_run_id"], ["generated_dataset_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "generated_dataset_run_id", "control_name", name="uq_generation_control"
        ),
    )
    for column in ("tenant_id", "generated_dataset_run_id", "control_name", "status"):
        op.create_index(
            f"ix_generation_control_totals_{column}", "generation_control_totals", [column]
        )

    op.create_table(
        "generation_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("generated_dataset_run_id", sa.Integer()),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("exception_code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generated_dataset_run_id"], ["generated_dataset_runs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id", "input_fingerprint", "exception_code", name="uq_generation_exception"
        ),
    )
    for column in (
        "tenant_id",
        "generated_dataset_run_id",
        "input_fingerprint",
        "exception_code",
        "severity",
    ):
        op.create_index(f"ix_generation_exceptions_{column}", "generation_exceptions", [column])


def downgrade() -> None:
    op.drop_table("generation_exceptions")
    op.drop_table("generation_control_totals")
    op.drop_table("generated_record_links")
    op.drop_table("generated_source_files")
    op.drop_table("generated_dataset_runs")
