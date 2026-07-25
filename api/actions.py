"""POST /api/actions — unified mutation endpoint."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.base import success_response
from core.exceptions import NotFoundError
from core.models import (
    CustomerCreate, CustomerUpdate,
    CloseoutRequest,
    TicketCreate, TicketUpdate,
    ServiceCreate, ServiceUpdate,
    LineItemCreate, LineItemUpdate,
    AddressCreate, AddressUpdate,
    NoteCreate,
    ScheduledMessageCreate,
    AttributeCreate,
    WorkspaceSettingsUpdate,
    SquareImportBatchRequest,
    NewCustomerJobBookingCreate,
    LeadCreate, LeadUpdate,
    QuoteCreate, QuoteUpdate,
    QuoteLineItemCreate, QuoteLineItemUpdate,
)


class ActionRequest(BaseModel):
    domain: str
    action: str
    data: dict


def create_actions_router(services: dict) -> APIRouter:
    router = APIRouter()

    handlers = {
        "customer": CustomerHandler(services["customer"]),
        "ticket": TicketHandler(services["ticket"], services["closeout"]),
        "catalog": CatalogHandler(services["catalog"]),
        "line_item": LineItemHandler(services["line_item"]),
        "invoice": InvoiceHandler(services["invoice"]),
        "note": NoteHandler(services["note"]),
        "attribute": AttributeHandler(services["attribute"]),
        "message": MessageHandler(services["message"]),
        "address": AddressHandler(services["address"]),
        "workspace_settings": WorkspaceSettingsHandler(services["workspace_settings"]),
        "square_import": SquareImportHandler(services["square_import"]),
        "workflow": WorkflowHandler(services["workflow"]),
        "lead": LeadHandler(services["lead"]),
        "quote": QuoteHandler(services["quote"]),
        "quote_line_item": QuoteLineItemHandler(services["quote"]),
    }

    @router.post("/actions")
    async def perform_action(request: Request, body: ActionRequest):
        handler = handlers.get(body.domain)
        if handler is None:
            raise ValueError(
                f"Unknown domain '{body.domain}'. "
                f"Valid domains: {', '.join(sorted(handlers.keys()))}"
            )

        if body.action not in handler.ALLOWED_ACTIONS:
            raise ValueError(
                f"Action '{body.action}' not allowed on '{body.domain}'. "
                f"Allowed: {', '.join(sorted(handler.ALLOWED_ACTIONS))}"
            )

        method = getattr(handler, f"_handle_{body.action}", None)
        result = method(body.data)
        return success_response(
            result,
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    return router



class SquareImportHandler:
    """Apply trusted Square history chunks from CRM Mira."""

    ALLOWED_ACTIONS = {"apply_batch"}

    def __init__(self, service):
        self.service = service

    def _handle_apply_batch(self, data: dict):
        result = self.service.apply_batch(SquareImportBatchRequest(**data))
        return result.model_dump(mode="json")


class WorkflowHandler:
    """Execute canonical multi-entity CRM workflows."""

    ALLOWED_ACTIONS = {"book_new_customer_job"}

    def __init__(self, service):
        self.service = service

    def _handle_book_new_customer_job(self, data: dict):
        booking = self.service.book_new_customer_job(NewCustomerJobBookingCreate(**data))
        return booking.model_dump(mode="json")


class WorkspaceSettingsHandler:

    """Update the current workspace's operational defaults."""

    ALLOWED_ACTIONS = {"update"}

    def __init__(self, service):
        self.service = service

    def _handle_update(self, data: dict):
        settings = self.service.update(WorkspaceSettingsUpdate(**data))
        return settings.model_dump(mode="json")


# =============================================================================
# HANDLER CLASSES
# =============================================================================


class CustomerHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        customer = self.service.create(CustomerCreate(**data))
        return customer.model_dump(mode="json")

    def _handle_update(self, data: dict):
        customer_id = UUID(data.pop("id"))
        customer = self.service.update(customer_id, CustomerUpdate(**data))
        return customer.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        customer_id = UUID(data["id"])
        deleted = self.service.delete(customer_id)
        if not deleted:
            raise NotFoundError(f"Customer {customer_id} not found")
        return {"deleted": True}


class TicketHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete", "clock_in", "clock_out", "closeout", "cancel"}

    def __init__(self, service, closeout_service):
        self.service = service
        self.closeout_service = closeout_service

    def _handle_create(self, data: dict):
        ticket = self.service.create(TicketCreate(**data))
        return ticket.model_dump(mode="json")

    def _handle_update(self, data: dict):
        ticket_id = UUID(data.pop("id"))
        ticket = self.service.update(ticket_id, TicketUpdate(**data))
        return ticket.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        ticket_id = UUID(data["id"])
        deleted = self.service.delete(ticket_id)
        if not deleted:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        return {"deleted": True}

    def _handle_clock_in(self, data: dict):
        ticket = self.service.clock_in(UUID(data["id"]))
        return ticket.model_dump(mode="json")

    def _handle_clock_out(self, data: dict):
        ticket = self.service.clock_out(UUID(data["id"]))
        return ticket.model_dump(mode="json")

    def _handle_closeout(self, data: dict):
        result = self.closeout_service.closeout(CloseoutRequest(**data))
        return result.model_dump(mode="json")

    def _handle_cancel(self, data: dict):
        ticket = self.service.cancel(UUID(data["id"]))
        return ticket.model_dump(mode="json")


class CatalogHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        service = self.service.create(ServiceCreate(**data))
        return service.model_dump(mode="json")

    def _handle_update(self, data: dict):
        service_id = UUID(data.pop("id"))
        service = self.service.update(service_id, ServiceUpdate(**data))
        return service.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        service_id = UUID(data["id"])
        deleted = self.service.delete(service_id)
        if not deleted:
            raise NotFoundError(f"Service {service_id} not found")
        return {"deleted": True}


class LineItemHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        ticket_id = UUID(data.pop("ticket_id"))
        line_item = self.service.create(ticket_id, LineItemCreate(**data))
        return line_item.model_dump(mode="json")

    def _handle_update(self, data: dict):
        line_item_id = UUID(data.pop("id"))
        line_item = self.service.update(line_item_id, LineItemUpdate(**data))
        return line_item.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        line_item_id = UUID(data["id"])
        deleted = self.service.delete(line_item_id)
        if not deleted:
            raise NotFoundError(f"Line item {line_item_id} not found")
        return {"deleted": True}


class InvoiceHandler:
    ALLOWED_ACTIONS = {"create_from_ticket", "send", "record_payment", "void"}

    def __init__(self, service):
        self.service = service

    def _handle_create_from_ticket(self, data: dict):
        ticket_id = UUID(data["ticket_id"])
        tax_rate_bps = data.get("tax_rate_bps", 0)
        notes = data.get("notes")
        invoice = self.service.create_from_ticket(ticket_id, tax_rate_bps, notes)
        return invoice.model_dump(mode="json")

    def _handle_send(self, data: dict):
        invoice = self.service.send(UUID(data["id"]))
        return invoice.model_dump(mode="json")

    def _handle_record_payment(self, data: dict):
        invoice = self.service.record_payment(UUID(data["id"]), data["amount_cents"])
        return invoice.model_dump(mode="json")

    def _handle_void(self, data: dict):
        invoice = self.service.void(UUID(data["id"]))
        return invoice.model_dump(mode="json")


