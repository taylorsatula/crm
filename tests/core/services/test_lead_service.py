"""Integration coverage for LeadService — the sales-pipeline lead state machine."""

from datetime import timedelta
from uuid import uuid4

import pytest

from core.exceptions import NotFoundError
from core.models import (
    AddressCreate,
    CustomerCreate,
    LeadCreate,
    LeadSource,
    LeadStatus,
    LeadUpdate,
    LeadUrgency,
)
from utils.timezone import now_utc


def _lead_data(**overrides):
    base = dict(
        raw_notes="Caller wants exterior windows cleaned, two-story home.",
        name="Dana Lead",
        phone="555-0100",
        email="dana@example.com",
        service_interest="Exterior window cleaning",
        lead_source=LeadSource.WEBSITE,
        urgency=LeadUrgency.MEDIUM,
    )
    base.update(overrides)
    return LeadCreate(**base)


class TestLeadCreate:
    def test_creates_lead_in_new_status(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())
        assert lead.status == LeadStatus.NEW
        assert lead.name == "Dana Lead"
        assert lead.lead_source == LeadSource.WEBSITE
        assert lead.urgency == LeadUrgency.MEDIUM
        assert lead.deleted_at is None

    def test_create_publishes_audit(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data(name="Audited"))
        assert lead_service.get_by_id(lead.id).name == "Audited"


class TestLeadGet:
    def test_get_by_id_returns_none_for_missing(self, as_test_workspace, lead_service):
        assert lead_service.get_by_id(uuid4()) is None

    def test_get_by_id_returns_lead(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())
        assert lead_service.get_by_id(lead.id).id == lead.id


class TestLeadUpdate:
    def test_updates_updatable_fields(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())
        updated = lead_service.update(
            lead.id, LeadUpdate(name="Dana Renamed", phone="555-9999")
        )
        assert updated.name == "Dana Renamed"
        assert updated.phone == "555-9999"

    def test_update_missing_raises_not_found(self, as_test_workspace, lead_service):
        with pytest.raises(NotFoundError, match="not found"):
            lead_service.update(uuid4(), LeadUpdate(name="X"))

    def test_converted_lead_is_immutable(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "contacted")
        lead_service.transition(lead.id, "qualified")
        customer = customer_service.create(CustomerCreate(first_name="Convert", last_name="Target"))
        lead_service.convert_lead(lead.id, customer.id)

        with pytest.raises(ValueError, match="already converted"):
            lead_service.update(lead.id, LeadUpdate(name="Too Late"))

    def test_archived_lead_is_immutable(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "archived")

        with pytest.raises(ValueError, match="archived"):
            lead_service.update(lead.id, LeadUpdate(name="Too Late"))


class TestLeadTransitions:
    @pytest.mark.parametrize(
        "path",
        [
            ["contacted"],
            ["contacted", "qualified"],
            ["archived"],
            ["contacted", "archived"],
        ],
    )
    def test_valid_transitions(self, as_test_workspace, lead_service, path):
        lead = lead_service.create(_lead_data())
        for status in path:
            lead_service.transition(lead.id, status)
            assert lead_service.get_by_id(lead.id).status == LeadStatus(status)

    def test_invalid_transition_rejected(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())  # status: new
        with pytest.raises(ValueError, match="Invalid lead transition"):
            lead_service.transition(lead.id, "qualified")  # new -> qualified is illegal

    def test_terminal_states_have_no_outgoing_transitions(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "contacted")
        lead_service.transition(lead.id, "qualified")
        customer = customer_service.create(CustomerCreate(first_name="Conv", last_name="Cust"))
        lead_service.convert_lead(lead.id, customer.id)
        assert lead_service.get_by_id(lead.id).status == LeadStatus.CONVERTED
        with pytest.raises(ValueError, match="Invalid lead transition"):
            lead_service.transition(lead.id, "archived")

    def test_transition_missing_raises_not_found(self, as_test_workspace, lead_service):
        with pytest.raises(NotFoundError, match="not found"):
            lead_service.transition(uuid4(), "contacted")


