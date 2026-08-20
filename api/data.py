"""GET /api/data — unified read endpoint."""
from uuid import UUID

from fastapi import APIRouter, Query, Request

from api.base import success_response, ErrorCodes
from core.models import InvoiceStatus, MessageStatus


VALID_TYPES = {
    "attributes",
    "customers",
    "invoices",
    "leads",
    "messages",
    "notes",
    "quotes",
    "services",
    "tickets",
    "square_sales",
    "workspace_settings",
}


def create_data_router(services: dict) -> APIRouter:
    router = APIRouter()

    customer_svc = services["customer"]
    ticket_svc = services["ticket"]
    catalog_svc = services["catalog"]
    line_item_svc = services["line_item"]
    invoice_svc = services["invoice"]
    note_svc = services["note"]
    address_svc = services["address"]
    message_svc = services["message"]
    attribute_svc = services["attribute"]
    square_import_svc = services["square_import"]
    workspace_settings_svc = services["workspace_settings"]
    closeout_svc = services["closeout"]
    lead_svc = services["lead"]
    quote_svc = services["quote"]

    # -------------------------------------------------------------------------
    # Convenience routes (must be registered before the generic /data route)
    # -------------------------------------------------------------------------

    @router.get("/data/tickets/today")
    async def tickets_today(request: Request):
        tickets = ticket_svc.list_today()
        return success_response(
            [t.model_dump(mode="json") for t in tickets],
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.get("/data/tickets/current")
    async def tickets_current(request: Request):
        ticket = ticket_svc.get_current()
        data = ticket.model_dump(mode="json") if ticket else None
        return success_response(data, request_id=request.state.request_id).model_dump(mode="json")

    @router.get("/data/today")
    async def today_control_surface(request: Request):
        tickets = ticket_svc.list_today()
        rows = [
            _ticket_packet(
                ticket,
                customer_svc,
                address_svc,
                line_item_svc,
                catalog_svc,
                note_svc,
                message_svc,
                invoice_svc,
                attribute_svc,
                closeout_svc,
            )
            for ticket in tickets
        ]
        return success_response(rows, request_id=request.state.request_id).model_dump(mode="json")

    @router.get("/data/tickets/{ticket_id}/packet")
    async def ticket_packet(ticket_id: str, request: Request):
        ticket = ticket_svc.get_by_id(UUID(ticket_id))
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found")

        data = _ticket_packet(
            ticket,
            customer_svc,
            address_svc,
            line_item_svc,
            catalog_svc,
            note_svc,
            message_svc,
            invoice_svc,
            attribute_svc,
            closeout_svc,
        )
        return success_response(data, request_id=request.state.request_id).model_dump(mode="json")

    @router.get("/data/customers/{customer_id}/dossier")
    async def customer_dossier(customer_id: str, request: Request):
        customer = customer_svc.get_by_id(UUID(customer_id))
        if customer is None:
            raise ValueError(f"Customer {customer_id} not found")

        data = _customer_dossier(
            customer,
            address_svc,
            ticket_svc,
            invoice_svc,
            note_svc,
            message_svc,
            attribute_svc,
            square_import_svc,
        )
        return success_response(data, request_id=request.state.request_id).model_dump(mode="json")

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
        ticket_id: str | None = Query(None),
        include: str | None = Query(None),
        filter: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        cursor: str | None = Query(None),
        offset: int | None = Query(None, ge=0),
    ):
        if type is None:
            raise ValueError("'type' query parameter is required")

        if type not in VALID_TYPES:
            raise ValueError(f"Unknown type '{type}'. Valid types: {', '.join(sorted(VALID_TYPES))}")

        includes = set(include.split(",")) if include else set()

        if type == "workspace_settings":
            return success_response(
                workspace_settings_svc.get().model_dump(mode="json"),
                request_id=request.state.request_id,
            ).model_dump(mode="json")

        if type == "customers":
            return _handle_customers(
                customer_svc, address_svc, ticket_svc, invoice_svc, note_svc,
                message_svc, attribute_svc, square_import_svc, id, search, includes,
                limit, cursor, offset,
                request.state.request_id,
            )

        if type == "square_sales":
            if not customer_id:
                raise ValueError("'square_sales' type requires customer_id")
            sales = square_import_svc.list_sales_for_customer(UUID(customer_id), limit)
            return success_response(
                [sale.model_dump(mode="json") for sale in sales],
                request_id=request.state.request_id,
            ).model_dump(mode="json")

        if type == "tickets":
            return _handle_tickets(
                ticket_svc, customer_svc, address_svc, line_item_svc, catalog_svc,
                note_svc, message_svc, invoice_svc, attribute_svc, closeout_svc, id, customer_id, filter, includes, limit,
                request.state.request_id,
            )

        if type == "services":
            return _handle_services(catalog_svc, filter, request.state.request_id)

        if type == "invoices":
            return _handle_invoices(
                invoice_svc, id, customer_id, filter, limit, request.state.request_id
            )

        if type == "messages":
            return _handle_messages(
                message_svc, id, customer_id, ticket_id, filter, limit,
                request.state.request_id,
            )

        if type == "notes":
            return _handle_notes(
                note_svc, id, customer_id, ticket_id, limit, request.state.request_id
            )

        if type == "attributes":
            return _handle_attributes(
                attribute_svc, id, customer_id, request.state.request_id
            )

        if type == "leads":
            return _handle_leads(
                lead_svc, id, search, filter, limit, cursor,
                request.state.request_id,
            )

        if type == "quotes":
            return _handle_quotes(
                quote_svc, id, search, customer_id, filter, limit, cursor,
                request.state.request_id,
            )

    return router


