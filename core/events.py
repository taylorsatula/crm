"""
Domain events for CRM.

Immutable event objects that represent state changes in the CRM domain.
Events enable loose coupling between services — a service publishes what
happened, and handlers react without the publisher knowing who's listening.

Event Categories:
- TicketEvent: Ticket lifecycle (create, clock in, complete, cancel)
- InvoiceEvent: Invoice lifecycle (send, paid)
- CustomerEvent: Customer lifecycle (create)
- NoteEvent: Note lifecycle (create)

Events carry the full domain object so handlers don't need to re-fetch state.
This prevents race conditions where persistence hasn't completed yet.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from utils.timezone import now_utc


@dataclass(frozen=True, kw_only=True)
class CRMEvent:
    """Base class for all CRM domain events."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=now_utc)


# =============================================================================
# TICKET EVENTS
# =============================================================================


@dataclass(frozen=True)
class TicketEvent(CRMEvent):
    """Events related to ticket lifecycle."""
    pass


@dataclass(frozen=True)
class TicketCreated(TicketEvent):
    """A new ticket was created in SCHEDULED status."""
    ticket: Any = None  # Ticket — using Any to avoid circular import

    @classmethod
    def create(cls, ticket: Any) -> "TicketCreated":
        return cls(ticket=ticket)


@dataclass(frozen=True)
class TicketClockIn(TicketEvent):
    """Technician clocked in to a ticket."""
    ticket: Any = None

    @classmethod
    def create(cls, ticket: Any) -> "TicketClockIn":
        return cls(ticket=ticket)


@dataclass(frozen=True)
class TicketCompleted(TicketEvent):
    """Ticket was closed/completed."""
    ticket: Any = None

    @classmethod
    def create(cls, ticket: Any) -> "TicketCompleted":
        return cls(ticket=ticket)


@dataclass(frozen=True)
class TicketCancelled(TicketEvent):
    """Ticket was cancelled."""
    ticket: Any = None

    @classmethod
    def create(cls, ticket: Any) -> "TicketCancelled":
        return cls(ticket=ticket)


# =============================================================================
# INVOICE EVENTS
# =============================================================================


@dataclass(frozen=True)
class InvoiceEvent(CRMEvent):
    """Events related to invoice lifecycle."""
    pass


@dataclass(frozen=True)
class InvoiceSent(InvoiceEvent):
    """Invoice was sent to customer."""
    invoice: Any = None

    @classmethod
    def create(cls, invoice: Any) -> "InvoiceSent":
        return cls(invoice=invoice)


@dataclass(frozen=True)
class InvoicePaid(InvoiceEvent):
    """Invoice was fully paid."""
    invoice: Any = None

    @classmethod
    def create(cls, invoice: Any) -> "InvoicePaid":
        return cls(invoice=invoice)


# =============================================================================
# CUSTOMER EVENTS
# =============================================================================


@dataclass(frozen=True)
class CustomerEvent(CRMEvent):
    """Events related to customer lifecycle."""
    pass


@dataclass(frozen=True)
class CustomerCreated(CustomerEvent):
    """A new customer was created."""
    customer: Any = None

    @classmethod
    def create(cls, customer: Any) -> "CustomerCreated":
        return cls(customer=customer)


# =============================================================================
# NOTE EVENTS
# =============================================================================


@dataclass(frozen=True)
class NoteEvent(CRMEvent):
    """Events related to note lifecycle."""
    pass


@dataclass(frozen=True)
class NoteCreated(NoteEvent):
    """A new note was created."""
    note: Any = None

    @classmethod
    def create(cls, note: Any) -> "NoteCreated":
        return cls(note=note)
