"""Read and update the current CRM workspace's operational defaults."""

from typing import Any

from clients.postgres_client import PostgresClient
from core.models.workspace_settings import WorkspaceSettings, WorkspaceSettingsUpdate
from utils.timezone import now_utc
from utils.workspace_context import get_current_workspace_id


class WorkspaceSettingsService:
    """Own the canonical one-to-one settings record for a CRM workspace."""

    _SETTING_COLUMNS = {
        "workday_start",
        "workday_end",
        "working_days",
        "default_appointment_minutes",
        "travel_buffer_minutes",
        "appointment_confirmation_enabled",
        "appointment_reminder_minutes",
        "service_reminder_mode",
    }

    def __init__(self, postgres: PostgresClient) -> None:
        self.postgres = postgres

    def get(self) -> WorkspaceSettings:
        """Return the required settings row for the active workspace."""
        workspace_id = get_current_workspace_id()
        row = self.postgres.execute_single(
            """
            SELECT settings.*, workspaces.timezone
            FROM workspace_settings AS settings
            JOIN workspaces ON workspaces.id = settings.workspace_id
            WHERE settings.workspace_id = %s
            """,
            (workspace_id,),
        )
        if row is None:
            raise RuntimeError(f"Workspace settings missing for workspace {workspace_id}")
        return WorkspaceSettings.model_validate(row)

    def update(self, data: WorkspaceSettingsUpdate) -> WorkspaceSettings:
        """Validate the complete next state and update workspace/settings atomically."""
        current = self.get()
        updates = data.model_dump(exclude_unset=True)
        merged: dict[str, Any] = current.model_dump()
        merged.update(updates)
        WorkspaceSettings.model_validate(merged)

        timezone = updates.pop("timezone", None)
        setting_fields = [field for field in updates if field in self._SETTING_COLUMNS]
        set_parts = [f"{field} = %s" for field in setting_fields]
        setting_values = [updates[field] for field in setting_fields]
        set_parts.append("updated_at = %s")
        params = [
            timezone,
            current.workspace_id,
            *setting_values,
            now_utc(),
            current.workspace_id,
        ]

        rows = self.postgres.execute_returning(
            f"""
            WITH workspace_update AS (
                UPDATE workspaces
                SET timezone = COALESCE(%s, timezone)
                WHERE id = %s
                RETURNING id
            )
            UPDATE workspace_settings AS settings
            SET {', '.join(set_parts)}
            FROM workspace_update
            WHERE settings.workspace_id = workspace_update.id
              AND settings.workspace_id = %s
            RETURNING settings.workspace_id
            """,
            tuple(params),
        )
        if len(rows) != 1:
            raise RuntimeError(
                f"Failed to update workspace settings for {current.workspace_id}"
            )
        return self.get()