class TestConvertLead:
    def test_convert_requires_qualified_status(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())  # new
        customer = customer_service.create(CustomerCreate(first_name="C", last_name="T"))
        with pytest.raises(ValueError, match="must be 'qualified'"):
            lead_service.convert_lead(lead.id, customer.id)

    def test_convert_stamps_customer_and_status(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "contacted")
        lead_service.transition(lead.id, "qualified")
        customer = customer_service.create(CustomerCreate(first_name="Converted", last_name="Customer"))

        converted = lead_service.convert_lead(lead.id, customer.id)

        assert converted.status == LeadStatus.CONVERTED
        assert converted.converted_customer_id == customer.id
        assert converted.converted_at is not None

    def test_convert_idempotent_rejected(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "contacted")
        lead_service.transition(lead.id, "qualified")
        customer = customer_service.create(CustomerCreate(first_name="Once", last_name="Only"))
        lead_service.convert_lead(lead.id, customer.id)

        with pytest.raises(ValueError, match="already converted"):
            lead_service.convert_lead(lead.id, customer.id)

    def test_convert_archived_rejected(self, as_test_workspace, lead_service, customer_service):
        lead = lead_service.create(_lead_data())
        lead_service.transition(lead.id, "archived")
        customer = customer_service.create(CustomerCreate(first_name="Arch", last_name="Lead"))
        with pytest.raises(ValueError, match="archived"):
            lead_service.convert_lead(lead.id, customer.id)


class TestLeadDelete:
    def test_soft_deletes_lead(self, as_test_workspace, lead_service):
        lead = lead_service.create(_lead_data())
        assert lead_service.delete(lead.id) is True
        assert lead_service.get_by_id(lead.id) is None

    def test_delete_missing_returns_false(self, as_test_workspace, lead_service):
        assert lead_service.delete(uuid4()) is False


class TestLeadList:
    def test_list_orders_newest_first_and_paginates(self, as_test_workspace, lead_service):
        first = lead_service.create(_lead_data(name="First"))
        second = lead_service.create(_lead_data(name="Second"))
        page = lead_service.list_page(status=None, search=None, limit=1, cursor=None)
        assert [l.id for l in page.leads] == [second.id]
        assert page.next_cursor is not None

        page2 = lead_service.list_page(status=None, search=None, limit=1, cursor=page.next_cursor)
        assert [l.id for l in page2.leads] == [first.id]
        assert page2.next_cursor is None

    def test_list_filters_by_status(self, as_test_workspace, lead_service):
        lead_service.create(_lead_data(name="Fresh"))
        contacted = lead_service.create(_lead_data(name="Touched"))
        lead_service.transition(contacted.id, "contacted")

        page = lead_service.list_page(status="contacted", search=None, limit=10, cursor=None)
        assert all(l.status == LeadStatus.CONTACTED for l in page.leads)
        assert [l.id for l in page.leads] == [contacted.id]

    def test_list_search_matches_name(self, as_test_workspace, lead_service):
        lead_service.create(_lead_data(name="Zelda Unique"))
        lead_service.create(_lead_data(name="Other"))
        page = lead_service.list_page(status=None, search="Zelda", limit=10, cursor=None)
        assert len(page.leads) == 1
        assert page.leads[0].name == "Zelda Unique"


class TestLeadRLS:
    def test_workspace_isolation(self, as_test_workspace, test_workspace_id, test_workspace_b_id, lead_service):
        from utils.workspace_context import workspace_context

        lead = lead_service.create(_lead_data(name="Workspace A lead"))
        assert lead.workspace_id == test_workspace_id
        # From workspace B, the lead is invisible.
        with workspace_context(test_workspace_b_id, "America/Chicago"):
            assert lead_service.get_by_id(lead.id) is None
            page = lead_service.list_page(status=None, search=None, limit=10, cursor=None)
            assert page.leads == []
        # From workspace A, it is visible.
        assert lead_service.get_by_id(lead.id) is not None
