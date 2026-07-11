"""Workspace lifecycle, access-token, and tenant-isolation tests."""

import hashlib
from datetime import datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from core.models import AddressCreate, CustomerCreate, TicketCreate
from starlette.testclient import TestClient
from tests.api.conftest import LIFECYCLE_SECRET
from tests.conftest import TEST_WORKSPACE_B_TOKEN
from utils.timezone import now_utc
from utils.workspace_context import workspace_context


def _lifecycle_headers():
    return {"Authorization": f"Bearer {LIFECYCLE_SECRET}"}


def test_provision_is_idempotent(app, db):
    workspace_id = uuid4()
    lifecycle = TestClient(app, headers=_lifecycle_headers())
    body = {"workspace_id": str(workspace_id), "timezone": "UTC"}
    assert lifecycle.post("/api/lifecycle/workspaces", json=body).status_code == 200
    assert lifecycle.post("/api/lifecycle/workspaces", json=body).status_code == 200
    with workspace_context(workspace_id, "UTC"):
        assert db.execute_scalar(
            "SELECT count(*) FROM workspaces WHERE id = %s",
            (workspace_id,),
        ) == 1
        assert db.execute_scalar(
            "SELECT count(*) FROM workspace_settings WHERE workspace_id = %s",
            (workspace_id,),
        ) == 1


def test_token_mint_persists_only_hash(app, db, test_workspace_id):
    lifecycle = TestClient(app, headers=_lifecycle_headers())
    response = lifecycle.post(
        f"/api/lifecycle/workspaces/{test_workspace_id}/tokens",
        json={"name": "MIRA", "scopes": ["read", "write"]},
    )
    assert response.status_code == 200
    raw_token = response.json()["data"]["token"]
    token_id = response.json()["data"]["id"]
    row = db.execute_single(
        "SELECT token_hash FROM workspace_access_tokens WHERE id = %s",
        (token_id,),
    )
    assert row["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in row["token_hash"]


def test_workspace_deletion_cascades_tenant_records(
    app,
    db,
    customer_service,
    test_workspace_id,
):
    with workspace_context(test_workspace_id, "UTC"):
        customer = customer_service.create(CustomerCreate(first_name="Cascade"))
        assert db.execute_scalar(
            "SELECT count(*) FROM customers WHERE id = %s",
            (customer.id,),
        ) == 1

    lifecycle = TestClient(app, headers=_lifecycle_headers())
    assert lifecycle.delete(f"/api/lifecycle/workspaces/{test_workspace_id}").status_code == 200
    with workspace_context(test_workspace_id, "UTC"):
        assert db.execute_scalar(
            "SELECT count(*) FROM customers WHERE id = %s",
            (customer.id,),
        ) == 0


def test_two_workspaces_cannot_read_or_mutate_each_other(
    app,
    db,
    customer_service,
    test_workspace_id,
    test_workspace_b_id,
):
    with workspace_context(test_workspace_id, "UTC"):
        customer = customer_service.create(CustomerCreate(first_name="Private"))

    client_b = TestClient(
        app,
        headers={"Authorization": f"Bearer {TEST_WORKSPACE_B_TOKEN}"},
        raise_server_exceptions=False,
    )
    read = client_b.get("/api/data", params={"type": "customers", "id": str(customer.id)})
    mutate = client_b.post(
        "/api/actions",
        json={"domain": "customer", "action": "delete", "data": {"id": str(customer.id)}},
    )
    assert read.status_code == 404
    assert mutate.status_code == 404
    with workspace_context(test_workspace_id, "UTC"):
        assert db.execute_scalar(
            "SELECT count(*) FROM customers WHERE id = %s",
            (customer.id,),
        ) == 1


def test_today_query_uses_workspace_timezone(
    client,
    db,
    customer_service,
    address_service,
    ticket_service,
    test_workspace_id,
):
    timezone = "Pacific/Auckland"
    local_timezone = ZoneInfo(timezone)
    with workspace_context(test_workspace_id, timezone):
        db.execute("UPDATE workspaces SET timezone = %s WHERE id = %s", (timezone, test_workspace_id))
        customer = customer_service.create(CustomerCreate(first_name="Timezone"))
        address = address_service.create(
            AddressCreate(customer_id=customer.id, street="1 Time Lane")
        )
        ticket = ticket_service.create(
            TicketCreate(
                customer_id=customer.id,
                address_id=address.id,
                scheduled_at=datetime.combine(
                    now_utc().astimezone(local_timezone).date(),
                    time(9),
                    tzinfo=local_timezone,
                ),
            )
        )

    response = client.get("/api/data/tickets/today")
    assert response.status_code == 200
    assert str(ticket.id) in {row["id"] for row in response.json()["data"]}
