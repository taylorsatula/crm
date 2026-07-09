"""Workspace provisioning, deletion, and tenant isolation tests."""

from datetime import datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from core.models import AddressCreate, CustomerCreate, TicketCreate
from starlette.testclient import TestClient
from utils.timezone import now_utc
from utils.workspace_context import workspace_context

from tests.api.conftest import INTERNAL_SECRET


def _headers(workspace_id):
    return {
        "Authorization": f"Bearer {INTERNAL_SECRET}",
        "X-Workspace-ID": str(workspace_id),
        "X-Workspace-Timezone": "UTC",
    }


def test_provision_is_idempotent(client, db, test_workspace_id):
    assert client.post("/api/workspace/provision").status_code == 200
    assert client.post("/api/workspace/provision").status_code == 200
    with workspace_context(test_workspace_id, "UTC"):
        assert db.execute_scalar("SELECT count(*) FROM workspaces WHERE id = %s", (test_workspace_id,)) == 1


def test_workspace_deletion_cascades_tenant_records(client, db, customer_service, test_workspace_id):
    with workspace_context(test_workspace_id, "UTC"):
        customer = customer_service.create(CustomerCreate(first_name="Cascade"))
        assert db.execute_scalar("SELECT count(*) FROM customers WHERE id = %s", (customer.id,)) == 1

    assert client.delete("/api/workspace").status_code == 200
    with workspace_context(test_workspace_id, "UTC"):
        assert db.execute_scalar("SELECT count(*) FROM customers WHERE id = %s", (customer.id,)) == 0


def test_two_workspaces_cannot_read_or_mutate_each_other(app, db, customer_service, test_workspace_id, test_workspace_b_id):
    with workspace_context(test_workspace_id, "UTC"):
        customer = customer_service.create(CustomerCreate(first_name="Private"))

    client_b = TestClient(app, headers=_headers(test_workspace_b_id), raise_server_exceptions=False)
    read = client_b.get("/api/data", params={"type": "customers", "id": str(customer.id)})
    mutate = client_b.post("/api/actions", json={
        "domain": "customer", "action": "delete", "data": {"id": str(customer.id)},
    })
    assert read.status_code == 404
    assert mutate.status_code == 404
    with workspace_context(test_workspace_id, "UTC"):
        assert db.execute_scalar("SELECT count(*) FROM customers WHERE id = %s", (customer.id,)) == 1


def test_today_query_uses_request_timezone(client, customer_service, address_service, ticket_service, test_workspace_id):
    timezone = "Pacific/Auckland"
    local_timezone = ZoneInfo(timezone)
    with workspace_context(test_workspace_id, timezone):
        customer = customer_service.create(CustomerCreate(first_name="Timezone"))
        address = address_service.create(AddressCreate(customer_id=customer.id, street="1 Time Lane"))
        ticket = ticket_service.create(TicketCreate(
            customer_id=customer.id,
            address_id=address.id,
            scheduled_at=datetime.combine(now_utc().astimezone(local_timezone).date(), time(9), tzinfo=local_timezone),
        ))

    response = client.get("/api/data/tickets/today", headers={"X-Workspace-Timezone": timezone})
    assert response.status_code == 200
    assert str(ticket.id) in {row["id"] for row in response.json()["data"]}
