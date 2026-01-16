# Phase 3: Core Domain

**Goal**: Implement business entities, audit trail, and domain services.

**Estimated files**: 15+
**Dependencies**: Phase 0, 1, and 2 complete

---

## Prerequisites

Before starting Phase 3, ensure:

1. All previous phases complete and verified
2. Database schema for domain entities exists (see below)
3. Auth system working end-to-end

### Required Database Schema

**RLS Pattern (applied to all user-scoped tables):**
```sql
-- Enable RLS and create isolation policy
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON {table}
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);
-- Note: Omit "AND deleted_at IS NULL" for tables without soft delete
```

```sql
-- Contacts (customers) [RLS: user_id + soft delete]
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ  -- Soft delete
);

-- Addresses (service locations) [RLS: user_id only, no soft delete]
CREATE TABLE addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label TEXT,  -- "Home", "Office", etc.
    street TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Services (catalog items) [RLS: user_id + soft delete]
CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT,
    pricing_type TEXT NOT NULL,  -- 'fixed', 'flexible', 'per_unit'
    default_price DECIMAL(10,2),  -- For fixed pricing
    unit_price DECIMAL(10,2),     -- For per_unit pricing
    unit_label TEXT,              -- "screen", "window", etc.
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

-- Tickets (appointments/jobs) [RLS: user_id + soft delete]
CREATE TABLE tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    address_id UUID NOT NULL REFERENCES addresses(id),
    status TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled, in_progress, completed, cancelled
    scheduled_at TIMESTAMPTZ NOT NULL,
    scheduled_duration_minutes INT,
    clock_in_at TIMESTAMPTZ,
    clock_out_at TIMESTAMPTZ,
    actual_duration_minutes INT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

-- Line items (services on a ticket) [RLS: user_id + soft delete]
CREATE TABLE line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES services(id),
    description TEXT,  -- Can override service name
    quantity INT DEFAULT 1,
    unit_price DECIMAL(10,2),
    total_price DECIMAL(10,2) NOT NULL,
    duration_minutes INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

-- Invoices [RLS: user_id + soft delete]
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    ticket_id UUID REFERENCES tickets(id),  -- NULL for standalone invoices
    status TEXT NOT NULL DEFAULT 'draft',  -- draft, sent, paid, void
    total_amount DECIMAL(10,2) NOT NULL,
    sent_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

-- Notes (attached to contacts or tickets) [RLS: user_id + soft delete]
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID REFERENCES contacts(id),
    ticket_id UUID REFERENCES tickets(id),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT notes_has_parent CHECK (contact_id IS NOT NULL OR ticket_id IS NOT NULL)
);

-- Attributes (structured data from notes) [RLS: user_id only]
CREATE TABLE attributes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    source_note_id UUID REFERENCES notes(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(contact_id, key)  -- One value per key per contact
);

-- Audit log (NO RLS - append-only, admin-accessible)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,  -- 'create', 'update', 'delete'
    changes JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);

-- Scheduled messages [RLS: user_id only]
CREATE TABLE scheduled_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    template_name TEXT,
    custom_content TEXT,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, sent, cancelled, failed
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 3.1 core/audit.py

**Purpose**: Universal change tracking for all entities.

### Implementation

```python
from enum import Enum
from uuid import UUID, uuid4
from typing import Any
from datetime import datetime

from clients.postgres_client import PostgresClient
from utils.user_context import get_current_user_id
from utils.timezone import now_utc


