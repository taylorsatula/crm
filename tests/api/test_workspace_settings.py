"""Workspace settings API, validation, and isolation tests."""

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient
from pathlib import Path

from core.models.workspace_settings import WorkspaceSettingsUpdate
from core.services.workspace_settings_service import WorkspaceSettingsService
from tests.conftest import TEST_WORKSPACE_B_TOKEN
from tests.conftest import TEST_WORKSPACE_ID
from utils.workspace_context import workspace_context


def test_workspace_settings_update_model_contract():
    assert WorkspaceSettingsUpdate(
        appointment_reminder_minutes=None,
        working_days=["mon", "wed"],
    ).model_dump(exclude_unset=True) == {
        "appointment_reminder_minutes": None,
        "working_days": ["mon", "wed"],
    }
    with pytest.raises(ValidationError):
        WorkspaceSettingsUpdate()
    with pytest.raises(ValidationError):
        WorkspaceSettingsUpdate(working_days=[])
    with pytest.raises(ValidationError):
        WorkspaceSettingsUpdate(working_days=["mon", "mon"])
    with pytest.raises(ValidationError):
        WorkspaceSettingsUpdate(default_appointment_minutes=90)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorkspaceSettingsUpdate(workday_start="09:00", unknown_field="junk")


def test_workspace_settings_service_updates_timezone_and_record_atomically():
    base = {
        "workspace_id": TEST_WORKSPACE_ID,
        "timezone": "America/Chicago",
        "workday_start": "08:00",
        "workday_end": "17:00",
        "working_days": ["mon", "tue", "wed", "thu", "fri"],
        "default_appointment_minutes": 120,
        "travel_buffer_minutes": 30,
        "appointment_confirmation_enabled": True,
        "appointment_reminder_minutes": 1440,
        "service_reminder_mode": "ask_each_time",
        "created_at": "2026-07-11T12:00:00Z",
        "updated_at": "2026-07-11T12:00:00Z",
    }

    class FakePostgres:
        def __init__(self):
            self.rows = [{**base, "timezone": "America/Chicago"}, {**base, "timezone": "America/Detroit", "default_appointment_minutes": 180}]
            self.update = None

        def execute_single(self, query, params):
            return self.rows.pop(0)

        def execute_returning(self, query, params):
            self.update = (query, params)
            return [{"workspace_id": TEST_WORKSPACE_ID}]

    postgres = FakePostgres()
    with workspace_context(TEST_WORKSPACE_ID, "America/Chicago"):
        result = WorkspaceSettingsService(postgres).update(WorkspaceSettingsUpdate(
            timezone="America/Detroit",
            default_appointment_minutes=180,
        ))

    assert result.timezone == "America/Detroit"
    assert result.default_appointment_minutes == 180
    query, params = postgres.update
    assert "WITH workspace_update AS" in query
    assert params[0:2] == ("America/Detroit", TEST_WORKSPACE_ID)
    assert params[2] == 180


def test_workspace_settings_schema_owns_only_operational_defaults():
    schema = (Path(__file__).resolve().parents[2] / "schema.sql").read_text()
    settings_section = schema.split("-- workspace_settings", 1)[1].split("-- customers", 1)[0]
    assert "workday_start" in settings_section
    assert "service_reminder_mode" in settings_section
    assert "business_name" not in settings_section
    assert "reply_to_email" not in settings_section


def test_workspace_settings_defaults(client):
    response = client.get("/api/data", params={"type": "workspace_settings"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["timezone"] == "America/Chicago"
    assert data["workday_start"] == "08:00:00"
    assert data["workday_end"] == "17:00:00"
    assert data["working_days"] == ["mon", "tue", "wed", "thu", "fri"]
    assert data["default_appointment_minutes"] == 120
    assert data["travel_buffer_minutes"] == 30
    assert data["appointment_confirmation_enabled"] is True
    assert data["appointment_reminder_minutes"] == 1440
    assert data["service_reminder_mode"] == "ask_each_time"


def test_workspace_settings_partial_update(client):
    response = client.post(
        "/api/actions",
        json={
            "domain": "workspace_settings",
            "action": "update",
            "data": {
                "working_days": ["tue", "wed", "thu", "fri", "sat"],
                "appointment_reminder_minutes": None,
                "timezone": "America/Detroit",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["working_days"] == ["tue", "wed", "thu", "fri", "sat"]
    assert data["appointment_reminder_minutes"] is None
    assert data["timezone"] == "America/Detroit"
    assert data["default_appointment_minutes"] == 120


def test_workspace_settings_reject_invalid_values(client):
    response = client.post(
        "/api/actions",
        json={
            "domain": "workspace_settings",
            "action": "update",
            "data": {"working_days": []},
        },
    )

    assert response.status_code == 400


def test_workspace_settings_are_isolated(app, client):
    first = client.post(
        "/api/actions",
        json={
            "domain": "workspace_settings",
            "action": "update",
            "data": {"workday_start": "09:00"},
        },
    )
    assert first.status_code == 200

    client_b = TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {TEST_WORKSPACE_B_TOKEN}"},
    )
    second = client_b.get("/api/data", params={"type": "workspace_settings"})
    assert second.status_code == 200
    assert second.json()["data"]["workday_start"] == "08:00:00"
