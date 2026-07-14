from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]+$", min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = None
    display_name: str = Field(min_length=1, max_length=255)
    status: Literal["active", "inactive", "suspended", "archived"] = "active"
    default_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    timezone: str = "UTC"
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    data_retention_days: int | None = Field(default=None, gt=0)
    settings_json: dict[str, Any] | None = None


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal["active", "inactive", "suspended", "archived"] | None = None
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = None
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    data_retention_days: int | None = Field(default=None, gt=0)
    settings_json: dict[str, Any] | None = None


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    legal_name: str | None
    display_name: str
    status: str
    default_currency: str
    timezone: str
    fiscal_year_start_month: int
    data_retention_days: int | None
    settings_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=255)
    first_name: str | None = None
    last_name: str | None = None
    status: Literal["invited", "active", "inactive", "suspended", "archived"] = "active"
    is_platform_admin: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    status: Literal["invited", "active", "inactive", "suspended", "archived"] | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    first_name: str | None
    last_name: str | None
    status: str
    is_platform_admin: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class MembershipCreate(BaseModel):
    user_id: int
    status: Literal["invited", "active", "suspended", "removed"] = "active"


class MembershipUpdate(BaseModel):
    status: Literal["invited", "active", "suspended", "removed"]


class RoleAssign(BaseModel):
    role_id: int


class MembershipResponse(BaseModel):
    id: int
    tenant_id: int
    user_id: int
    user_email: str
    user_display_name: str
    status: str
    roles: list[str]
    joined_at: datetime | None
    created_at: datetime


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None
    scope: str
    is_system_role: bool


class AuditChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    field_name: str
    old_value_json: Any | None
    new_value_json: Any | None


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int | None
    actor_user_id: int | None
    actor_type: str
    event_type: str
    entity_type: str
    entity_id: str | None
    action: str
    description: str
    pipeline_run_id: int | None
    source_file_id: int | None
    metadata_json: dict[str, Any] | None
    occurred_at: datetime
    changes: list[AuditChangeResponse] = []


class PipelineDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None
    version: str
    is_active: bool
    configuration_schema_json: dict[str, Any] | None


class PipelineArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    pipeline_run_id: int
    artifact_type: str
    name: str
    relative_path: str
    checksum: str | None
    mime_type: str | None
    file_size_bytes: int | None
    metadata_json: dict[str, Any] | None
    created_at: datetime


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
