# Runbooks

Step-by-step guides for common development tasks. Follow these patterns to maintain consistency.

---

## How to Add a New Entity

Example: Adding a `Product` entity (physical items sold alongside services).

### 1. Add Database Table

Edit `schema.sql`:

```sql
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    sku TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ  -- If soft delete needed
);

CREATE TRIGGER products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_products_user ON products(user_id);

-- RLS
ALTER TABLE products ENABLE ROW LEVEL SECURITY;

CREATE POLICY products_isolation ON products FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid AND deleted_at IS NULL);

CREATE POLICY products_insert ON products FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);
```

Run against database:
```bash
psql -U postgres -d crm -c "$(cat schema.sql)"
```

### 2. Create Pydantic Models

Create `core/models/product.py`:

```python
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., ge=0)
    sku: str | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(None, ge=0)
    sku: str | None = None
    is_active: bool | None = None


class Product(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    price: Decimal
    sku: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

Add to `core/models/__init__.py`:
```python
from .product import Product, ProductCreate, ProductUpdate
```

### 3. Create Service

Create `core/services/product_service.py`:

```python
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models.product import Product, ProductCreate, ProductUpdate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc


class ProductService:
    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: ProductCreate) -> Product:
        product_id = uuid4()
        user_id = get_current_user_id()
        now = now_utc()

        self.postgres.execute(
            """
            INSERT INTO products (id, user_id, name, description, price, sku, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (product_id, user_id, data.name, data.description, data.price, data.sku, data.is_active, now, now)
        )

        product = self.get_by_id(product_id)
        self.audit.log_change("product", product_id, AuditAction.CREATE, {"created": product.model_dump(mode="json")})
        return product

    def get_by_id(self, product_id: UUID) -> Product | None:
        row = self.postgres.execute_one("SELECT * FROM products WHERE id = %s", (product_id,))
        return Product(**row) if row else None

    def update(self, product_id: UUID, data: ProductUpdate) -> Product:
        old = self.get_by_id(product_id)
        if not old:
            raise ValueError(f"Product {product_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return old

        update_data["updated_at"] = now_utc()
        set_clauses = [f"{k} = %s" for k in update_data.keys()]
        values = list(update_data.values()) + [product_id]

        self.postgres.execute(f"UPDATE products SET {', '.join(set_clauses)} WHERE id = %s", tuple(values))

        new = self.get_by_id(product_id)
        changes = compute_changes(old.model_dump(mode="json"), new.model_dump(mode="json"))
        if changes:
            self.audit.log_change("product", product_id, AuditAction.UPDATE, changes)
        return new

    def delete(self, product_id: UUID) -> None:
        old = self.get_by_id(product_id)
        if not old:
            raise ValueError(f"Product {product_id} not found")

        self.postgres.execute(
            "UPDATE products SET deleted_at = %s, updated_at = %s WHERE id = %s",
            (now_utc(), now_utc(), product_id)
        )
        self.audit.log_change("product", product_id, AuditAction.DELETE, {"deleted": old.model_dump(mode="json")})

    def list(self, limit: int = 20, cursor: str | None = None) -> PaginatedResult:
        cursor_obj = Cursor.decode(cursor) if cursor else None

        query = "SELECT * FROM products"
        params = []

        if cursor_obj:
            query += " WHERE id > %s"
            params.append(cursor_obj.id)

        query += " ORDER BY id LIMIT %s"
        params.append(limit + 1)

        results = self.postgres.execute(query, tuple(params))
        has_more = len(results) > limit
        items = [Product(**r) for r in results[:limit]]
        next_cursor = create_next_cursor(results, limit) if has_more else None

        return PaginatedResult(items=items, next_cursor=next_cursor, has_more=has_more)
```

### 4. Register in API

Add to data handlers in `main.py`:
```python
product_service = ProductService(postgres, audit)

data_services = {
    # ... existing ...
    "products": product_service,
}
```

Add action handler if needed (see "How to Add a New Action" below).

### 5. Write Tests

Create `tests/test_product_service.py` covering:

```python
# Test file structure - all tests use `user_context` fixture for RLS

def test_create_product(...)       # Create and verify fields returned
def test_get_product_not_found(...) # get_by_id returns None for missing
def test_update_product(...)       # Partial update with exclude_unset
def test_delete_product(...)       # Soft delete sets deleted_at

# Critical: RLS isolation test
def test_rls_isolation(product_service, user_context):
    """User A creates item, User B cannot see it."""
    user_a, user_b = uuid4(), uuid4()

    with user_context(user_a):
        product = product_service.create(ProductCreate(name="A's Product", price=Decimal("10.00")))

    with user_context(user_b):
        assert product_service.get_by_id(product.id) is None  # RLS filters
```

The RLS test is mandatory - it verifies user isolation works correctly.

### 6. Update Phase Docs

Add the entity to the relevant phase document's schema section and model list.

---

## How to Add a New Action

Example: Adding `archive` action to the customer domain.

### 1. Add Method to Service

In `core/services/customer_service.py`:

```python
def archive(self, customer_id: UUID, reason: str | None = None) -> Customer:
    """Archive a customer (soft delete with reason tracking)."""
    customer = self.get_by_id(customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    if customer.deleted_at:
        raise ValueError("Customer already archived")

    now = now_utc()
    self.postgres.execute(
        "UPDATE customers SET deleted_at = %s, updated_at = %s WHERE id = %s",
        (now, now, customer_id)
    )

    self.audit.log_change(
        "customer",
        customer_id,
        AuditAction.DELETE,
        {"archived": customer.model_dump(mode="json"), "reason": reason}
    )

    # Return the archived customer (fetch with admin to bypass RLS)
    row = self.postgres.execute_admin("SELECT * FROM customers WHERE id = %s", (customer_id,))
    return Customer(**row[0]) if row else None
```

### 2. Add to Action Handler

In `api/actions.py`, find `CustomerActionHandler`:

```python
class CustomerActionHandler:
    # ... existing methods ...

    def archive(self, customer_id: str, reason: str | None = None) -> dict:
        """Archive a customer."""
        customer = self.customer_service.archive(UUID(customer_id), reason)
        return {"archived": True, "customer_id": customer_id}
```

### 3. Test It

```bash
# Via API
curl -X POST http://localhost:8000/api/actions \
  -H "Content-Type: application/json" \
  -d '{"domain": "customer", "action": "archive", "data": {"customer_id": "...", "reason": "Moved away"}}'
```

### 4. Add Error Code (if needed)

If the action can fail in a new way, add error code to `docs/ERROR_CODES.md` first, then to `api/base.py`.

---

## How to Add a New Error Code

### 1. Document It First

Add to `docs/ERROR_CODES.md`:

```markdown
### `CUSTOMER_ARCHIVED`
**HTTP Status:** 409

**When to use:**
- Attempting to create ticket for archived customer
- Attempting to modify archived customer

**Example message:** `"Customer has been archived and cannot be modified."`

**Client handling:** Show archived state. Offer to restore if appropriate.
```

### 2. Add to ErrorCodes Class

In `api/base.py`:

```python
class ErrorCodes:
    # ... existing ...
    CUSTOMER_ARCHIVED = "CUSTOMER_ARCHIVED"
```

### 3. Use It

```python
from api.base import error_response, ErrorCodes

if customer.deleted_at:
    return error_response(ErrorCodes.CUSTOMER_ARCHIVED, "Customer has been archived.")
```

---

## How to Add a New Attribute Extraction Category

Example: Adding `vehicle` extraction (for customers who need driveway access).

### 1. Update Extraction Prompt

In `core/extraction.py`, update `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = """You are an assistant that extracts structured information from service technician notes.

Categories to look for:
- customer_demographic: age indicators (elderly, young family, etc.)
- pet: any pets mentioned (type, name if given)
- property_notes: important property details (gate codes, access instructions, hazards)
- equipment_needed: special equipment requirements
- service_preferences: customer preferences about timing, methods, etc.
- property_details: physical property characteristics
- vehicle: vehicles mentioned (for driveway/parking notes)

...rest of prompt...

Example output:
{
  "customer_demographic": "elderly",
  "pet": {"type": "dog", "name": "Biscuit"},
  "vehicle": {"type": "truck", "note": "parks in driveway, need to work around"}
}
"""
```

### 2. Test Extraction

```python
def test_vehicle_extraction(extractor):
    notes = "Large truck always parked in driveway. Had to set up ladder on lawn instead."
    result = extractor.extract_attributes(notes)
    assert "vehicle" in result.attributes
```

### 3. Update UI (if needed)

If the attribute needs special display handling, update the close-out confirmation template.

---

## How to Add a New Scheduled Message Type

Example: Adding `payment_reminder` message type.

### 1. Update Database Constraint

Modify `schema.sql` constraint:

```sql
CONSTRAINT scheduled_messages_valid_type CHECK (
    message_type IN ('service_reminder', 'appointment_confirmation', 'appointment_reminder', 'payment_reminder', 'custom')
)
```

Run migration:
```sql
ALTER TABLE scheduled_messages DROP CONSTRAINT scheduled_messages_valid_type;
ALTER TABLE scheduled_messages ADD CONSTRAINT scheduled_messages_valid_type CHECK (
    message_type IN ('service_reminder', 'appointment_confirmation', 'appointment_reminder', 'payment_reminder', 'custom')
);
```

### 2. Create Template

Create email template in `templates/email/payment_reminder.html`:

```html
<h2>Payment Reminder</h2>
<p>Hi {{ customer_name }},</p>
<p>This is a friendly reminder that invoice #{{ invoice_number }} for ${{ amount }} is due on {{ due_date }}.</p>
<p><a href="{{ payment_link }}">Pay Now</a></p>
```

### 3. Add Scheduling Logic

In `core/services/message_service.py`:

```python
def schedule_payment_reminder(
    self,
    customer_id: UUID,
    invoice_id: UUID,
    remind_at: datetime
) -> ScheduledMessage:
    """Schedule a payment reminder for an unpaid invoice."""
    return self._schedule_message(
        customer_id=customer_id,
        message_type="payment_reminder",
        template_name="payment_reminder",
        scheduled_for=remind_at,
        context={"invoice_id": str(invoice_id)}
    )
```

### 4. Add to Invoice Flow

In invoice service, when invoice is sent:

```python
def send(self, invoice_id: UUID) -> Invoice:
    # ... send invoice ...

    # Schedule payment reminder for 3 days before due date
    if invoice.due_at:
        remind_at = invoice.due_at - timedelta(days=3)
        if remind_at > now_utc():
            self.message_service.schedule_payment_reminder(
                invoice.customer_id,
                invoice.id,
                remind_at
            )
```

---

## How to Add a New API Endpoint

Example: Adding `GET /api/data/tickets/week` for week view.

### 1. Add Route

In `api/data.py` or a domain-specific router:

```python
@router.get("/tickets/week")
async def get_week_tickets(
    request: Request,
    start_date: str = Query(..., description="Week start date (YYYY-MM-DD)"),
) -> APIResponse:
    """Get tickets for a specific week."""
    from datetime import datetime, timedelta

    try:
        week_start = datetime.fromisoformat(start_date)
    except ValueError:
        return error_response(ErrorCodes.VALIDATION_ERROR, "Invalid date format. Use YYYY-MM-DD.")

    week_end = week_start + timedelta(days=7)

    tickets = request.app.state.services["tickets"].list_for_date_range(week_start, week_end)

    return success_response({
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "tickets": [t.model_dump(mode="json") for t in tickets]
    })
```

### 2. Add Service Method

In `core/services/ticket_service.py`:

```python
def list_for_date_range(self, start: datetime, end: datetime) -> list[Ticket]:
    """List tickets within a date range."""
    results = self.postgres.execute(
        """
        SELECT * FROM tickets
        WHERE scheduled_at >= %s AND scheduled_at < %s
        ORDER BY scheduled_at
        """,
        (start, end)
    )
    return [Ticket(**r) for r in results]
```

### 3. Test It

```python
def test_get_week_tickets(client, auth_cookie):
    response = client.get(
        "/api/data/tickets/week?start_date=2024-01-15",
        cookies={"session_token": auth_cookie}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "tickets" in data["data"]
```

---

## How to Add a Database Index

When queries are slow, add indexes.

### 1. Identify Slow Query

Check query patterns. Common candidates:
- Columns in WHERE clauses
- Columns in ORDER BY
- Foreign keys
- Columns used in JOINs

### 2. Add Index

```sql
-- Single column
CREATE INDEX idx_tickets_customer ON tickets(customer_id);

-- Composite (for queries filtering on both)
CREATE INDEX idx_tickets_user_status ON tickets(user_id, status);

-- Partial (for common filtered queries)
CREATE INDEX idx_tickets_pending ON tickets(scheduled_at)
    WHERE status = 'scheduled';

-- Trigram (for LIKE/ILIKE fuzzy search)
CREATE INDEX idx_customers_name_trgm ON customers
    USING GIN (first_name gin_trgm_ops);
```

### 3. Update schema.sql

Add the index to `schema.sql` so it's included in fresh installs.

### 4. Verify

```sql
EXPLAIN ANALYZE SELECT * FROM tickets WHERE customer_id = '...';
-- Should show "Index Scan" not "Seq Scan"
```

---

## How to Add RLS to a New Table

Every user-scoped table needs RLS. See `PHASE_1_INFRASTRUCTURE.md` for the authoritative explanation of RLS context injection.

### Quick Reference

```sql
-- 1. Enable RLS
ALTER TABLE your_table ENABLE ROW LEVEL SECURITY;

-- 2. Isolation policy (read/update/delete)
CREATE POLICY your_table_isolation ON your_table FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid AND deleted_at IS NULL);

-- 3. Insert policy
CREATE POLICY your_table_insert ON your_table FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);
```

### Test Isolation (Mandatory)

See the RLS isolation test pattern in "How to Add a New Entity" above - every entity needs this test.

---

## Quick Reference: File Locations

| What | Where |
|------|-------|
| Database schema | `schema.sql` |
| Pydantic models | `core/models/{entity}.py` |
| Business logic | `core/services/{entity}_service.py` |
| API routes | `api/data.py`, `api/actions.py` |
| Error codes | `docs/ERROR_CODES.md` → `api/base.py` |
| Tests | `tests/test_{entity}_service.py` |
| LLM prompts | `core/extraction.py` |
| Email templates | `templates/email/` |