class NoteHandler:
    ALLOWED_ACTIONS = {"create", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        note = self.service.create(NoteCreate(**data))
        return note.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        note_id = UUID(data["id"])
        deleted = self.service.delete(note_id)
        if not deleted:
            raise NotFoundError(f"Note {note_id} not found")
        return {"deleted": True}


class AttributeHandler:
    ALLOWED_ACTIONS = {"create", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        attr = self.service.create(AttributeCreate(**data))
        return attr.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        attr_id = UUID(data["id"])
        deleted = self.service.delete(attr_id)
        if not deleted:
            raise NotFoundError(f"Attribute {attr_id} not found")
        return {"deleted": True}


class MessageHandler:
    ALLOWED_ACTIONS = {"schedule", "cancel"}

    def __init__(self, service):
        self.service = service

    def _handle_schedule(self, data: dict):
        message = self.service.schedule(ScheduledMessageCreate(**data))
        return message.model_dump(mode="json")

    def _handle_cancel(self, data: dict):
        message = self.service.cancel(UUID(data["id"]))
        return message.model_dump(mode="json")


class AddressHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        address = self.service.create(AddressCreate(**data))
        return address.model_dump(mode="json")

    def _handle_update(self, data: dict):
        address_id = UUID(data.pop("id"))
        address = self.service.update(address_id, AddressUpdate(**data))
        return address.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        address_id = UUID(data["id"])
        deleted = self.service.delete(address_id)
        if not deleted:
            raise NotFoundError(f"Address {address_id} not found")
        return {"deleted": True}


class LeadHandler:
    """Manage CRM leads across the sales pipeline."""

    ALLOWED_ACTIONS = {"create", "update", "transition", "convert", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        lead = self.service.create(LeadCreate(**data))
        return lead.model_dump(mode="json")

    def _handle_update(self, data: dict):
        lead_id = UUID(data.pop("id"))
        lead = self.service.update(lead_id, LeadUpdate(**data))
        return lead.model_dump(mode="json")

    def _handle_transition(self, data: dict):
        lead_id = UUID(data["id"])
        target_status = data["status"]
        lead = self.service.transition(lead_id, target_status)
        return lead.model_dump(mode="json")

    def _handle_convert(self, data: dict):
        lead_id = UUID(data["lead_id"])
        customer_id = UUID(data["customer_id"])
        lead = self.service.convert_lead(lead_id, customer_id)
        return lead.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        lead_id = UUID(data["id"])
        deleted = self.service.delete(lead_id)
        if not deleted:
            raise NotFoundError(f"Lead {lead_id} not found")
        return {"deleted": True}


class QuoteHandler:
    """Manage CRM quotes and their lifecycle."""

    ALLOWED_ACTIONS = {"create", "update", "send", "accept", "reject", "expire", "archive", "delete"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        quote = self.service.create(QuoteCreate(**data))
        return quote.model_dump(mode="json")

    def _handle_update(self, data: dict):
        quote_id = UUID(data.pop("id"))
        quote = self.service.update(quote_id, QuoteUpdate(**data))
        return quote.model_dump(mode="json")

    def _handle_send(self, data: dict):
        quote = self.service.transition(UUID(data["id"]), "sent")
        return quote.model_dump(mode="json")

    def _handle_accept(self, data: dict):
        quote_id = UUID(data["id"])
        ticket_id = UUID(data["created_ticket_id"])
        quote = self.service.accept(quote_id, ticket_id)
        return quote.model_dump(mode="json")

    def _handle_reject(self, data: dict):
        quote = self.service.transition(UUID(data["id"]), "rejected")
        return quote.model_dump(mode="json")

    def _handle_expire(self, data: dict):
        quote = self.service.transition(UUID(data["id"]), "expired")
        return quote.model_dump(mode="json")

    def _handle_archive(self, data: dict):
        quote = self.service.transition(UUID(data["id"]), "archived")
        return quote.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        quote_id = UUID(data["id"])
        deleted = self.service.delete(quote_id)
        if not deleted:
            raise NotFoundError(f"Quote {quote_id} not found")
        return {"deleted": True}


class QuoteLineItemHandler:
    """Manage quote line items scoped to draft quotes."""

    ALLOWED_ACTIONS = {"create", "update", "delete", "list"}

    def __init__(self, service):
        self.service = service

    def _handle_create(self, data: dict):
        quote_id = UUID(data.pop("quote_id"))
        li = self.service.create_line_item(quote_id, QuoteLineItemCreate(**data))
        return li.model_dump(mode="json")

    def _handle_update(self, data: dict):
        li_id = UUID(data.pop("id"))
        li = self.service.update_line_item(li_id, QuoteLineItemUpdate(**data))
        return li.model_dump(mode="json")

    def _handle_delete(self, data: dict):
        li_id = UUID(data["id"])
        deleted = self.service.delete_line_item(li_id)
        if not deleted:
            raise NotFoundError(f"Quote line item {li_id} not found")
        return {"deleted": True}

    def _handle_list(self, data: dict):
        quote_id = UUID(data["quote_id"])
        items = self.service.list_line_items(quote_id)
        return [li.model_dump(mode="json") for li in items]
