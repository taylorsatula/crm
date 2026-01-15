"""Core domain models."""

from core.models.customer import Customer, CustomerCreate, CustomerUpdate
from core.models.address import Address, AddressCreate, AddressUpdate
from core.models.service import Service, ServiceCreate, ServiceUpdate, PricingType
from core.models.ticket import Ticket, TicketCreate, TicketUpdate, TicketStatus, ConfirmationStatus
from core.models.line_item import LineItem, LineItemCreate, LineItemUpdate
from core.models.invoice import Invoice, InvoiceCreate, InvoiceStatus
from core.models.note import Note, NoteCreate
from core.models.attribute import Attribute, AttributeCreate, ExtractedAttributes
from core.models.scheduled_message import ScheduledMessage, ScheduledMessageCreate, MessageStatus, MessageType
from core.models.lead import Lead, LeadCreate, LeadUpdate, LeadStatus, LeadSource, LeadUrgency

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
]
