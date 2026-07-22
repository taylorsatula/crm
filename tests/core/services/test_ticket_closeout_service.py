"""Integration coverage for the canonical structured ticket-closeout workflow."""

from datetime import timedelta

import pytest

from core.models import (
    AddressCreate,
    BillingHoldResolution,
    CloseoutRequest,
    CustomerCreate,
    LineItemCreate,
    PricingType,
    ServiceCreate,
    TicketCreate,
)
from utils.timezone import now_utc


def _ticket_with_line(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
):
    customer = customer_service.create(CustomerCreate(first_name="Closeout", last_name="Customer"))
    address = address_service.create(AddressCreate(
        customer_id=customer.id,
        street="1 Reconcile Way",
        city="Austin",
        state="TX",
        zip="78701",
    ))
    service = catalog_service.create(ServiceCreate(
        name="Closeout Service",
        pricing_type=PricingType.FIXED,
        default_price_cents=5000,
    ))
    ticket = ticket_service.create(TicketCreate(
        customer_id=customer.id,
        address_id=address.id,
        scheduled_at=now_utc() + timedelta(days=1),
        scheduled_duration_minutes=90,
    ))
    line_item = line_item_service.create(ticket.id, LineItemCreate(
        service_id=service.id,
        quantity=2,
        unit_price_cents=5000,
        total_price_cents=10000,
        duration_minutes=90,
    ))
    return customer, address, service, ticket, line_item


def _base_request(ticket_id):
    return {
        "ticket_id": ticket_id,
        "actual_duration_minutes": 90,
        "work_reconciliation": {
            "quoted_scope_status": "completed",
            "result_status": "achieved",
            "deviations": [],
        },
        "customer_capture": {
            "customer_response": "unknown",
            "profile_updates": [],
        },
        "next_service": {"disposition": "not_applicable"},
        "follow_up_actions": [],
    }


def test_completed_quote_closes_without_reenumerating_lines(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
):
    customer, _, _, ticket, line_item = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )

    result = closeout_service.closeout(CloseoutRequest.model_validate(_base_request(ticket.id)))

    assert result.ticket["status"] == "completed"
    assert result.ticket["actual_duration_minutes"] == 90
    assert result.closeout.work_reconciliation.quoted_scope_status == "completed"
    assert result.closeout.invoice_ready is True
    assert line_item_service.get_by_id(line_item.id).quantity == 2
    assert line_item_service.get_by_id(line_item.id).total_price_cents == 10000
    assert closeout_service.get_for_ticket(ticket.id).id == result.closeout.id
    assert closeout_service.list_profile_updates_for_customer(customer.id) == []


def test_partial_billable_deviation_updates_final_line_and_preserves_quote_snapshot(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
    db,
):
    _, _, _, ticket, line_item = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )
    payload = _base_request(ticket.id)
    payload["work_reconciliation"] = {
        "quoted_scope_status": "partially_completed",
        "result_status": "achieved_with_limitations",
        "deviations": [{
            "deviation_type": "partially_completed",
            "line_item_id": str(line_item.id),
            "description": "One unit was inaccessible.",
            "actual_quantity": 1,
            "billing_disposition": "billable",
            "customer_acknowledgement": "informed_no_concern",
        }],
    }

    result = closeout_service.closeout(CloseoutRequest.model_validate(payload))

    final_line = line_item_service.get_by_id(line_item.id)
    assert final_line.quantity == 1
    assert final_line.total_price_cents == 5000
    assert result.closeout.final_subtotal_cents == 5000
    snapshot = db.execute_single(
        """
        SELECT quoted_line_item, final_line_item
        FROM ticket_closeout_line_items
        WHERE ticket_closeout_id = %s AND line_item_id = %s
        """,
        (result.closeout.id, line_item.id),
    )
    assert snapshot["quoted_line_item"]["quantity"] == 2
    assert snapshot["quoted_line_item"]["total_price_cents"] == 10000
    assert snapshot["final_line_item"]["quantity"] == 1
    assert snapshot["final_line_item"]["total_price_cents"] == 5000


def test_billable_omission_preserves_explicit_final_charge(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
):
    _, _, _, ticket, line_item = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )
    payload = _base_request(ticket.id)
    payload["work_reconciliation"] = {
        "quoted_scope_status": "not_completed",
        "result_status": "not_achieved",
        "deviations": [{
            "deviation_type": "omitted",
            "line_item_id": str(line_item.id),
            "description": "Access was denied after travel began.",
            "billing_disposition": "billable",
            "final_price_cents": 2500,
            "customer_acknowledgement": "informed_no_concern",
        }],
    }

    result = closeout_service.closeout(CloseoutRequest.model_validate(payload))

    final_line = line_item_service.get_by_id(line_item.id)
    assert final_line.quantity == 0
    assert final_line.total_price_cents == 2500
    assert result.closeout.final_subtotal_cents == 2500


