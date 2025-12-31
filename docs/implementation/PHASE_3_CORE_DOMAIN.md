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

```sql
-- Contacts (customers)
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

ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON contacts
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Addresses (service locations)
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

ALTER TABLE addresses ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON addresses
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid);

-- Services (catalog items)
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

ALTER TABLE services ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON services
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Tickets (appointments/jobs)
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

ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON tickets
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Line items (services on a ticket)
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

ALTER TABLE line_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON line_items
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Invoices
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

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON invoices
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Notes (attached to contacts or tickets)
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

ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON notes
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid AND deleted_at IS NULL);

-- Attributes (structured data derived from notes)
CREATE TABLE attributes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    source_note_id UUID REFERENCES notes(id),  -- Which note this came from
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(contact_id, key)  -- One value per key per contact
);

ALTER TABLE attributes ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON attributes
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid);

-- Audit log (universal change tracking)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,  -- 'create', 'update', 'delete'
    changes JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- No RLS on audit_log - it's append-only and admin-accessible
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);

-- Scheduled messages
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

ALTER TABLE scheduled_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON scheduled_messages
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid);
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

## 3.2 utils/pagination.py

**Purpose**: Cursor-based pagination utilities.

### Implementation

```python
import base64
import json
from uuid import UUID
from datetime import datetime
from typing import Any, TypeVar, Generic
from pydantic import BaseModel


class Cursor(BaseModel):
    """
    Pagination cursor encoding a position in a result set.

    The cursor encodes the sort key(s) of the last item returned.
    Typically this is just the ID, but can include created_at for
    time-sorted results.
    """
    id: str
    created_at: str | None = None

    def encode(self) -> str:
        """Encode cursor as URL-safe string."""
        data = self.model_dump(exclude_none=True)
        json_str = json.dumps(data, sort_keys=True)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @classmethod
    def decode(cls, encoded: str) -> "Cursor":
        """Decode cursor from URL-safe string."""
        try:
            json_str = base64.urlsafe_b64decode(encoded.encode()).decode()
            data = json.loads(json_str)
            return cls(**data)
        except Exception as e:
            raise ValueError(f"Invalid cursor: {e}")


T = TypeVar("T")


class PaginatedResult(BaseModel, Generic[T]):
    """
    Result of a paginated query.

    Includes items and cursor for next page.
    """
    items: list[Any]  # Would be list[T] but Pydantic generics are tricky
    next_cursor: str | None
    has_more: bool

    class Config:
        arbitrary_types_allowed = True


def build_cursor_query(
    base_query: str,
    cursor: Cursor | None,
    sort_column: str = "id",
    sort_direction: str = "ASC"
) -> tuple[str, list[Any]]:
    """
    Build a cursor-paginated query.

    Args:
        base_query: Base SELECT query (without ORDER BY or LIMIT)
        cursor: Cursor from previous page (None for first page)
        sort_column: Column to sort by
        sort_direction: ASC or DESC

    Returns:
        (query_with_pagination, params_to_append)
    """
    params = []
    where_clause = ""

    if cursor:
        # Add cursor condition
        operator = ">" if sort_direction.upper() == "ASC" else "<"
        where_clause = f" AND {sort_column} {operator} %s"
        params.append(cursor.id)

    order = f"ORDER BY {sort_column} {sort_direction}"

    # Check if query already has WHERE
    if " WHERE " in base_query.upper():
        query = f"{base_query}{where_clause} {order}"
    else:
        if where_clause:
            # Remove leading AND
            where_clause = "WHERE " + where_clause[5:]
        query = f"{base_query} {where_clause} {order}"

    return query, params


def create_next_cursor(
    items: list[dict[str, Any]],
    limit: int,
    sort_column: str = "id"
) -> str | None:
    """
    Create cursor for next page if there are more results.

    Call with limit + 1 items; if you got limit + 1, there's a next page.
    """
    if len(items) <= limit:
        return None

    # Get the last item that will actually be returned (index limit - 1)
    last_item = items[limit - 1]

    cursor = Cursor(
        id=str(last_item[sort_column]),
        created_at=last_item.get("created_at", "").isoformat() if last_item.get("created_at") else None
    )

    return cursor.encode()
```

### Usage Pattern

```python
def list_contacts(
    self,
    limit: int = 20,
    cursor: str | None = None
) -> PaginatedResult:
    """List contacts with cursor pagination."""

    # Decode cursor if provided
    cursor_obj = Cursor.decode(cursor) if cursor else None

    # Build query - fetch one extra to detect if there's more
    base_query = "SELECT * FROM contacts"
    query, params = build_cursor_query(base_query, cursor_obj)
    query += f" LIMIT %s"
    params.append(limit + 1)

    results = self.postgres.execute(query, tuple(params))

    # Check if there's more
    has_more = len(results) > limit
    items = results[:limit]  # Return only requested amount

    # Create next cursor
    next_cursor = create_next_cursor(results, limit) if has_more else None

    return PaginatedResult(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more
    )
