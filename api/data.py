"""GET /api/data — unified read endpoint."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from api.base import success_response, ErrorCodes


VALID_TYPES = {"customers", "tickets", "services", "invoices"}


def create_data_router(services: dict) -> APIRouter:
    router = APIRouter()

    customer_svc = services["customer"]
    ticket_svc = services["ticket"]
    catalog_svc = services["catalog"]
    line_item_svc = services["line_item"]
    invoice_svc = services["invoice"]
    note_svc = services["note"]
    address_svc = services["address"]

    # -------------------------------------------------------------------------
    # Convenience routes (must be registered before the generic /data route)
    # -------------------------------------------------------------------------

    @router.get("/data/tickets/today")
    async def tickets_today(request: Request):
        tickets = ticket_svc.list_today()
        return success_response(
            [t.model_dump(mode="json") for t in tickets]
        ).model_dump(mode="json")

    @router.get("/data/tickets/current")
    async def tickets_current(request: Request):
        ticket = ticket_svc.get_current()
        data = ticket.model_dump(mode="json") if ticket else None
        return success_response(data).model_dump(mode="json")

    # -------------------------------------------------------------------------
    # Generic data endpoint
    # -------------------------------------------------------------------------

    @router.get("/data")
    async def get_data(
        request: Request,
        type: str | None = Query(None),
        id: str | None = Query(None),
        search: str | None = Query(None),
        customer_id: str | None = Query(None),
        include: str | None = Query(None),
        filter: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        if type is None:
            raise ValueError("'type' query parameter is required")

        if type not in VALID_TYPES:
            raise ValueError(f"Unknown type '{type}'. Valid types: {', '.join(sorted(VALID_TYPES))}")

        includes = set(include.split(",")) if include else set()

        if type == "customers":
            return _handle_customers(
                customer_svc, address_svc, id, search, includes, limit, offset
            )

        if type == "tickets":
            return _handle_tickets(
                ticket_svc, line_item_svc, note_svc, id, customer_id, includes, limit
            )

        if type == "services":
            return _handle_services(catalog_svc, filter)

        if type == "invoices":
            return _handle_invoices(invoice_svc, filter, limit)

    return router


def _handle_customers(customer_svc, address_svc, id, search, includes, limit, offset):
    if id:
        customer = customer_svc.get_by_id(UUID(id))
        if customer is None:
            raise ValueError(f"Customer {id} not found")

        data = customer.model_dump(mode="json")
        if "addresses" in includes:
            addresses = address_svc.list_for_customer(customer.id)
            data["addresses"] = [a.model_dump(mode="json") for a in addresses]

        return success_response(data).model_dump(mode="json")

    if search:
        customers = customer_svc.search(search, limit)
        return success_response(
            [c.model_dump(mode="json") for c in customers]
        ).model_dump(mode="json")

    customers = customer_svc.list_all(limit, offset)
    return success_response(
        [c.model_dump(mode="json") for c in customers]
    ).model_dump(mode="json")


def _handle_tickets(ticket_svc, line_item_svc, note_svc, id, customer_id, includes, limit):
    if id:
        ticket = ticket_svc.get_by_id(UUID(id))
        if ticket is None:
            raise ValueError(f"Ticket {id} not found")

        data = ticket.model_dump(mode="json")
        if "line_items" in includes:
            items = line_item_svc.list_for_ticket(ticket.id)
            data["line_items"] = [li.model_dump(mode="json") for li in items]
        if "notes" in includes:
            notes = note_svc.list_for_ticket(ticket.id)
            data["notes"] = [n.model_dump(mode="json") for n in notes]

        return success_response(data).model_dump(mode="json")

    if customer_id:
        tickets = ticket_svc.list_for_customer(UUID(customer_id), limit)
        return success_response(
            [t.model_dump(mode="json") for t in tickets]
        ).model_dump(mode="json")

    raise ValueError("'tickets' type requires 'id' or 'customer_id' parameter")


def _handle_services(catalog_svc, filter):
    if filter == "active":
        services = catalog_svc.list_active()
    else:
        services = catalog_svc.list_all()

    return success_response(
        [s.model_dump(mode="json") for s in services]
    ).model_dump(mode="json")


def _handle_invoices(invoice_svc, filter, limit):
    if filter == "unpaid":
        invoices = invoice_svc.list_unpaid(limit)
    else:
        raise ValueError("'invoices' type requires 'filter' parameter (e.g. filter=unpaid)")

    return success_response(
        [i.model_dump(mode="json") for i in invoices]
    ).model_dump(mode="json")
