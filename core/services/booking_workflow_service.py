"""Canonical multi-entity workflows for booking CRM work."""

from clients.postgres_client import PostgresClient
from core.models import (
    AddressCreate,
    NewCustomerJobBooking,
    NewCustomerJobBookingCreate,
    TicketCreate,
)
from core.services.address_service import AddressService
from core.services.customer_service import CustomerService
from core.services.line_item_service import LineItemService
from core.services.ticket_service import TicketService


class BookingWorkflowService:
    """Compose existing domain services without duplicating their rules."""

    def __init__(
        self,
        postgres: PostgresClient,
        customer_service: CustomerService,
        address_service: AddressService,
        ticket_service: TicketService,
        line_item_service: LineItemService,
    ) -> None:
        self.postgres = postgres
        self.customer_service = customer_service
        self.address_service = address_service
        self.ticket_service = ticket_service
        self.line_item_service = line_item_service

    def book_new_customer_job(
        self,
        data: NewCustomerJobBookingCreate,
    ) -> NewCustomerJobBooking:
        """Atomically create a new customer and fully scoped scheduled job."""
        with self.postgres.transaction():
            customer = self.customer_service.create(data.customer)
            address = self.address_service.create(AddressCreate(
                customer_id=customer.id,
                is_primary=True,
                **data.address.model_dump(),
            ))
            ticket = self.ticket_service.create(TicketCreate(
                customer_id=customer.id,
                address_id=address.id,
                **data.ticket.model_dump(),
            ))
            line_items = [
                self.line_item_service.create(ticket.id, line_item)
                for line_item in data.line_items
            ]

        return NewCustomerJobBooking(
            customer=customer,
            address=address,
            ticket=ticket,
            line_items=line_items,
        )