```

---

## 3.3 core/models/

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

## 3.4 core/services/contact_service.py

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
from utils.pagination import Cursor, PaginatedResult, build_cursor_query, create_next_cursor


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
        changes = compute_changes(old.model_dump(), new.model_dump())

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

    def list(
        self,
        limit: int = 20,
        cursor: str | None = None
    ) -> PaginatedResult:
        """List contacts with cursor pagination."""
        cursor_obj = Cursor.decode(cursor) if cursor else None

        base_query = "SELECT * FROM contacts"
        query, params = build_cursor_query(base_query, cursor_obj)
        query += " LIMIT %s"
        params.append(limit + 1)

        results = self.postgres.execute(query, tuple(params))

        has_more = len(results) > limit
        items = [Contact(**r) for r in results[:limit]]
        next_cursor = create_next_cursor(results, limit) if has_more else None

        return PaginatedResult(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more
        )

    def search(
        self,
        query: str,
        limit: int = 20,
        cursor: str | None = None
    ) -> PaginatedResult:
        """
        Search contacts by name, email, phone.

        Uses ILIKE for simple substring matching.
        TODO: Upgrade to full-text search or trigram matching.
        """
        cursor_obj = Cursor.decode(cursor) if cursor else None
        search_pattern = f"%{query}%"

        base_query = """
            SELECT * FROM contacts
            WHERE (name ILIKE %s OR email ILIKE %s OR phone ILIKE %s)
        """
        base_params = [search_pattern, search_pattern, search_pattern]

        # Add cursor condition if present
        if cursor_obj:
            base_query += " AND id > %s"
            base_params.append(cursor_obj.id)

        base_query += " ORDER BY id LIMIT %s"
        base_params.append(limit + 1)

        results = self.postgres.execute(base_query, tuple(base_params))

        has_more = len(results) > limit
        items = [Contact(**r) for r in results[:limit]]
        next_cursor = create_next_cursor(results, limit) if has_more else None

        return PaginatedResult(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more
        )
```

---

## 3.5 core/services/ticket_service.py

**Purpose**: Ticket lifecycle management including close-out flow.

### Implementation

```python
from uuid import UUID, uuid4
from datetime import datetime
from typing import Any
from enum import Enum

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
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
    """

    def __init__(
        self,
        postgres: PostgresClient,
        audit: AuditLogger,
        extractor: AttributeExtractor
    ):
        self.postgres = postgres
        self.audit = audit
        self.extractor = extractor

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

        This is step 2: save attributes, handle follow-up, close ticket.

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

        user_id = get_current_user_id()
        now = now_utc()

        # Save confirmed attributes to contact
        if confirmed_attributes:
            for key, value in confirmed_attributes.items():
                self.postgres.execute(
                    """
                    INSERT INTO attributes (id, user_id, contact_id, key, value, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (contact_id, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                    """,
                    (uuid4(), user_id, ticket.contact_id, key, Json(value), now, now)
                )

        # Handle follow-up scheduling
        if next_service == NextServiceAction.REACH_OUT and reach_out_months:
            from datetime import timedelta
            reach_out_date = now + timedelta(days=reach_out_months * 30)
            self.postgres.execute(
                """
                INSERT INTO scheduled_messages
                    (id, user_id, contact_id, template_name, scheduled_for, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                """,
                (uuid4(), user_id, ticket.contact_id, "service_reminder", reach_out_date, now)
            )

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

        return self.get_by_id(ticket_id)
```

---

## 3.6 core/extraction.py

**Purpose**: LLM-powered attribute extraction from notes.

### Implementation

```python
from typing import Any
from pydantic import BaseModel

from clients.llm_client import LLMClient


class ExtractedAttributes(BaseModel):
    """Attributes extracted from technician notes."""
    attributes: dict[str, Any]
    raw_response: str  # For debugging
    confidence: float  # 0-1 confidence score


class AttributeExtractor:
    """
    Extract structured attributes from free-form technician notes.

    Uses LLM to identify entities and facts that should become
    queryable attributes on the customer record.
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

Output JSON with extracted attributes. Only include attributes you're confident about.
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
        """
        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract attributes from these notes:\n\n{notes}"}
            ],
            response_format={"type": "json_object"}
        )

        import json
        try:
            attributes = json.loads(response.content)
        except json.JSONDecodeError:
            attributes = {}

        return ExtractedAttributes(
            attributes=attributes,
            raw_response=response.content,
            confidence=0.8  # TODO: Calculate based on model response
        )
```

---

## 3.7 Additional Services

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

- [ ] `pytest tests/test_audit.py` - all tests pass
- [ ] `pytest tests/test_pagination.py` - all tests pass
- [ ] `pytest tests/test_contact_service.py` - all tests pass
- [ ] `pytest tests/test_ticket_service.py` - all tests pass

### Integration Tests

- [ ] Can create contact → create address → create ticket flow
- [ ] Clock in/out updates ticket correctly
- [ ] Line items can be added to tickets
- [ ] Close-out flow extracts attributes
- [ ] Closed tickets cannot be modified
- [ ] Audit trail captures all changes
- [ ] Cursor pagination works correctly (test with 50+ records)
- [ ] RLS prevents cross-user data access

### Data Integrity

- [ ] Soft-deleted records don't appear in normal queries
- [ ] Audit log entries are created for all mutations
- [ ] Foreign key relationships enforced

---

## Next Phase

Proceed to [Phase 4: API Routes](./PHASE_4_API_ROUTES.md)