class AuditAction(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class AuditLogger:
    """
    Universal audit trail for all entity changes.

    Every mutation to every entity is logged here. The audit log is:
    - Append-only (entries never modified or deleted)
    - User-attributed (who made the change)
    - Detailed (captures old and new values)
    """

    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    def log_change(
        self,
        entity_type: str,
        entity_id: UUID,
        action: AuditAction,
        changes: dict[str, Any],
        user_id: UUID | None = None
    ) -> None:
        """
        Log an entity change.

        Args:
            entity_type: Type of entity ("contact", "ticket", etc.)
            entity_id: ID of the entity
            action: The action performed
            changes: The changes made (format depends on action)
            user_id: User who made change (defaults to current context)

        Changes format by action:
        - CREATE: {"created": {full entity data}}
        - UPDATE: {"field": {"old": old_val, "new": new_val}, ...}
        - DELETE: {"deleted": {full entity data at deletion}}
        """
        from psycopg.types.json import Json

        if user_id is None:
            user_id = get_current_user_id()

        # Use admin connection since audit log doesn't have RLS
        self.postgres.execute_admin(
            """
            INSERT INTO audit_log (id, user_id, entity_type, entity_id, action, changes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                user_id,
                entity_type,
                entity_id,
                action.value,
                Json(changes),
                now_utc()
            )
        )

    def get_entity_history(
        self,
        entity_type: str,
        entity_id: UUID
    ) -> list[dict[str, Any]]:
        """
        Get full audit history for an entity.

        Returns list of audit entries, newest first.
        """
        return self.postgres.execute_admin(
            """
            SELECT id, user_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE entity_type = %s AND entity_id = %s
            ORDER BY created_at DESC
            """,
            (entity_type, entity_id)
        )

    def get_user_activity(
        self,
        user_id: UUID,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get recent activity by user."""
        return self.postgres.execute_admin(
            """
            SELECT id, user_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit)
        )


def compute_changes(
    old: dict[str, Any],
    new: dict[str, Any],
    exclude_fields: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """
    Compute changes between two entity states.

    Returns dict of {field: {"old": old_val, "new": new_val}} for changed fields.
    """
    exclude = exclude_fields or {"updated_at"}
    changes = {}

    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        if key in exclude:
            continue

        old_val = old.get(key)
        new_val = new.get(key)

        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}

    return changes
```

---

## 3.2 core/events.py

**Purpose**: Domain event definitions for loose coupling between services.

### Implementation

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4
from typing import Any

from utils.timezone import now_utc
from utils.user_context import get_current_user_id


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class for all domain events.

    Events are immutable and carry complete state to prevent
    handlers from re-fetching stale data.
    """
    event_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=get_current_user_id)
    occurred_at: datetime = field(default_factory=now_utc)


# === Ticket Events ===

@dataclass(frozen=True)
class TicketCreatedEvent(DomainEvent):
    """Published when a new ticket is scheduled."""
    ticket_id: UUID
    contact_id: UUID
    address_id: UUID
    scheduled_at: datetime


@dataclass(frozen=True)
class TicketCompletedEvent(DomainEvent):
    """
    Published when ticket close-out is finalized.

    Carries full state needed by handlers - they don't re-fetch.
    """
    ticket_id: UUID
    contact_id: UUID
    notes: str | None
    confirmed_attributes: dict[str, Any]
    next_service_action: str  # "schedule_now", "reach_out", "no_followup"
    reach_out_months: int | None


# === Contact Events ===

@dataclass(frozen=True)
class ContactCreatedEvent(DomainEvent):
    """Published when a new contact is created."""
    contact_id: UUID
    name: str
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class ContactUpdatedEvent(DomainEvent):
    """Published when contact data is modified."""
    contact_id: UUID
    changes: dict[str, dict[str, Any]]  # {field: {old, new}}


# === Invoice Events ===

@dataclass(frozen=True)
class InvoiceCreatedEvent(DomainEvent):
    """Published when an invoice is generated."""
    invoice_id: UUID
    contact_id: UUID
    ticket_id: UUID | None
    total_amount: float


@dataclass(frozen=True)
class InvoiceSentEvent(DomainEvent):
    """Published when invoice is emailed to customer."""
    invoice_id: UUID
    contact_id: UUID
    payment_link: str | None


@dataclass(frozen=True)
class InvoicePaidEvent(DomainEvent):
    """Published when payment is confirmed (from Stripe webhook)."""
    invoice_id: UUID
    contact_id: UUID
    amount_paid: float


# === Lead Events ===

@dataclass(frozen=True)
class LeadCreatedEvent(DomainEvent):
    """Published when a lead is captured."""
    lead_id: UUID
    raw_notes: str


@dataclass(frozen=True)
class LeadConvertedEvent(DomainEvent):
    """Published when a lead is converted to a customer."""
    lead_id: UUID
    contact_id: UUID


# === Message Events ===

@dataclass(frozen=True)
class ScheduledMessageCreatedEvent(DomainEvent):
    """Published when outreach is scheduled."""
    message_id: UUID
    contact_id: UUID
    scheduled_for: datetime


@dataclass(frozen=True)
class ScheduledMessageSentEvent(DomainEvent):
    """Published when scheduled message is delivered."""
    message_id: UUID
    contact_id: UUID
```

---

## 3.3 core/event_bus.py

**Purpose**: Synchronous event bus for publishing and handling domain events.

### Implementation

```python
import logging
from typing import Callable, Any

from core.events import DomainEvent

logger = logging.getLogger(__name__)


class EventBus:
    """
    Synchronous event bus for domain events.

    Events execute handlers immediately in the publishing thread.
    No async, no queues - when publish() returns, all handlers have completed.

    Handler failures are logged but don't cascade - a search index failure
    shouldn't prevent ticket close-out from completing.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[DomainEvent], None]]] = {}

    def subscribe(self, event_type: str, callback: Callable[[DomainEvent], None]) -> None:
        """
        Register handler for event type.

        Args:
            event_type: Event class name (e.g., "TicketCompletedEvent")
            callback: Function that accepts the event
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed {callback.__qualname__} to {event_type}")

    def publish(self, event: DomainEvent) -> None:
        """
        Publish event to all subscribers.

        Executes handlers synchronously. Exceptions are logged but
        don't stop other handlers from executing.
        """
        event_type = event.__class__.__name__
        handlers = self._subscribers.get(event_type, [])

        logger.debug(f"Publishing {event_type} to {len(handlers)} handlers")

        for callback in handlers:
            try:
                callback(event)
            except Exception as e:
                # Log but don't cascade - other handlers should still run
                logger.error(
                    f"Handler {callback.__qualname__} failed for {event_type}: {e}",
                    exc_info=True
                )

    def subscriber_count(self, event_type: str) -> int:
        """Get number of subscribers for an event type."""
        return len(self._subscribers.get(event_type, []))
```

---

## 3.4 core/handlers/

**Purpose**: Event handlers that react to domain events.

### 3.4.1 core/handlers/scheduled_message_handler.py

```python
import logging
from uuid import uuid4
from datetime import timedelta

from core.events import TicketCompletedEvent
from core.event_bus import EventBus
from clients.postgres_client import PostgresClient
from utils.timezone import now_utc
from utils.user_context import get_current_user_id

logger = logging.getLogger(__name__)


class ScheduledMessageHandler:
    """
    Creates scheduled messages based on ticket close-out choices.

    Listens to TicketCompletedEvent and creates reach-out messages
    when technician selects "reach out in X months".
    """

    def __init__(self, event_bus: EventBus, postgres: PostgresClient):
        self.postgres = postgres
        # Self-register with event bus
        event_bus.subscribe("TicketCompletedEvent", self.handle_ticket_completed)
        logger.info("ScheduledMessageHandler registered")

    def handle_ticket_completed(self, event: TicketCompletedEvent) -> None:
        """Create scheduled message if reach-out was requested."""
        if event.next_service_action != "reach_out" or not event.reach_out_months:
            return

        now = now_utc()
        scheduled_for = now + timedelta(days=event.reach_out_months * 30)

        self.postgres.execute(
            """
            INSERT INTO scheduled_messages
                (id, user_id, contact_id, template_name, scheduled_for, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s)
            """,
            (uuid4(), event.user_id, event.contact_id, "service_reminder", scheduled_for, now)
        )

        logger.info(
            f"Scheduled reach-out for contact {event.contact_id} "
            f"in {event.reach_out_months} months"
        )
```

### 3.4.2 core/handlers/attribute_persistence_handler.py

```python
import logging
from uuid import uuid4

from psycopg.types.json import Json

from core.events import TicketCompletedEvent
from core.event_bus import EventBus
from clients.postgres_client import PostgresClient
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


class AttributePersistenceHandler:
    """
    Persists confirmed attributes to contact record.

    The extraction itself happens during close-out wizard with human validation.
    This handler just persists the already-confirmed attributes.
    """

    def __init__(self, event_bus: EventBus, postgres: PostgresClient):
        self.postgres = postgres
        event_bus.subscribe("TicketCompletedEvent", self.handle_ticket_completed)
        logger.info("AttributePersistenceHandler registered")

    def handle_ticket_completed(self, event: TicketCompletedEvent) -> None:
        """Persist confirmed attributes to contact."""
        if not event.confirmed_attributes:
            return

        now = now_utc()

        for key, value in event.confirmed_attributes.items():
            self.postgres.execute(
                """
                INSERT INTO attributes (id, user_id, contact_id, key, value, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (contact_id, key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (uuid4(), event.user_id, event.contact_id, key, Json(value), now, now)
            )

        logger.info(
            f"Persisted {len(event.confirmed_attributes)} attributes "
            f"for contact {event.contact_id}"
        )
```

---

## 3.5 core/models/

**Purpose**: Pydantic models for all domain entities.

### Pattern (applied to each entity)

```python
# core/models/contact.py
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime


class ContactCreate(BaseModel):
    """Data required to create a contact."""
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    notes: str | None = None


class ContactUpdate(BaseModel):
    """Data that can be updated on a contact. All fields optional."""
    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    notes: str | None = None


class Contact(BaseModel):
    """Full contact entity as stored."""
    id: UUID
    user_id: UUID
    name: str
    email: EmailStr | None
    phone: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContactWithAddresses(Contact):
    """Contact with expanded addresses."""
    addresses: list["Address"] = []
```

### Models to Create

| File | Models |
|------|--------|
| `contact.py` | Contact, ContactCreate, ContactUpdate, ContactWithAddresses |
| `address.py` | Address, AddressCreate, AddressUpdate |
| `service.py` | Service, ServiceCreate, ServiceUpdate, PricingType (Enum) |
| `ticket.py` | Ticket, TicketCreate, TicketUpdate, TicketStatus (Enum), TicketWithDetails |
| `line_item.py` | LineItem, LineItemCreate, LineItemUpdate |
| `invoice.py` | Invoice, InvoiceCreate, InvoiceStatus (Enum) |
| `note.py` | Note, NoteCreate |
| `attribute.py` | Attribute, AttributeCreate, ExtractedAttributes |
| `scheduled_message.py` | ScheduledMessage, ScheduledMessageCreate, MessageStatus (Enum) |

### Enums

```python
# core/models/ticket.py
from enum import Enum

class TicketStatus(Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PricingType(Enum):
    FIXED = "fixed"        # Set price regardless of scope
    FLEXIBLE = "flexible"  # Price determined at ticket creation
    PER_UNIT = "per_unit"  # Quantity × unit price


class InvoiceStatus(Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    VOID = "void"


class MessageStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

---

## 3.6 core/services/contact_service.py

**Purpose**: Business logic for contact management.

### Implementation

```python
from uuid import UUID, uuid4
from typing import Any

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models.contact import Contact, ContactCreate, ContactUpdate, ContactWithAddresses
from core.models.address import Address
from utils.user_context import get_current_user_id
from utils.timezone import now_utc


class ContactService:
    """
    Contact (customer) management.

    All operations automatically scoped to current user via RLS.
    All mutations logged to audit trail.
    """

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: ContactCreate) -> Contact:
        """Create new contact."""
        contact_id = uuid4()
        user_id = get_current_user_id()
        now = now_utc()

        self.postgres.execute(
            """
            INSERT INTO contacts (id, user_id, name, email, phone, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (contact_id, user_id, data.name, data.email, data.phone, data.notes, now, now)
        )

        contact = self.get_by_id(contact_id)

        self.audit.log_change(
            entity_type="contact",
            entity_id=contact_id,
            action=AuditAction.CREATE,
            changes={"created": contact.model_dump(mode="json")}
        )

        return contact

    def get_by_id(self, contact_id: UUID) -> Contact | None:
        """
        Get contact by ID.

        RLS ensures user can only see their own contacts.
        """
        row = self.postgres.execute_one(
            "SELECT * FROM contacts WHERE id = %s",
            (contact_id,)
        )
        return Contact(**row) if row else None

    def get_with_addresses(self, contact_id: UUID) -> ContactWithAddresses | None:
        """Get contact with addresses expanded."""
        contact = self.get_by_id(contact_id)
        if not contact:
            return None

        address_rows = self.postgres.execute(
            "SELECT * FROM addresses WHERE contact_id = %s ORDER BY created_at",
            (contact_id,)
        )
        addresses = [Address(**row) for row in address_rows]

        return ContactWithAddresses(
            **contact.model_dump(),
            addresses=addresses
        )

    def update(self, contact_id: UUID, data: ContactUpdate) -> Contact:
        """
        Update contact fields.

        Only updates fields that are explicitly set (not None).
        """
        # Get current state for audit
        old = self.get_by_id(contact_id)
        if not old:
            raise ValueError(f"Contact {contact_id} not found")

        # Build update from provided fields
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return old  # Nothing to update

        # Add updated_at
        update_data["updated_at"] = now_utc()

        # Build SQL
        set_clauses = [f"{k} = %s" for k in update_data.keys()]
        values = list(update_data.values()) + [contact_id]

        self.postgres.execute(
            f"UPDATE contacts SET {', '.join(set_clauses)} WHERE id = %s",
            tuple(values)
        )

        # Get new state and compute changes
        new = self.get_by_id(contact_id)
        changes = compute_changes(old.model_dump(mode="json"), new.model_dump(mode="json"))

        if changes:
            self.audit.log_change(
                entity_type="contact",
                entity_id=contact_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return new

    def delete(self, contact_id: UUID) -> None:
        """
        Soft delete contact.

        Sets deleted_at, making it invisible via RLS.
        """
        old = self.get_by_id(contact_id)
        if not old:
            raise ValueError(f"Contact {contact_id} not found")

        self.postgres.execute(
            "UPDATE contacts SET deleted_at = %s, updated_at = %s WHERE id = %s",
            (now_utc(), now_utc(), contact_id)
        )

        self.audit.log_change(
            entity_type="contact",
            entity_id=contact_id,
            action=AuditAction.DELETE,
            changes={"deleted": old.model_dump(mode="json")}
        )

    def list(self, limit: int = 100) -> list[Contact]:
        """List contacts ordered by creation date."""
        query = "SELECT * FROM contacts ORDER BY created_at DESC LIMIT %s"
        results = self.postgres.execute(query, (limit,))
        return [Contact(**r) for r in results]

    def search(self, query: str, limit: int = 100) -> list[Contact]:
        """
        Search contacts by name, email, phone.

        Uses ILIKE for simple substring matching.
        TODO: Upgrade to full-text search or trigram matching.
        """
        search_pattern = f"%{query}%"
        sql = """
            SELECT * FROM contacts
            WHERE (name ILIKE %s OR email ILIKE %s OR phone ILIKE %s)
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = self.postgres.execute(sql, (search_pattern, search_pattern, search_pattern, limit))
        return [Contact(**r) for r in results]
```

---

## 3.7 core/services/ticket_service.py

**Purpose**: Ticket lifecycle management including close-out flow.

### Implementation

```python
from uuid import UUID, uuid4
from datetime import datetime
from typing import Any
from enum import Enum

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.event_bus import EventBus
from core.events import TicketCreatedEvent, TicketCompletedEvent
from core.models.ticket import (
    Ticket, TicketCreate, TicketUpdate, TicketStatus, TicketWithDetails
)
from core.models.line_item import LineItem, LineItemCreate, LineItemUpdate
from core.extraction import AttributeExtractor, ExtractedAttributes
from utils.user_context import get_current_user_id
from utils.timezone import now_utc


class NextServiceAction(Enum):
    """Options for next service scheduling during close-out."""
    SCHEDULE_NOW = "schedule_now"
    REACH_OUT = "reach_out"
    NO_FOLLOWUP = "no_followup"


class CloseOutResult:
    """Result of close-out flow, including extracted attributes for review."""
    def __init__(
        self,
        ticket: Ticket,
        extracted_attributes: ExtractedAttributes | None,
        scheduled_message_id: UUID | None = None
    ):
        self.ticket = ticket
        self.extracted_attributes = extracted_attributes
        self.scheduled_message_id = scheduled_message_id


class TicketService:
    """
    Ticket (appointment/job) management.

    Handles full lifecycle:
    - Creation and scheduling
    - Clock in/out
    - Line item management
    - Close-out flow with attribute extraction

    Publishes events for loose coupling:
    - TicketCreatedEvent on create()
    - TicketCompletedEvent on finalize_close_out()
    """

    def __init__(
        self,
        postgres: PostgresClient,
        audit: AuditLogger,
        extractor: AttributeExtractor,
        event_bus: EventBus
    ):
        self.postgres = postgres
        self.audit = audit
        self.extractor = extractor
        self.event_bus = event_bus

    def create(self, data: TicketCreate) -> Ticket:
        """Create new ticket."""
        ticket_id = uuid4()
        user_id = get_current_user_id()
        now = now_utc()

        self.postgres.execute(
            """
            INSERT INTO tickets
                (id, user_id, contact_id, address_id, status, scheduled_at,
                 scheduled_duration_minutes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ticket_id, user_id, data.contact_id, data.address_id,
                TicketStatus.SCHEDULED.value, data.scheduled_at,
                data.scheduled_duration_minutes, now, now
            )
        )

        ticket = self.get_by_id(ticket_id)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.CREATE,
            changes={"created": ticket.model_dump(mode="json")}
        )

        # Publish event for handlers
        self.event_bus.publish(TicketCreatedEvent(
            ticket_id=ticket_id,
            contact_id=data.contact_id,
            address_id=data.address_id,
            scheduled_at=data.scheduled_at
        ))

        return ticket

    def get_by_id(self, ticket_id: UUID) -> Ticket | None:
        """Get ticket by ID."""
        row = self.postgres.execute_one(
            "SELECT * FROM tickets WHERE id = %s",
            (ticket_id,)
        )
        return Ticket(**row) if row else None

    def clock_in(self, ticket_id: UUID) -> Ticket:
        """Record technician clock-in."""
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.status != TicketStatus.SCHEDULED:
            raise ValueError(f"Cannot clock in: ticket is {ticket.status.value}")

        if ticket.clock_in_at:
            raise ValueError("Already clocked in")

        now = now_utc()

        self.postgres.execute(
            """
            UPDATE tickets
            SET clock_in_at = %s, status = %s, updated_at = %s
            WHERE id = %s
            """,
            (now, TicketStatus.IN_PROGRESS.value, now, ticket_id)
        )

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "clock_in_at": {"old": None, "new": now.isoformat()},
                "status": {"old": ticket.status.value, "new": TicketStatus.IN_PROGRESS.value}
            }
        )

        return self.get_by_id(ticket_id)

    def clock_out(self, ticket_id: UUID) -> Ticket:
        """Record technician clock-out."""
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if not ticket.clock_in_at:
            raise ValueError("Cannot clock out: not clocked in")

        if ticket.clock_out_at:
            raise ValueError("Already clocked out")

        now = now_utc()
        duration = int((now - ticket.clock_in_at).total_seconds() / 60)

        self.postgres.execute(
            """
            UPDATE tickets
            SET clock_out_at = %s, actual_duration_minutes = %s, updated_at = %s
            WHERE id = %s
            """,
            (now, duration, now, ticket_id)
        )

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "clock_out_at": {"old": None, "new": now.isoformat()},
                "actual_duration_minutes": {"old": None, "new": duration}
            }
        )

        return self.get_by_id(ticket_id)

    def add_line_item(self, ticket_id: UUID, data: LineItemCreate) -> LineItem:
        """Add line item to ticket."""
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.closed_at:
            raise ValueError("Cannot modify closed ticket")

        line_item_id = uuid4()
        user_id = get_current_user_id()
        now = now_utc()

        # Calculate total price
        total = data.total_price
        if total is None and data.quantity and data.unit_price:
            total = data.quantity * data.unit_price

        self.postgres.execute(
            """
            INSERT INTO line_items
                (id, user_id, ticket_id, service_id, description,
                 quantity, unit_price, total_price, duration_minutes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                line_item_id, user_id, ticket_id, data.service_id,
                data.description, data.quantity, data.unit_price,
                total, data.duration_minutes, now, now
            )
        )

        row = self.postgres.execute_one(
            "SELECT * FROM line_items WHERE id = %s",
            (line_item_id,)
        )

        self.audit.log_change(
            entity_type="line_item",
            entity_id=line_item_id,
            action=AuditAction.CREATE,
            changes={"created": row}
        )

        return LineItem(**row)

    def initiate_close_out(
        self,
        ticket_id: UUID,
        confirmed_duration_minutes: int,
        notes: str | None
    ) -> CloseOutResult:
        """
        Begin close-out flow.

        This is step 1: process notes through LLM and return extracted
        attributes for technician review. Does NOT finalize the ticket.

        Args:
            ticket_id: Ticket to close
            confirmed_duration_minutes: Technician-confirmed duration
            notes: Free-form notes to process

        Returns:
            CloseOutResult with extracted attributes for review
        """
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.closed_at:
            raise ValueError("Ticket already closed")

        # Extract attributes from notes if provided
        extracted = None
        if notes:
            extracted = self.extractor.extract_attributes(notes)

        # Update ticket with notes and duration (but don't close yet)
        now = now_utc()
        self.postgres.execute(
            """
            UPDATE tickets
            SET notes = %s, actual_duration_minutes = %s, updated_at = %s
            WHERE id = %s
            """,
            (notes, confirmed_duration_minutes, now, ticket_id)
        )

        return CloseOutResult(
            ticket=self.get_by_id(ticket_id),
            extracted_attributes=extracted
        )

    def finalize_close_out(
        self,
        ticket_id: UUID,
        confirmed_attributes: dict[str, Any],
        next_service: NextServiceAction,
        reach_out_months: int | None = None
    ) -> Ticket:
        """
        Finalize close-out after technician confirms extracted attributes.

        This is step 2: close ticket and publish TicketCompletedEvent.
        Event handlers handle the downstream work:
        - AttributePersistenceHandler saves confirmed attributes
        - ScheduledMessageHandler creates reach-out messages

        Args:
            ticket_id: Ticket to close
            confirmed_attributes: Technician-confirmed attributes to save
            next_service: Follow-up action
            reach_out_months: Months until reach-out (if next_service is REACH_OUT)
        """
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.closed_at:
            raise ValueError("Ticket already closed")

        now = now_utc()

        # Close the ticket (now immutable)
        self.postgres.execute(
            """
            UPDATE tickets
            SET status = %s, closed_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (TicketStatus.COMPLETED.value, now, now, ticket_id)
        )

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"old": ticket.status.value, "new": TicketStatus.COMPLETED.value},
                "closed_at": {"old": None, "new": now.isoformat()}
            }
        )

        # Publish event - handlers do the downstream work
        # (attribute persistence, scheduled messages, etc.)
        self.event_bus.publish(TicketCompletedEvent(
            ticket_id=ticket_id,
            contact_id=ticket.contact_id,
            notes=ticket.notes,
            confirmed_attributes=confirmed_attributes,
            next_service_action=next_service.value,
            reach_out_months=reach_out_months
        ))

        return self.get_by_id(ticket_id)