def _handle_customers(
    customer_svc,
    address_svc,
    ticket_svc,
    invoice_svc,
    note_svc,
    message_svc,
    attribute_svc,
    square_import_svc,
    id,
    search,
    includes,
    limit,
    cursor,
    offset,
    request_id,
):
    if id:
        customer = customer_svc.get_by_id(UUID(id))
        if customer is None:
            raise ValueError(f"Customer {id} not found")

        data = customer.model_dump(mode="json")
        if "addresses" in includes:
            addresses = address_svc.list_for_customer(customer.id)
            data["addresses"] = [a.model_dump(mode="json") for a in addresses]
        if "tickets" in includes:
            tickets = ticket_svc.list_for_customer(customer.id, limit)
            data["tickets"] = [t.model_dump(mode="json") for t in tickets]
        if "invoices" in includes:
            invoices = invoice_svc.list_for_customer(customer.id, limit)
            data["invoices"] = [i.model_dump(mode="json") for i in invoices]
        if "notes" in includes:
            notes = note_svc.list_for_customer(customer.id, limit)
            # Preserve the customer's free-text `notes` string field, then surface
            # the note records under `notes` so the response key matches the
            # include key (matching the ticket packet convention). Earlier this
            # used the non-canonical `note_items` key.
            data["customer_notes"] = data["notes"]
            data["notes"] = [n.model_dump(mode="json") for n in notes]
        if "messages" in includes:
            messages = message_svc.list_for_customer(customer.id, limit)
            data["messages"] = [m.model_dump(mode="json") for m in messages]
        if "attributes" in includes:
            attributes = attribute_svc.list_for_customer(customer.id)
            data["attributes"] = [a.model_dump(mode="json") for a in attributes]
        if "square_sales" in includes:
            sales = square_import_svc.list_sales_for_customer(customer.id, limit)
            data["square_sales"] = [sale.model_dump(mode="json") for sale in sales]

        return success_response(data, request_id=request_id).model_dump(mode="json")

    if offset is not None:
        raise ValueError("Customer listing uses 'cursor'; 'offset' is not supported")
    page = customer_svc.list_page(search=search, limit=limit, cursor=cursor)
    customers = page.customers

    # Enrich with primary address (single batch query)
    if customers:
        customer_ids = [str(c.id) for c in customers]
        placeholders = ",".join("%s" for _ in customer_ids)
        rows = address_svc.postgres.execute(
            f"""
            SELECT customer_id, street FROM (
                SELECT customer_id, street,
                       ROW_NUMBER() OVER (
                           PARTITION BY customer_id
                           ORDER BY label = 'Home' DESC, created_at ASC
                       ) as rn
                FROM addresses
                WHERE customer_id IN ({placeholders})
            ) ranked WHERE rn = 1
            """,
            tuple(customer_ids),
        )
        addr_map = {str(r["customer_id"]): r["street"] for r in rows}
        for c in customers:
            c.address = addr_map.get(str(c.id))

    return success_response(
        {
            "customers": [c.model_dump(mode="json") for c in customers],
            "next_cursor": page.next_cursor,
        },
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_tickets(
    ticket_svc, customer_svc, address_svc, line_item_svc, catalog_svc, note_svc,
    message_svc, invoice_svc, attribute_svc, closeout_svc, id, customer_id, filter, includes, limit, request_id
):
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
            # Preserve the ticket's free-text `notes` string as `job_notes`,
            # then surface the note records under `notes` (canonical: matches the
            # include key). `note_items` was a redundant non-canonical alias.
            data["job_notes"] = data["notes"]
            data["notes"] = [n.model_dump(mode="json") for n in notes]
        if "messages" in includes:
            messages = message_svc.list_pending_for_ticket(ticket.id)
            data["messages"] = [m.model_dump(mode="json") for m in messages]

        return success_response(data, request_id=request_id).model_dump(mode="json")

    if customer_id:
        tickets = ticket_svc.list_for_customer(UUID(customer_id), limit)
        return success_response(
            [t.model_dump(mode="json") for t in tickets],
            request_id=request_id,
        ).model_dump(mode="json")

    if filter == "upcoming":
        tickets = ticket_svc.list_upcoming(limit)
    elif filter == "all":
        tickets = ticket_svc.list_all(limit)
    else:
        raise ValueError("'tickets' type requires 'id', 'customer_id', or filter=upcoming|all")

    return success_response(
        [
            _ticket_packet(
                ticket,
                customer_svc,
                address_svc,
                line_item_svc,
                catalog_svc,
                note_svc,
                message_svc,
                invoice_svc,
                attribute_svc,
                closeout_svc,
            )
            for ticket in tickets
        ],
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_services(catalog_svc, filter, request_id):
    if filter == "active":
        services = catalog_svc.list_active()
    else:
        services = catalog_svc.list_all()

    return success_response(
        [s.model_dump(mode="json") for s in services],
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_invoices(invoice_svc, id, customer_id, filter, limit, request_id):
    if id:
        invoice = invoice_svc.get_by_id(UUID(id))
        if invoice is None:
            raise ValueError(f"Invoice {id} not found")
        return success_response(invoice.model_dump(mode="json"), request_id=request_id).model_dump(mode="json")

    if customer_id:
        invoices = invoice_svc.list_for_customer(UUID(customer_id), limit)
    elif filter == "unpaid":
        invoices = invoice_svc.list_unpaid(limit)
    elif filter == "draft":
        invoices = invoice_svc.list_by_status(InvoiceStatus.DRAFT, limit)
    elif filter == "all":
        invoices = invoice_svc.list_all(limit)
    else:
        raise ValueError("'invoices' type requires 'id', 'customer_id', or filter=unpaid|draft|all")

    return success_response(
        [i.model_dump(mode="json") for i in invoices],
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_messages(message_svc, id, customer_id, ticket_id, filter, limit, request_id):
    if id:
        message = message_svc.get_by_id(UUID(id))
        if message is None:
            raise ValueError(f"Message {id} not found")
        return success_response(message.model_dump(mode="json"), request_id=request_id).model_dump(mode="json")

    if customer_id:
        messages = message_svc.list_for_customer(UUID(customer_id), limit)
    elif ticket_id:
        messages = message_svc.list_pending_for_ticket(UUID(ticket_id))
    elif filter == "due":
        messages = message_svc.list_pending_due(limit)
    elif filter in {"pending", "sent", "failed", "cancelled", "skipped"}:
        messages = message_svc.list_by_status(MessageStatus(filter), limit)
    else:
        raise ValueError(
            "'messages' type requires 'id', 'customer_id', 'ticket_id', "
            "or filter=due|pending|sent|failed|cancelled|skipped"
        )

    return success_response(
        [m.model_dump(mode="json") for m in messages],
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_notes(note_svc, id, customer_id, ticket_id, limit, request_id):
    if id:
        note = note_svc.get_by_id(UUID(id))
        if note is None:
            raise ValueError(f"Note {id} not found")
        return success_response(note.model_dump(mode="json"), request_id=request_id).model_dump(mode="json")

    if customer_id:
        notes = note_svc.list_for_customer(UUID(customer_id), limit)
    elif ticket_id:
        notes = note_svc.list_for_ticket(UUID(ticket_id), limit)
    else:
        raise ValueError("'notes' type requires 'id', 'customer_id', or 'ticket_id'")

    return success_response(
        [n.model_dump(mode="json") for n in notes],
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_attributes(attribute_svc, id, customer_id, request_id):
    if id:
        attribute = attribute_svc.get_by_id(UUID(id))
        if attribute is None:
            raise ValueError(f"Attribute {id} not found")
        return success_response(attribute.model_dump(mode="json"), request_id=request_id).model_dump(mode="json")

    if not customer_id:
        raise ValueError("'attributes' type requires 'id' or 'customer_id'")

    attributes = attribute_svc.list_for_customer(UUID(customer_id))
    return success_response(
        [a.model_dump(mode="json") for a in attributes],
        request_id=request_id,
    ).model_dump(mode="json")


def _customer_display_name(customer) -> str:
    if customer.business_name:
        return customer.business_name
    parts = [customer.first_name, customer.last_name]
    name = " ".join(part for part in parts if part)
    return name or "Unnamed customer"


def _customer_summary(customer) -> dict:
    data = customer.model_dump(mode="json")
    data["display_name"] = _customer_display_name(customer)
    return data


def _address_one_line(address) -> str:
    parts = [
        address.street,
        address.street2 or "",
        address.city,
        address.state,
        address.zip,
    ]
    return ", ".join(p for p in parts if p)


def _address_summary(address) -> dict:
    data = address.model_dump(mode="json")
    data["one_line"] = _address_one_line(address)
    return data


def _line_item_payloads(items, catalog_svc) -> list[dict]:
    payloads = []
    for item in items:
        data = item.model_dump(mode="json")
        service = catalog_svc.get_by_id(item.service_id)
        if service is not None:
            data["service"] = service.model_dump(mode="json")
            data["service_name"] = service.name
            data["pricing_type"] = service.pricing_type.value
        else:
            data["service"] = None
            data["service_name"] = str(item.service_id)
            data["pricing_type"] = None
        payloads.append(data)
    return payloads


def _scope_summary(line_items: list[dict]) -> str:
    if not line_items:
        return "No line items"

    labels = [
        item.get("description") or item.get("service_name") or "Line item"
        for item in line_items[:2]
    ]
    remaining = len(line_items) - len(labels)
    if remaining:
        labels.append(f"+{remaining} more")
    return ", ".join(labels)


def _ticket_clock_state(ticket) -> str:
    if ticket.clock_in_at is not None and ticket.clock_out_at is None:
        return "in_progress"
    if ticket.clock_out_at is not None:
        return "clocked_out"
    return "not_started"


def _ticket_packet(
    ticket,
    customer_svc,
    address_svc,
    line_item_svc,
    catalog_svc,
    note_svc,
    message_svc,
    invoice_svc,
    attribute_svc,
    closeout_svc,
) -> dict:
    customer = customer_svc.get_by_id(ticket.customer_id)
    if customer is None:
        raise ValueError(f"Customer {ticket.customer_id} not found")

    address = address_svc.get_by_id(ticket.address_id) if ticket.address_id else None

    items = line_item_svc.list_for_ticket(ticket.id)
    line_items = _line_item_payloads(items, catalog_svc)
    notes = note_svc.list_for_ticket(ticket.id)
    customer_notes = note_svc.list_for_customer(customer.id, limit=20)
    recent_closeouts = closeout_svc.list_for_customer(customer.id, limit=5)
    customer_addresses = address_svc.list_for_customer(customer.id)
    catalog_services = catalog_svc.list_all()
    messages = message_svc.list_pending_for_ticket(ticket.id)
    attributes = attribute_svc.list_for_customer(customer.id)
    invoices = [
        invoice
        for invoice in invoice_svc.list_for_customer(ticket.customer_id)
        if invoice.ticket_id == ticket.id
    ]

    total_price_cents = sum(item["total_price_cents"] or 0 for item in line_items)

    return {
        "ticket": ticket.model_dump(mode="json"),
        "customer": _customer_summary(customer),
        "address": _address_summary(address) if address else None,
        "addresses": [_address_summary(a) for a in customer_addresses],
        "services": [s.model_dump(mode="json") for s in catalog_services if s.is_active],
        "line_items": line_items,
        "scope_summary": _scope_summary(line_items),
        "total_price_cents": total_price_cents,
        "job_notes": ticket.notes,
        "notes": [note.model_dump(mode="json") for note in notes],
        "customer_notes": [note.model_dump(mode="json") for note in customer_notes],
        "recent_closeouts": [closeout.model_dump(mode="json") for closeout in recent_closeouts],
        "attributes": [attribute.model_dump(mode="json") for attribute in attributes],
        "pending_messages": [message.model_dump(mode="json") for message in messages],
        "pending_message_count": len(messages),
        "invoices": [invoice.model_dump(mode="json") for invoice in invoices],
        "invoice_summary": invoices[0].model_dump(mode="json") if invoices else None,
        "clock_state": _ticket_clock_state(ticket),
    }


def _customer_dossier(
    customer,
    address_svc,
    ticket_svc,
    invoice_svc,
    note_svc,
    message_svc,
    attribute_svc,
    square_import_svc,
) -> dict:
    addresses = address_svc.list_for_customer(customer.id)
    tickets = ticket_svc.list_for_customer(customer.id, 20)
    invoices = invoice_svc.list_for_customer(customer.id, 20)
    notes = note_svc.list_for_customer(customer.id, 20)
    messages = message_svc.list_for_customer(customer.id, 20)
    attributes = attribute_svc.list_for_customer(customer.id)
    square_sales = square_import_svc.list_sales_for_customer(customer.id, 20)
    sales_by_ticket = {
        sale.matched_ticket_id: sale
        for sale in square_sales
        if sale.matched_ticket_id is not None
    }
    recent_tickets = []
    for ticket in tickets:
        ticket_data = ticket.model_dump(mode="json")
        matched_sale = sales_by_ticket.get(ticket.id)
        ticket_data["square_sale"] = (
            matched_sale.model_dump(mode="json") if matched_sale else None
        )
        recent_tickets.append(ticket_data)

    open_invoices = [
        invoice
        for invoice in invoices
        if invoice.status.value in {"draft", "sent", "partial"}
    ]
    pending_messages = [
        message
        for message in messages
        if message.status.value == "pending"
    ]

    return {
        "customer": _customer_summary(customer),
        "addresses": [_address_summary(address) for address in addresses],
        "attributes": [attribute.model_dump(mode="json") for attribute in attributes],
        "square_sales": [sale.model_dump(mode="json") for sale in square_sales],
        "notes": [note.model_dump(mode="json") for note in notes],
        "recent_tickets": recent_tickets,
        "invoices": [invoice.model_dump(mode="json") for invoice in invoices],
        "open_invoices": [invoice.model_dump(mode="json") for invoice in open_invoices],
        "messages": [message.model_dump(mode="json") for message in messages],
        "pending_messages": [message.model_dump(mode="json") for message in pending_messages],
    }


def _handle_leads(lead_svc, id, search, filter, limit, cursor, request_id):
    if id:
        lead = lead_svc.get_by_id(UUID(id))
        if lead is None:
            raise ValueError(f"Lead {id} not found")
        data = lead.model_dump(mode="json")
        return success_response(data, request_id=request_id).model_dump(mode="json")

    page = lead_svc.list_page(
        status=filter,
        search=search or None,
        limit=limit,
        cursor=cursor,
    )
    return success_response(
        {
            "leads": [l.model_dump(mode="json") for l in page.leads],
            "next_cursor": page.next_cursor,
        },
        request_id=request_id,
    ).model_dump(mode="json")


def _handle_quotes(quote_svc, id, search, customer_id, filter, limit, cursor, request_id):
    if id:
        quote = quote_svc.get_by_id(UUID(id))
        if quote is None:
            raise ValueError(f"Quote {id} not found")
        data = quote.model_dump(mode="json")
        data["line_items"] = [
            li.model_dump(mode="json")
            for li in quote_svc.list_line_items(quote.id)
        ]
        return success_response(data, request_id=request_id).model_dump(mode="json")

    cid = UUID(customer_id) if customer_id else None
    page = quote_svc.list_page(
        customer_id=cid,
        status=filter,
        limit=limit,
        cursor=cursor,
    )
    # Enrich each quote with line items for the pipeline view
    enriched = []
    for q in page.quotes:
        q_dict = q.model_dump(mode="json")
        q_dict["line_items"] = [
            li.model_dump(mode="json")
            for li in quote_svc.list_line_items(q.id)
        ]
        enriched.append(q_dict)
    return success_response(
        {
            "quotes": enriched,
            "next_cursor": page.next_cursor,
        },
        request_id=request_id,
    ).model_dump(mode="json")
