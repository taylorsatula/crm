"""Vault-authenticated CRM workspace lifecycle API."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from api.base import success_response
from utils.timezone import now_utc
from utils.workspace_context import workspace_context


class WorkspaceProvisionRequest(BaseModel):
    """Create one external CRM workspace for MIRA."""

    workspace_id: UUID = Field(description="MIRA-owned CRM workspace identifier")
    timezone: str = Field(description="IANA timezone used for CRM date boundaries")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value


class WorkspaceTimezoneRequest(BaseModel):
    """Change the timezone stored on a CRM workspace."""

    timezone: str = Field(description="IANA timezone used for CRM date boundaries")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value


class WorkspaceTokenRequest(BaseModel):
    """Mint one scoped workspace access token."""

    name: str = Field(min_length=1, max_length=100, description="Operator-visible token label")
    scopes: list[Literal["read", "write"]] = Field(
        min_length=1,
        description="Exact normal-request permissions granted to this token",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="UTC expiry; null means no automatic expiry",
    )

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone offset")
        value = value.astimezone(UTC)
        if value <= now_utc():
            raise ValueError("expires_at must be in the future")
        return value


def create_workspace_router(postgres) -> APIRouter:
    """Create the lifecycle-only workspace and token routes."""
    router = APIRouter(tags=["workspace-lifecycle"])

    @router.post("/lifecycle/workspaces")
    async def provision_workspace(body: WorkspaceProvisionRequest, request: Request):
        with workspace_context(body.workspace_id, body.timezone):
            postgres.execute(
                """
                INSERT INTO workspaces (id, timezone)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET timezone = EXCLUDED.timezone
                """,
                (body.workspace_id, body.timezone),
            )
            postgres.execute(
                """
                INSERT INTO workspace_settings (workspace_id)
                VALUES (%s)
                ON CONFLICT (workspace_id) DO NOTHING
                """,
                (body.workspace_id,),
            )
        return success_response(
            {"workspace_id": str(body.workspace_id), "timezone": body.timezone},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.post("/lifecycle/workspaces/{workspace_id}/tokens")
    async def mint_workspace_token(
        workspace_id: UUID,
        body: WorkspaceTokenRequest,
        request: Request,
    ):
        with workspace_context(workspace_id):
            workspace = postgres.execute_single(
                "SELECT timezone FROM workspaces WHERE id = %s",
                (workspace_id,),
            )
            if not workspace:
                raise ValueError(f"Workspace {workspace_id} not found")

            raw_token = f"crm_ws_{secrets.token_urlsafe(32)}"
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            row = postgres.execute_returning(
                """
                INSERT INTO workspace_access_tokens (
                    workspace_id, token_hash, name, scopes, expires_at
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, issued_at
                """,
                (workspace_id, token_hash, body.name, body.scopes, body.expires_at),
            )[0]

        return success_response(
            {
                "id": str(row["id"]),
                "workspace_id": str(workspace_id),
                "token": raw_token,
                "name": body.name,
                "scopes": body.scopes,
                "issued_at": row["issued_at"],
                "expires_at": body.expires_at,
            },
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.delete("/lifecycle/workspaces/{workspace_id}/tokens/{token_id}")
    async def revoke_workspace_token(
        workspace_id: UUID,
        token_id: UUID,
        request: Request,
    ):
        with workspace_context(workspace_id):
            rows = postgres.execute_returning(
                """
                UPDATE workspace_access_tokens
                SET revoked_at = NOW()
                WHERE id = %s AND workspace_id = %s AND revoked_at IS NULL
                RETURNING id
                """,
                (token_id, workspace_id),
            )
        if not rows:
            raise ValueError(f"Active workspace token {token_id} not found")
        return success_response(
            {"id": str(token_id), "revoked": True},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.patch("/lifecycle/workspaces/{workspace_id}/timezone")
    async def update_workspace_timezone(
        workspace_id: UUID,
        body: WorkspaceTimezoneRequest,
        request: Request,
    ):
        with workspace_context(workspace_id, body.timezone):
            rows = postgres.execute_returning(
                """
                UPDATE workspaces SET timezone = %s
                WHERE id = %s
                RETURNING id
                """,
                (body.timezone, workspace_id),
            )
        if not rows:
            raise ValueError(f"Workspace {workspace_id} not found")
        return success_response(
            {"workspace_id": str(workspace_id), "timezone": body.timezone},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.delete("/lifecycle/workspaces/{workspace_id}")
    async def delete_workspace(workspace_id: UUID, request: Request):
        with workspace_context(workspace_id):
            postgres.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
        return success_response(
            {"workspace_id": str(workspace_id), "deleted": True},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    return router