```

---

## 3.8 core/extraction.py

**Purpose**: LLM-powered attribute extraction from notes.

### Implementation

```python
import json
import logging
from typing import Any
from pydantic import BaseModel

from clients.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ExtractedAttributes(BaseModel):
    """Attributes extracted from technician notes."""
    attributes: dict[str, Any]
    raw_response: str  # For debugging
    thinking: str | None = None  # Model's reasoning (from extended thinking)


class AttributeExtractor:
    """
    Extract structured attributes from free-form technician notes.

    Uses Anthropic LLM with extended thinking to identify entities and facts
    that should become queryable attributes on the customer record.
    """

    SYSTEM_PROMPT = """You are an assistant that extracts structured information from service technician notes.

Given notes about a customer service visit, extract relevant attributes that would be useful for future visits.

Categories to look for:
- customer_demographic: age indicators (elderly, young family, etc.)
- pet: any pets mentioned (type, name if given)
- property_notes: important property details (gate codes, access instructions, hazards)
- equipment_needed: special equipment requirements
- service_preferences: customer preferences about timing, methods, etc.
- property_details: physical property characteristics

Output ONLY valid JSON with extracted attributes. Only include attributes you're confident about.
Use snake_case keys. Values should be strings or simple objects.

Example input: "Elderly woman, very nice. Dog named Biscuit, keep gate closed. Complex sill on 2nd story, brought extension ladder."

Example output:
{
  "customer_demographic": "elderly",
  "pet": {"type": "dog", "name": "Biscuit"},
  "property_notes": "keep gate closed",
  "equipment_needed": "extension ladder",
  "property_details": "complex 2nd story sill"
}
"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def extract_attributes(self, notes: str) -> ExtractedAttributes:
        """
        Extract attributes from technician notes.

        This is called synchronously during close-out so the
        technician can review extracted attributes before confirming.

        Uses extended thinking (default in LLMClient) to let the model
        reason through what attributes to extract.
        """
        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract attributes from these notes:\n\n{notes}"}
            ],
            thinking=True,  # Enable extended thinking for better extraction
            thinking_budget=512,  # Modest budget for this task
            max_tokens=1024
        )

        # Parse JSON from response
        try:
            # Try to extract JSON from the response
            content = response.content.strip()
            # Handle case where model wraps in markdown code block
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            attributes = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction response as JSON: {e}")
            attributes = {}

        return ExtractedAttributes(
            attributes=attributes,
            raw_response=response.content,
            thinking=response.thinking  # Include model's reasoning for debugging
        )
```

---

## 3.9 Additional Services

Create similar services for remaining entities following the patterns above:

| Service | Key Methods |
|---------|-------------|
| `address_service.py` | create, get_by_id, update, delete, list_for_contact |
| `catalog_service.py` | create_service, update_service, delete_service, list_services, get_by_id |
| `invoice_service.py` | create_from_ticket, create_standalone, send, mark_paid, list |
| `note_service.py` | create, list_for_contact, list_for_ticket |
| `attribute_service.py` | set_attribute, get_attributes, search_by_attribute |
| `message_service.py` | schedule, cancel, list_pending, mark_sent |

---

## Phase 3 Verification Checklist

Before proceeding to Phase 4:

### Unit Tests

- [ ] `pytest tests/core/test_audit.py` - all tests pass
- [ ] `pytest tests/core/test_events.py` - all tests pass
- [ ] `pytest tests/core/test_event_bus.py` - all tests pass
- [ ] `pytest tests/core/services/test_contact_service.py` - all tests pass
- [ ] `pytest tests/core/services/test_ticket_service.py` - all tests pass
- [ ] `pytest tests/core/handlers/test_scheduled_message_handler.py` - all tests pass
- [ ] `pytest tests/core/handlers/test_attribute_persistence_handler.py` - all tests pass

### Integration Tests

- [ ] Can create contact → create address → create ticket flow
- [ ] Clock in/out updates ticket correctly
- [ ] Line items can be added to tickets
- [ ] Close-out flow extracts attributes via LLM
- [ ] Closed tickets cannot be modified
- [ ] Audit trail captures all changes
- [ ] RLS prevents cross-user data access

### Event System Tests

- [ ] TicketCreatedEvent published on ticket creation
- [ ] TicketCompletedEvent published on close-out
- [ ] ScheduledMessageHandler creates reach-out message when requested
- [ ] AttributePersistenceHandler saves confirmed attributes
- [ ] Handler failures don't cascade (other handlers still run)

### Data Integrity

- [ ] Soft-deleted records don't appear in normal queries
- [ ] Audit log entries are created for all mutations
- [ ] Foreign key relationships enforced

---

## Next Phase

Proceed to [Phase 4: API Routes](./PHASE_4_API_ROUTES.md)
