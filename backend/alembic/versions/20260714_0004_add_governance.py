"""Add tenant, authorization, audit, and pipeline governance.

Revision ID: 20260714_0004
Revises: 20260714_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0004"
down_revision: str | None = "20260714_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(255)),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=False),
        sa.Column("data_retention_days", sa.Integer()),
        sa.Column("settings_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_tenants_code", "tenants", ["code"], unique=True)
    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.execute("""INSERT INTO tenants (code,name,display_name,status,default_currency,timezone,fiscal_year_start_month)
        VALUES ('demo_coffee_group','Demo Coffee Group','Demo Coffee Group','active','USD','America/New_York',1)""")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("password_hash", sa.String(500)),
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("is_system_role", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)
    op.create_index("ix_roles_scope", "roles", ["scope"])

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "tenant_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True)),
        sa.Column("joined_at", sa.DateTime(timezone=True)),
        sa.Column("suspended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),
    )
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"])
    op.create_index("ix_tenant_users_user_id", "tenant_users", ["user_id"])
    op.create_index("ix_tenant_users_status", "tenant_users", ["status"])

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    op.create_table(
        "tenant_user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_user_id", sa.Integer(), sa.ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_user_id", "role_id", name="uq_tenant_user_role"),
    )
    op.create_index("ix_tenant_user_roles_tenant_user_id", "tenant_user_roles", ["tenant_user_id"])
    op.create_index("ix_tenant_user_roles_role_id", "tenant_user_roles", ["role_id"])

    op.create_table(
        "pipeline_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("configuration_schema_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", "version", name="uq_pipeline_definition_version"),
    )
    op.create_index("ix_pipeline_definitions_code", "pipeline_definitions", ["code"])
    op.create_index("ix_pipeline_definitions_is_active", "pipeline_definitions", ["is_active"])

    for table in ("source_systems", "source_files", "source_file_profiles", "data_quality_issues", "pipeline_runs"):
        op.add_column(table, sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_foreign_key(f"fk_{table}_tenant_id", table, "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        op.execute(f"UPDATE {table} SET tenant_id=(SELECT id FROM tenants WHERE code='demo_coffee_group')")
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    op.add_column("pipeline_runs", sa.Column("pipeline_definition_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_pipeline_runs_definition", "pipeline_runs", "pipeline_definitions", ["pipeline_definition_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_pipeline_runs_pipeline_definition_id", "pipeline_runs", ["pipeline_definition_id"])

    op.drop_index("ix_source_systems_code", table_name="source_systems")
    op.drop_constraint("source_systems_code_key", "source_systems", type_="unique")
    op.create_index("ix_source_systems_code", "source_systems", ["code"])
    op.create_unique_constraint("uq_source_system_tenant_code", "source_systems", ["tenant_id", "code"])
    op.drop_constraint("source_files_sha256_checksum_key", "source_files", type_="unique")
    op.create_unique_constraint("uq_source_file_tenant_checksum", "source_files", ["tenant_id", "sha256_checksum"])
    op.create_index("ix_source_systems_tenant_status", "source_systems", ["tenant_id", "is_active"])
    op.create_index("ix_source_files_tenant_status", "source_files", ["tenant_id", "status"])
    op.create_index("ix_pipeline_runs_tenant_status", "pipeline_runs", ["tenant_id", "status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT")),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("correlation_id", sa.String(100)),
        sa.Column("pipeline_run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL")),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id", ondelete="SET NULL")),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for column in ("tenant_id", "actor_user_id", "event_type", "entity_type", "entity_id", "action", "pipeline_run_id", "source_file_id", "occurred_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])
    op.create_index("ix_audit_events_tenant_occurred", "audit_events", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    op.create_table(
        "audit_event_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_event_id", sa.Integer(), sa.ForeignKey("audit_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("old_value_json", postgresql.JSONB()),
        sa.Column("new_value_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_event_changes_audit_event_id", "audit_event_changes", ["audit_event_id"])

    op.create_table(
        "pipeline_run_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64)),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("file_size_bytes", sa.BigInteger()),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for column in ("tenant_id", "pipeline_run_id", "artifact_type"):
        op.create_index(f"ix_pipeline_run_artifacts_{column}", "pipeline_run_artifacts", [column])
    op.create_index("ix_pipeline_artifact_run_type", "pipeline_run_artifacts", ["pipeline_run_id", "artifact_type"])

    _seed_governance()
    op.execute("""UPDATE pipeline_runs SET pipeline_definition_id=(SELECT id FROM pipeline_definitions WHERE code=CASE WHEN pipeline_runs.run_type='csv_profile' THEN 'csv_profile' ELSE 'source_file_registration' END AND version='1.0.0')""")


def _seed_governance() -> None:
    roles = (("platform_admin", "Platform Administrator", "platform"), ("cfo_user", "CFO User", "tenant"), ("finance_analyst", "Finance Analyst", "tenant"), ("client_viewer", "Client Viewer", "tenant"))
    for code, name, scope in roles:
        op.execute(sa.text("INSERT INTO roles (code,name,scope,is_system_role) VALUES (:c,:n,:s,true)").bindparams(c=code, n=name, s=scope))
    permissions = ("tenants.view", "tenants.manage", "users.view", "users.manage", "roles.view", "roles.manage", "source_systems.view", "source_systems.manage", "source_files.view", "source_files.upload", "source_files.profile", "profiles.view", "data_quality_issues.view", "data_quality_issues.manage", "pipeline_runs.view", "pipeline_runs.execute", "pipeline_runs.retry", "audit_events.view", "dashboards.view")
    for code in permissions:
        op.execute(sa.text("INSERT INTO permissions (code,name) VALUES (:c,:n)").bindparams(c=code, n=code.replace(".", " ").title()))
    role_map = {
        "platform_admin": permissions,
        "cfo_user": ("users.view", "roles.view", "source_systems.view", "source_files.view", "source_files.upload", "source_files.profile", "profiles.view", "data_quality_issues.view", "data_quality_issues.manage", "pipeline_runs.view", "pipeline_runs.execute", "pipeline_runs.retry", "audit_events.view", "dashboards.view"),
        "finance_analyst": ("source_systems.view", "source_files.view", "source_files.upload", "source_files.profile", "profiles.view", "data_quality_issues.view", "pipeline_runs.view", "pipeline_runs.execute", "dashboards.view"),
        "client_viewer": ("source_systems.view", "source_files.view", "profiles.view", "data_quality_issues.view", "pipeline_runs.view", "dashboards.view"),
    }
    for role, codes in role_map.items():
        for code in codes:
            op.execute(sa.text("INSERT INTO role_permissions (role_id,permission_id) SELECT r.id,p.id FROM roles r, permissions p WHERE r.code=:r AND p.code=:p").bindparams(r=role, p=code))
    users = (("admin@demo.local", "Demo Platform Administrator", True), ("cfo@demo.local", "Demo CFO User", False), ("analyst@demo.local", "Demo Finance Analyst", False), ("viewer@demo.local", "Demo Client Viewer", False))
    for email, name, admin in users:
        op.execute(sa.text("INSERT INTO users (email,display_name,status,is_platform_admin) VALUES (:e,:n,'inactive',:a)").bindparams(e=email, n=name, a=admin))
    for email, role in (("cfo@demo.local", "cfo_user"), ("analyst@demo.local", "finance_analyst"), ("viewer@demo.local", "client_viewer")):
        op.execute(sa.text("INSERT INTO tenant_users (tenant_id,user_id,status,joined_at) SELECT t.id,u.id,'active',now() FROM tenants t, users u WHERE t.code='demo_coffee_group' AND u.email=:e").bindparams(e=email))
        op.execute(sa.text("INSERT INTO tenant_user_roles (tenant_user_id,role_id,assigned_at) SELECT tu.id,r.id,now() FROM tenant_users tu JOIN users u ON u.id=tu.user_id, roles r WHERE u.email=:e AND r.code=:r").bindparams(e=email, r=role))
    op.execute("INSERT INTO pipeline_definitions (code,name,version,is_active,configuration_schema_json) VALUES ('source_file_registration','Source File Registration','1.0.0',true,'{}'),('csv_profile','CSV Profile','1.0.0',true,'{}')")


def downgrade() -> None:
    op.drop_table("pipeline_run_artifacts")
    op.drop_table("audit_event_changes")
    op.drop_table("audit_events")
    op.drop_index("ix_pipeline_runs_pipeline_definition_id", table_name="pipeline_runs")
    op.drop_constraint("fk_pipeline_runs_definition", "pipeline_runs", type_="foreignkey")
    op.drop_column("pipeline_runs", "pipeline_definition_id")
    op.drop_constraint("uq_source_file_tenant_checksum", "source_files", type_="unique")
    op.create_unique_constraint("source_files_sha256_checksum_key", "source_files", ["sha256_checksum"])
    op.drop_constraint("uq_source_system_tenant_code", "source_systems", type_="unique")
    op.drop_index("ix_source_systems_code", table_name="source_systems")
    op.create_index("ix_source_systems_code", "source_systems", ["code"], unique=True)
    for table in ("pipeline_runs", "data_quality_issues", "source_file_profiles", "source_files", "source_systems"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    op.drop_table("tenant_user_roles")
    op.drop_table("role_permissions")
    op.drop_table("tenant_users")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("pipeline_definitions")
    op.drop_table("tenants")