def test_substitution_uses_the_replacement_catalog_unit_price(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
):
    _, _, _, ticket, line_item = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )
    replacement = catalog_service.create(ServiceCreate(
        name="Replacement per-unit service",
        pricing_type=PricingType.PER_UNIT,
        unit_price_cents=3000,
    ))
    payload = _base_request(ticket.id)
    payload["work_reconciliation"] = {
        "quoted_scope_status": "partially_completed",
        "result_status": "achieved",
        "deviations": [{
            "deviation_type": "substituted",
            "line_item_id": str(line_item.id),
            "service_id": str(replacement.id),
            "description": "The quoted service was replaced with the per-unit alternative.",
            "billing_disposition": "billable",
        }],
    }

    closeout_service.closeout(CloseoutRequest.model_validate(payload))

    final_line = line_item_service.get_by_id(line_item.id)
    assert final_line.service_id == replacement.id
    assert final_line.unit_price_cents == 3000
    assert final_line.total_price_cents == 6000


def test_billing_hold_blocks_then_releases_invoice_creation(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
    invoice_service,
):
    _, _, _, ticket, _ = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )
    payload = _base_request(ticket.id)
    payload["work_reconciliation"]["deviations"] = [{
        "deviation_type": "billing_uncertainty",
        "affected_item": "the final price",
        "description": "The office must reconcile the disputed add-on before invoicing.",
        "escalation": {
            "category": "billing_uncertainty",
            "disposition": "follow_up_required",
            "action": {
                "action_type": "create_quote",
                "responsible_party": "business",
                "description": "Resolve the final charge with the customer.",
            },
        },
    }]

    result = closeout_service.closeout(CloseoutRequest.model_validate(payload))

    assert result.closeout.invoice_ready is False
    with pytest.raises(ValueError, match="unresolved billing escalation"):
        invoice_service.create_from_ticket(ticket.id)

    resolved = closeout_service.resolve_billing_hold(BillingHoldResolution(
        ticket_id=ticket.id,
        confirmed_total_cents=result.closeout.final_subtotal_cents,
        resolution_note="Customer approved the reconciled total by phone.",
    ))

    assert resolved.invoice_ready is True
    escalation = resolved.work_reconciliation.deviations[0].escalation
    assert escalation is not None
    assert escalation.disposition == "resolved"
    assert escalation.resolution_note == "Customer approved the reconciled total by phone."
    assert closeout_service.list_follow_up_actions_for_ticket(ticket.id)[0].status == "completed"
    assert invoice_service.create_from_ticket(ticket.id).subtotal_cents == 10000


def test_route_flexible_plan_and_profile_fact_create_office_actions(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    line_item_service,
    closeout_service,
):
    customer, _, _, ticket, _ = _ticket_with_line(
        customer_service,
        address_service,
        catalog_service,
        ticket_service,
        line_item_service,
    )
    payload = _base_request(ticket.id)
    payload["work_reconciliation"]["deviations"] = [{
        "deviation_type": "customer_concern",
        "affected_item": "the completed service",
        "description": "The customer disputes the final result.",
        "customer_acknowledgement": "disputed",
        "escalation": {
            "category": "customer_concern_or_dispute",
            "disposition": "follow_up_required",
            "action": {
                "action_type": "schedule_return_visit",
                "responsible_party": "business",
                "description": "Schedule a return visit to review the concern.",
            },
        },
    }]
    payload["customer_capture"] = {
        "appointment_contact": {
            "name": "Morgan Customer",
            "relationship_to_account": "spouse",
            "source": "technician_reported_customer_statement",
            "certainty": "likely",
        },
        "customer_response": "concern_stated",
        "profile_updates": [{
            "update_type": "asset_condition",
            "asset": "front entry fixture",
            "condition": "brittle and requires gentle handling",
            "handling_instruction": "Do not apply pressure to the fixture.",
            "source": "technician_observed",
            "certainty": "confirmed",
            "persistence": "durable",
        }],
    }
    payload["next_service"] = {
        "disposition": "book",
        "timing": {
            "window_start": str(now_utc().date() + timedelta(days=30)),
            "window_end": str(now_utc().date() + timedelta(days=37)),
            "timing_note": "When the route is nearby.",
        },
        "pricing_status": "catalog_default",
        "scheduling_mode": "route_flexible",
        "routing_instruction": "Book only when nearby.",
        "confirmation_channel": "text",
    }
    payload["follow_up_actions"] = [
        {
            "action_type": "create_quote",
            "responsible_party": "business",
            "description": "Quote the optional fixture repair.",
        },
        {
            "action_type": "schedule_return_visit",
            "responsible_party": "business",
            "description": "Schedule a return visit to review the concern.",
        },
    ]

    result = closeout_service.closeout(CloseoutRequest.model_validate(payload))

    assert result.future_ticket is None
    assert result.service_plan is not None
    assert result.service_plan.status == "pending"
    assert result.service_plan.planned_scope[0].service_id
    assert len(result.profile_updates) == 1
    assert result.profile_updates[0].update.update_type == "asset_condition"
    action_types = {action.action_type for action in result.follow_up_actions}
    assert action_types == {"create_quote", "schedule_return_visit", "send_confirmation"}
    assert len(result.follow_up_actions) == 3
    assert closeout_service.list_service_plans_for_customer(customer.id)[0].id == result.service_plan.id
