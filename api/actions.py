"""POST /api/actions — unified mutation endpoint."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.base import success_response
from core.models import (
    CustomerCreate, CustomerUpdate,
    TicketCreate, TicketUpdate,
    ServiceCreate, ServiceUpdate,
    LineItemCreate, LineItemUpdate,
    AddressCreate, AddressUpdate,
    NoteCreate,
    ScheduledMessageCreate,
    AttributeCreate,
)


class ActionRequest(BaseModel):
    domain: str
    action: str
    data: dict


def create_actions_router(services: dict) -> APIRouter:
    router = APIRouter()

    handlers = {
        "customer": CustomerHandler(services["customer"]),
        "ticket": TicketHandler(services["ticket"]),
        "catalog": CatalogHandler(services["catalog"]),
        "line_item": LineItemHandler(services["line_item"]),
        "invoice": InvoiceHandler(services["invoice"]),
        "note": NoteHandler(services["note"]),
        "attribute": AttributeHandler(services["attribute"]),
        "message": MessageHandler(services["message"]),
        "address": AddressHandler(services["address"]),
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
        return success_response(result).model_dump(mode="json")

    return router


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
            raise ValueError(f"Customer {customer_id} not found")
        return {"deleted": True}


class TicketHandler:
    ALLOWED_ACTIONS = {"create", "update", "delete", "clock_in", "clock_out", "close", "cancel"}

    def __init__(self, service):
        self.service = service

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
            raise ValueError(f"Ticket {ticket_id} not found")
        return {"deleted": True}

    def _handle_clock_in(self, data: dict):
        ticket = self.service.clock_in(UUID(data["id"]))
        return ticket.model_dump(mode="json")

    def _handle_clock_out(self, data: dict):
        ticket = self.service.clock_out(UUID(data["id"]))
        return ticket.model_dump(mode="json")

    def _handle_close(self, data: dict):
        ticket = self.service.close(UUID(data["id"]))
        return ticket.model_dump(mode="json")

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
            raise ValueError(f"Service {service_id} not found")
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
            raise ValueError(f"Line item {line_item_id} not found")
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
            raise ValueError(f"Note {note_id} not found")
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
            raise ValueError(f"Attribute {attr_id} not found")
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
            raise ValueError(f"Address {address_id} not found")
        return {"deleted": True}
