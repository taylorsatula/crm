"""Workspace-owned operational defaults for the CRM."""

from datetime import datetime, time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WorkingDay = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ServiceReminderMode = Literal["ask_each_time", "six_months", "one_year", "off"]


class WorkspaceSettingsUpdate(BaseModel):
    """Partial update accepted from the workspace settings interface."""

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = None
    workday_start: time | None = None
    workday_end: time | None = None
    working_days: list[WorkingDay] | None = None
    default_appointment_minutes: Literal[60, 120, 180, 240] | None = None
    travel_buffer_minutes: Literal[0, 30, 45, 60] | None = None
    appointment_confirmation_enabled: bool | None = None
    appointment_reminder_minutes: Literal[120, 1440, 2880] | None = None
    service_reminder_mode: ServiceReminderMode | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value

    @field_validator("working_days")
    @classmethod
    def validate_working_days(
        cls, value: list[WorkingDay] | None
    ) -> list[WorkingDay] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("working_days must contain at least one day")
        if len(value) != len(set(value)):
            raise ValueError("working_days cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def require_update(self) -> "WorkspaceSettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one workspace setting is required")
        return self


class WorkspaceSettings(BaseModel):
    """Complete workspace settings record returned to MIRA."""

    workspace_id: UUID
    timezone: str
    workday_start: time
    workday_end: time
    working_days: list[WorkingDay]
    default_appointment_minutes: Literal[60, 120, 180, 240]
    travel_buffer_minutes: Literal[0, 30, 45, 60]
    appointment_confirmation_enabled: bool
    appointment_reminder_minutes: Literal[120, 1440, 2880] | None
    service_reminder_mode: ServiceReminderMode
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_workday(self) -> "WorkspaceSettings":
        if self.workday_start >= self.workday_end:
            raise ValueError("workday_start must be before workday_end")
        if not self.working_days:
            raise ValueError("working_days must contain at least one day")
        if len(self.working_days) != len(set(self.working_days)):
            raise ValueError("working_days cannot contain duplicates")
        return self
