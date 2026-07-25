"""Core domain models."""

from core.models.customer import Customer, CustomerCreate, CustomerUpdate
from core.models.address import Address, AddressCreate, AddressUpdate
from core.models.service import Service, ServiceCreate, ServiceUpdate, PricingType
from core.models.ticket import Ticket, TicketCreate, TicketUpdate, TicketStatus, ConfirmationStatus
from core.models.line_item import LineItem, LineItemCreate, LineItemUpdate
from core.models.square_import import (
    SquareImportBatchRequest,
    SquareImportBatchResult,
    SquareSale,
    SquareSaleLine,
)
from core.models.invoice import Invoice, InvoiceCreate, InvoiceStatus
from core.models.note import Note, NoteCreate
from core.models.attribute import Attribute, AttributeCreate, ExtractedAttributes
from core.models.scheduled_message import ScheduledMessage, ScheduledMessageCreate, MessageStatus, MessageType
from core.models.lead import Lead, LeadCreate, LeadUpdate, LeadStatus, LeadSource, LeadUrgency
from core.models.workspace_settings import WorkspaceSettings, WorkspaceSettingsUpdate
from core.models.booking import (
    BookingAddressCreate,
    BookingTicketCreate,
    NewCustomerJobBooking,
    NewCustomerJobBookingCreate,
)
from core.models.closeout import (
    CloseoutRequest,
    CustomerCapture,
    NextServiceDisposition,
    TicketCloseout,
)
from core.models.quote import (
    Quote,
    QuoteCreate,
    QuoteUpdate,
    QuoteStatus,
    QuoteLineItem,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QUOTE_VALID_TRANSITIONS,
)

__all__ = [
    # Customer
    "Customer", "CustomerCreate", "CustomerUpdate",
    # Address
    "Address", "AddressCreate", "AddressUpdate",
    # Service
    "Service", "ServiceCreate", "ServiceUpdate", "PricingType",
    # Ticket
    "Ticket", "TicketCreate", "TicketUpdate", "TicketStatus", "ConfirmationStatus",
    # LineItem
    "LineItem", "LineItemCreate", "LineItemUpdate",
    "SquareImportBatchRequest", "SquareImportBatchResult", "SquareSale", "SquareSaleLine",
    # Invoice
    "Invoice", "InvoiceCreate", "InvoiceStatus",
    # Note
    "Note", "NoteCreate",
    # Attribute
    "Attribute", "AttributeCreate", "ExtractedAttributes",
    # ScheduledMessage
    "ScheduledMessage", "ScheduledMessageCreate", "MessageStatus", "MessageType",
    # Lead
    "Lead", "LeadCreate", "LeadUpdate", "LeadStatus", "LeadSource", "LeadUrgency",
    # Workspace settings
    "WorkspaceSettings", "WorkspaceSettingsUpdate",
    # Booking workflow
    "BookingAddressCreate",
    "BookingTicketCreate",
    "NewCustomerJobBooking",
    "NewCustomerJobBookingCreate",
    # Structured closeout
    "CloseoutRequest", "CustomerCapture", "NextServiceDisposition", "TicketCloseout",
    # Quote
    "Quote", "QuoteCreate", "QuoteUpdate", "QuoteStatus",
    "QuoteLineItem", "QuoteLineItemCreate", "QuoteLineItemUpdate",
    "QUOTE_VALID_TRANSITIONS",
]
