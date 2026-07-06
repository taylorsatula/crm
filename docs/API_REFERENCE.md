# CRM API Reference

This document explains how to operate the CRM entirely through its HTTP API. The API is built with FastAPI and exposes a small set of composable endpoints:

- Authentication: `/auth/*`
- Reads: `GET /api/data` plus a few read convenience routes
- Mutations: `POST /api/actions`
- Health and diagnostics: `/health*`

The live OpenAPI schema is also available at `/openapi.json`, and the FastAPI Swagger UI is available at `/docs`.

---

## 1. Conventions

### Base URL

Use the deployment origin as the base URL. In local development this is commonly:

```text
http://localhost:8000
```

Examples below use:

```bash
BASE_URL="http://localhost:8000"
```

### Authentication model

The API support two authentication methods:

1.  **Session Cookies**: Protected API routes use an HTTP-only cookie named `session_token`. Browser clients should rely on normal cookie handling.
2.  **Access Tokens (Bearer)**: Scripts and automation should use personal access tokens via the `Authorization` header.

```bash
# Using a session cookie (scripted client)
curl -c cookies.txt -b cookies.txt "$BASE_URL/auth/me"

# Using a bearer access token
curl -H "Authorization: Bearer crm_pat_..." "$BASE_URL/auth/me"
```

Public routes:

- `GET /`
- `POST /auth/request-link`
- `GET /auth/verify`
- `POST /auth/dev-autobypass` — local development only
- `POST /auth/logout`
- `GET /health`
- `GET /health/ready`
- `GET /health/live`
- `GET /docs`, `GET /openapi.json`
- `/assets/*`

All `/api/*` routes require a valid session.

### Response envelope

Every JSON API response uses the same envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {
    "timestamp": "2026-07-06T12:00:00Z",
    "request_id": "7d1f4b47-3f47-43f3-95f6-cf73a3d1a0f5"
  }
}
```

Errors keep the same shape:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "NOT_AUTHENTICATED",
    "message": "Authentication required"
  },
  "meta": {
    "timestamp": "2026-07-06T12:00:00Z",
    "request_id": "7d1f4b47-3f47-43f3-95f6-cf73a3d1a0f5"
  }
}
```

The server also returns `X-Request-ID`; include that value in bug reports and logs.

### Data format rules

- IDs are UUID strings.
- Datetimes are ISO 8601 strings. Send timezone-aware UTC values, for example `2026-07-06T14:30:00Z`.
- Money is represented as integer cents. `$125.00` is `12500`.
- Tax rates are basis points. `825` means 8.25%; `10000` means 100%.
- Enum values are lowercase strings exactly as shown in this document.

---

## 2. Authentication

### Request a magic link

```http
POST /auth/request-link
Content-Type: application/json
```

Request:

```json
{
  "email": "owner@example.com"
}
```

Response data:

```json
{
  "sent": true,
  "needs_signup": false
}
```

If rate limited, the server returns HTTP `429`, error code `RATE_LIMITED`, and a `Retry-After` header.

### Verify a magic link

```http
GET /auth/verify?token=<magic-link-token>
```

On success, the server sets the `session_token` cookie.

Response data:

```json
{
  "user": {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "owner@example.com"
  }
}
```

Invalid, expired, or reused tokens return HTTP `401` with `INVALID_TOKEN`.

### Local development auth bypass

```http
POST /auth/dev-autobypass
```

This endpoint is intentionally local-only and insecure by design. It mints a real session for the local test user without email verification.

```bash
curl -c cookies.txt -b cookies.txt -X POST "$BASE_URL/auth/dev-autobypass"
```

Response data:

```json
{
  "user_id": "00000000-0000-0000-0000-000000000001",
  "temporary_development_autobypass": true
}
```

### Current user

```http
GET /auth/me
```

Response data:

```json
{
  "user_id": "00000000-0000-0000-0000-000000000001"
}
```

### Logout

```http
POST /auth/logout
```

Revokes the current session if one exists and clears the session cookie.

### Personal Access Tokens

Personal access tokens (PATs) are long-lived, revocable credentials for API access. Unlike session cookies, they are not tied to browser sessions and have fixed scopes.

#### Token format

`crm_pat_<8-hex-prefix>_<urlsafe-secret>`

#### Generating a token

Use the creation script from the project root:

```bash
python scripts/create_access_token.py \
  --email owner@example.com \
  --name "Backup Script" \
  --scopes read
```

By default, tokens expire in 365 days.

#### Scopes

Bearer tokens are restricted by coarse scopes:

- `read`: Permits all `GET` data reads.
- `write`: Permits `/api/actions` mutations and generic `POST` actions.
- `admin`: Full access to read and write (reserved for future admin routes).

If a token has insufficient scope for a route, the server returns HTTP `403` with `AUTHORIZATION_DENIED`.

---

## 3. Read API

Most reads go through:

```http
GET /api/data
```

Common query parameters:

| Parameter | Required | Meaning |
|---|---:|---|
| `type` | yes | One of `attributes`, `customers`, `invoices`, `messages`, `notes`, `services`, `tickets` |
| `id` | no | Fetch one resource where supported |
| `search` | no | Customer search term |
| `customer_id` | no | Filter by customer |
| `ticket_id` | no | Filter by ticket |
| `include` | no | Comma-separated expansions for supported single-resource reads |
| `filter` | no | Resource-specific status/list filter |
| `limit` | no | Default `50`, min `1`, max `500` |
| `offset` | no | Default `0`; currently used by customer list/search |

### Customers

List customers:

```http
GET /api/data?type=customers&limit=50&offset=0
```

Search customers by first name, last name, business name, email, or phone:

```http
GET /api/data?type=customers&search=smith&limit=20
```

Get one customer:

```http
GET /api/data?type=customers&id=<customer_id>
```

Supported includes for one customer:

```http
GET /api/data?type=customers&id=<customer_id>&include=addresses,tickets,invoices,notes,messages,attributes
```

Exact include keys added to `data`:

- `addresses`
- `tickets`
- `invoices`
- `note_items` for `include=notes`
- `messages`
- `attributes`

Customer entity fields:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "first_name": "Taylor",
  "last_name": "Example",
  "business_name": null,
  "email": "customer@example.com",
  "phone": "555-0100",
  "address": "Legacy free-form address",
  "reference_id": null,
  "referred_by": null,
  "notes": "Gate code is 1234",
  "preferred_contact_method": "text",
  "preferred_time_of_day": "morning",
  "stripe_customer_id": null,
  "created_at": "2026-07-06T12:00:00Z",
  "updated_at": "2026-07-06T12:00:00Z",
  "deleted_at": null
}
```

### Customer dossier

```http
GET /api/data/customers/<customer_id>/dossier
```

This is the best API call for a customer detail screen. Response data:

```json
{
  "customer": { "...": "customer plus display_name" },
  "addresses": [{ "...": "address plus one_line" }],
  "attributes": [],
  "notes": [],
  "recent_tickets": [],
  "invoices": [],
  "open_invoices": [],
  "messages": [],
  "pending_messages": []
}
```

### Tickets

List upcoming tickets as enriched packets:

```http
GET /api/data?type=tickets&filter=upcoming&limit=50
```

List all tickets as enriched packets:

```http
GET /api/data?type=tickets&filter=all&limit=50
```

List tickets for one customer as raw ticket entities:

```http
GET /api/data?type=tickets&customer_id=<customer_id>&limit=50
```

Get one ticket:

```http
GET /api/data?type=tickets&id=<ticket_id>
```

Supported includes for one ticket:

```http
GET /api/data?type=tickets&id=<ticket_id>&include=line_items,notes,messages
```

Ticket entity fields:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "customer_id": "uuid",
  "address_id": "uuid",
  "status": "scheduled",
  "scheduled_at": "2026-07-06T14:30:00Z",
  "scheduled_duration_minutes": 120,
  "confirmation_status": "pending",
  "confirmation_sent_at": null,
  "confirmed_at": null,
  "clock_in_at": null,
  "clock_out_at": null,
  "actual_duration_minutes": null,
  "notes": "Exterior windows only",
  "closed_at": null,
  "is_price_estimated": false,
  "created_at": "2026-07-06T12:00:00Z",
  "updated_at": "2026-07-06T12:00:00Z",
  "deleted_at": null
}
```

Ticket statuses:

- `scheduled`
- `in_progress`
- `completed`
- `cancelled`

Confirmation statuses:

- `pending`
- `confirmed`
- `declined`
- `reschedule_requested`

### Ticket convenience reads

Today's raw tickets:

```http
GET /api/data/tickets/today
```

Currently clocked-in ticket, or `null`:

```http
GET /api/data/tickets/current
```

Today's enriched control-surface packets:

```http
GET /api/data/today
```

Full ticket packet:

```http
GET /api/data/tickets/<ticket_id>/packet
```

Ticket packet response data:

```json
{
  "ticket": {},
  "customer": { "...": "customer plus display_name" },
  "address": { "...": "address plus one_line" },
  "addresses": [],
  "services": [],
  "line_items": [],
  "scope_summary": "Exterior windows, Screens",
  "total_price_cents": 25000,
  "job_notes": "Exterior windows only",
  "notes": [],
  "pending_messages": [],
  "pending_message_count": 0,
  "invoices": [],
  "invoice_summary": null,
  "clock_state": "not_started"
}
```

`clock_state` values are `not_started`, `in_progress`, and `clocked_out`.

### Services / catalog

List all non-deleted services:

```http
GET /api/data?type=services
```

List only active services:

```http
GET /api/data?type=services&filter=active
```

The generic service read endpoint currently returns lists only; there is no `GET /api/data?type=services&id=...` handler.

Service fields:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "name": "Exterior Window Cleaning",
  "description": "Standard exterior clean",
  "pricing_type": "fixed",
  "default_price_cents": 12500,
  "unit_price_cents": null,
  "unit_label": null,
  "is_active": true,
  "display_order": 0,
  "created_at": "2026-07-06T12:00:00Z",
  "updated_at": "2026-07-06T12:00:00Z",
  "deleted_at": null
}
```

Pricing types:

- `fixed` — requires `default_price_cents`
- `flexible` — price is set on the ticket line item
- `per_unit` — requires `unit_price_cents`; `quantity * unit_price_cents` determines total unless overridden

### Invoices

Get one invoice:

```http
GET /api/data?type=invoices&id=<invoice_id>
```

List for a customer:

```http
GET /api/data?type=invoices&customer_id=<customer_id>&limit=50
```

List by filter:

```http
GET /api/data?type=invoices&filter=unpaid
GET /api/data?type=invoices&filter=draft
GET /api/data?type=invoices&filter=all
```

Invoice statuses:

- `draft`
- `sent`
- `partial`
- `paid`
- `void`

Invoice fields:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "customer_id": "uuid",
  "ticket_id": "uuid",
  "invoice_number": "INV-20260706-0001",
  "status": "draft",
  "subtotal_cents": 25000,
  "tax_rate_bps": 0,
  "tax_amount_cents": 0,
  "total_amount_cents": 25000,
  "amount_paid_cents": 0,
  "issued_at": null,
  "due_at": null,
  "sent_at": null,
  "paid_at": null,
  "voided_at": null,
  "stripe_checkout_session_id": null,
  "stripe_payment_intent_id": null,
  "notes": null,
  "created_at": "2026-07-06T12:00:00Z",
  "updated_at": "2026-07-06T12:00:00Z",
  "deleted_at": null
}
```

### Messages

Get one scheduled message:

```http
GET /api/data?type=messages&id=<message_id>
```

List messages for a customer:

```http
GET /api/data?type=messages&customer_id=<customer_id>&limit=50
```

List pending messages for a ticket:

```http
GET /api/data?type=messages&ticket_id=<ticket_id>
```

List by filter:

```http
GET /api/data?type=messages&filter=due
GET /api/data?type=messages&filter=pending
GET /api/data?type=messages&filter=sent
GET /api/data?type=messages&filter=failed
GET /api/data?type=messages&filter=cancelled
GET /api/data?type=messages&filter=skipped
```

Message types:

- `service_reminder`
- `appointment_confirmation`
- `appointment_reminder`
- `custom`

Message statuses:

- `pending`
- `sent`
- `cancelled`
- `failed`
- `skipped`

### Notes

Get one note:

```http
GET /api/data?type=notes&id=<note_id>
```

List customer notes:

```http
GET /api/data?type=notes&customer_id=<customer_id>&limit=50
```

List ticket notes:

```http
GET /api/data?type=notes&ticket_id=<ticket_id>&limit=50
```

A note must belong to exactly one customer or one ticket.

### Attributes

Get one attribute:

```http
GET /api/data?type=attributes&id=<attribute_id>
```

List customer attributes:

```http
GET /api/data?type=attributes&customer_id=<customer_id>
```

Attributes are key-value facts attached to customers. Creating an attribute with an existing `customer_id + key` updates the existing attribute rather than creating a duplicate.

---

## 4. Mutation API

All writes use:

```http
POST /api/actions
Content-Type: application/json
```

Request shape:

```json
{
  "domain": "customer",
  "action": "create",
  "data": {}
}
```

The response `data` is the created/updated entity, a workflow-specific object, or `{ "deleted": true }`.

### Customer actions

Allowed actions: `create`, `update`, `delete`.

Create:

```json
{
  "domain": "customer",
  "action": "create",
  "data": {
    "first_name": "Taylor",
    "last_name": "Example",
    "email": "customer@example.com",
    "phone": "555-0100",
    "preferred_contact_method": "text",
    "preferred_time_of_day": "morning",
    "notes": "Gate code is 1234"
  }
}
```

At least one of `first_name`, `last_name`, or `business_name` is required.

Update:

```json
{
  "domain": "customer",
  "action": "update",
  "data": {
    "id": "<customer_id>",
    "phone": "555-0199",
    "notes": "Updated notes"
  }
}
```

Delete:

```json
{
  "domain": "customer",
  "action": "delete",
  "data": { "id": "<customer_id>" }
}
```

Customers are soft-deleted.

### Address actions

Allowed actions: `create`, `update`, `delete`.

Create:

```json
{
  "domain": "address",
  "action": "create",
  "data": {
    "customer_id": "<customer_id>",
    "label": "Home",
    "street": "123 Main St",
    "street2": null,
    "city": "Austin",
    "state": "TX",
    "zip": "78701",
    "notes": "Use side gate",
    "is_primary": true
  }
}
```

Update:

```json
{
  "domain": "address",
  "action": "update",
  "data": {
    "id": "<address_id>",
    "notes": "Park in driveway"
  }
}
```

Delete:

```json
{
  "domain": "address",
  "action": "delete",
  "data": { "id": "<address_id>" }
}
```

Addresses are hard-deleted.

### Catalog actions

Allowed actions: `create`, `update`, `delete`.

Create fixed-price service:

```json
{
  "domain": "catalog",
  "action": "create",
  "data": {
    "name": "Exterior Window Cleaning",
    "description": "Standard exterior clean",
    "pricing_type": "fixed",
    "default_price_cents": 12500,
    "is_active": true,
    "display_order": 10
  }
}
```

Create per-unit service:

```json
{
  "domain": "catalog",
  "action": "create",
  "data": {
    "name": "Screen Cleaning",
    "pricing_type": "per_unit",
    "unit_price_cents": 500,
    "unit_label": "screen",
    "is_active": true
  }
}
```

Create flexible-price service:

```json
{
  "domain": "catalog",
  "action": "create",
  "data": {
    "name": "Custom Cleaning",
    "pricing_type": "flexible",
    "is_active": true
  }
}
```

Update:

```json
{
  "domain": "catalog",
  "action": "update",
  "data": {
    "id": "<service_id>",
    "is_active": false
  }
}
```

Delete:

```json
{
  "domain": "catalog",
  "action": "delete",
  "data": { "id": "<service_id>" }
}
```

Services are soft-deleted.

### Ticket actions

Allowed actions: `create`, `update`, `delete`, `clock_in`, `clock_out`, `close`, `closeout`, `cancel`.

Create appointment/job ticket:

```json
{
  "domain": "ticket",
  "action": "create",
  "data": {
    "customer_id": "<customer_id>",
    "address_id": "<address_id>",
    "scheduled_at": "2026-07-06T14:30:00Z",
    "scheduled_duration_minutes": 120,
    "is_price_estimated": false,
    "notes": "Exterior windows only"
  }
}
```

Update schedule/details:

```json
{
  "domain": "ticket",
  "action": "update",
  "data": {
    "id": "<ticket_id>",
    "scheduled_at": "2026-07-07T15:00:00Z",
    "scheduled_duration_minutes": 150,
    "confirmation_status": "confirmed"
  }
}
```

Clock in:

```json
{
  "domain": "ticket",
  "action": "clock_in",
  "data": { "id": "<ticket_id>" }
}
```

Clock out:

```json
{
  "domain": "ticket",
  "action": "clock_out",
  "data": { "id": "<ticket_id>" }
}
```

Close without closeout payload:

```json
{
  "domain": "ticket",
  "action": "close",
  "data": { "id": "<ticket_id>" }
}
```

Closeout with confirmed duration and final note:

```json
{
  "domain": "ticket",
  "action": "closeout",
  "data": {
    "id": "<ticket_id>",
    "confirmed_duration_minutes": 135,
    "final_note": "Completed exterior and screens. Customer requested spring reminder."
  }
}
```

Closeout response data:

```json
{
  "ticket": { "...": "completed ticket" },
  "customer_id": "<customer_id>",
  "address_id": "<address_id>"
}
```

Cancel:

```json
{
  "domain": "ticket",
  "action": "cancel",
  "data": { "id": "<ticket_id>" }
}
```

Delete:

```json
{
  "domain": "ticket",
  "action": "delete",
  "data": { "id": "<ticket_id>" }
}
```

Tickets are soft-deleted. Completed and cancelled tickets are terminal for normal workflow purposes.

### Line item actions

Allowed actions: `create`, `update`, `delete`.

Create line item:

```json
{
  "domain": "line_item",
  "action": "create",
  "data": {
    "ticket_id": "<ticket_id>",
    "service_id": "<service_id>",
    "description": "Exterior windows",
    "quantity": 1,
    "unit_price_cents": 12500,
    "total_price_cents": 12500,
    "duration_minutes": 90,
    "notes": "Includes garage windows"
  }
}
```

Pricing behavior:

- If `total_price_cents` is omitted and `unit_price_cents` is present, total is computed as `quantity * unit_price_cents`.
- If both are omitted, the service default price or service unit price is used when available.
- Flexible-price services may produce a line item with no total until a price is supplied.

Update:

```json
{
  "domain": "line_item",
  "action": "update",
  "data": {
    "id": "<line_item_id>",
    "quantity": 12,
    "unit_price_cents": 500,
    "total_price_cents": 6000
  }
}
```

Delete:

```json
{
  "domain": "line_item",
  "action": "delete",
  "data": { "id": "<line_item_id>" }
}
```

Line items are soft-deleted. They cannot be created or updated on completed or cancelled tickets.

### Invoice actions

Allowed actions: `create_from_ticket`, `send`, `record_payment`, `void`.

Create draft invoice from ticket line items:

```json
{
  "domain": "invoice",
  "action": "create_from_ticket",
  "data": {
    "ticket_id": "<ticket_id>",
    "tax_rate_bps": 825,
    "notes": "Due on receipt"
  }
}
```

The invoice subtotal is calculated from non-deleted ticket line items. A ticket with no billable line items is rejected.

Send invoice:

```json
{
  "domain": "invoice",
  "action": "send",
  "data": { "id": "<invoice_id>" }
}
```

Record payment:

```json
{
  "domain": "invoice",
  "action": "record_payment",
  "data": {
    "id": "<invoice_id>",
    "amount_cents": 10000
  }
}
```

Partial payments set status to `partial`; payment at or above the invoice total sets status to `paid`.

Void invoice:

```json
{
  "domain": "invoice",
  "action": "void",
  "data": { "id": "<invoice_id>" }
}
```

Paid invoices cannot be voided.

### Note actions

Allowed actions: `create`, `delete`.

Create customer note:

```json
{
  "domain": "note",
  "action": "create",
  "data": {
    "customer_id": "<customer_id>",
    "content": "Prefers text reminders."
  }
}
```

Create ticket note:

```json
{
  "domain": "note",
  "action": "create",
  "data": {
    "ticket_id": "<ticket_id>",
    "content": "Technician after-action note."
  }
}
```

Exactly one of `customer_id` or `ticket_id` must be supplied.

Delete:

```json
{
  "domain": "note",
  "action": "delete",
  "data": { "id": "<note_id>" }
}
```

Notes are soft-deleted.

### Attribute actions

Allowed actions: `create`, `delete`.

Create or update customer attribute:

```json
{
  "domain": "attribute",
  "action": "create",
  "data": {
    "customer_id": "<customer_id>",
    "key": "property.has_solar_screens",
    "value": true,
    "source_type": "manual"
  }
}
```

LLM-extracted attribute example:

```json
{
  "domain": "attribute",
  "action": "create",
  "data": {
    "customer_id": "<customer_id>",
    "key": "preference.reminder_season",
    "value": "spring",
    "source_type": "llm_extracted",
    "source_note_id": "<note_id>",
    "confidence": "0.87"
  }
}
```

`source_type` must be `manual` or `llm_extracted`. `confidence` is a decimal from `0.00` to `1.00`.

Delete:

```json
{
  "domain": "attribute",
  "action": "delete",
  "data": { "id": "<attribute_id>" }
}
```

Attributes are hard-deleted.

### Message actions

Allowed actions: `schedule`, `cancel`.

Schedule an appointment reminder:

```json
{
  "domain": "message",
  "action": "schedule",
  "data": {
    "customer_id": "<customer_id>",
    "ticket_id": "<ticket_id>",
    "message_type": "appointment_reminder",
    "template_name": "appointment_reminder_24h",
    "subject": "Reminder: window cleaning tomorrow",
    "body": "We will see you tomorrow at 10:00 AM.",
    "scheduled_for": "2026-07-05T14:30:00Z"
  }
}
```

Cancel a pending message:

```json
{
  "domain": "message",
  "action": "cancel",
  "data": { "id": "<message_id>" }
}
```

Only pending messages can be cancelled.

---

## 5. End-to-end API workflows

### A. Bootstrap a service catalog

1. Create fixed, per-unit, and flexible services with `catalog.create`.
2. Read active services with `GET /api/data?type=services&filter=active`.
3. Store returned service IDs for line-item creation.

### B. Add a new customer and service address

```bash
curl -c cookies.txt -b cookies.txt \
  -H 'Content-Type: application/json' \
  -X POST "$BASE_URL/api/actions" \
  -d '{
    "domain": "customer",
    "action": "create",
    "data": {"first_name": "Jane", "last_name": "Smith", "phone": "555-0100"}
  }'
```

Use the returned `data.id` as `customer_id`, then call `address.create`.

### C. Schedule a job

1. Create the ticket with `ticket.create` using `customer_id`, `address_id`, and `scheduled_at`.
2. Add one or more line items with `line_item.create`.
3. Optionally schedule confirmation/reminder messages with `message.schedule`.
4. Read `GET /api/data/tickets/<ticket_id>/packet` for the complete job packet.

### D. Technician day-of workflow

1. List today's jobs: `GET /api/data/today`.
2. Open a job packet: `GET /api/data/tickets/<ticket_id>/packet`.
3. Start work: `ticket.clock_in`.
4. Add ticket notes as needed with `note.create`.
5. Finish work: `ticket.clock_out`.
6. Complete closeout: `ticket.closeout` with `confirmed_duration_minutes` and optional `final_note`.

### E. Invoice and payment workflow

1. Ensure the ticket has line items with totals.
2. Create draft invoice: `invoice.create_from_ticket`.
3. Send invoice: `invoice.send`.
4. Record payments with `invoice.record_payment` until status becomes `paid`.
5. View unpaid invoices with `GET /api/data?type=invoices&filter=unpaid`.

### F. Customer history and structured data workflow

1. Add customer or ticket notes with `note.create`.
2. Store queryable facts with `attribute.create`.
3. Read the customer dossier with `GET /api/data/customers/<customer_id>/dossier`.

---

## 6. Lifecycle rules

### Ticket lifecycle

Normal path:

```text
scheduled -> in_progress -> completed
```

Actions:

- `ticket.create` creates `scheduled` tickets.
- `ticket.clock_in` changes `scheduled` to `in_progress` and sets `clock_in_at`.
- `ticket.clock_out` sets `clock_out_at` and `actual_duration_minutes` but does not by itself mark the ticket completed.
- `ticket.close` or `ticket.closeout` marks the ticket `completed` and sets `closed_at`.
- `ticket.cancel` marks a non-completed ticket `cancelled` and sets `closed_at`.

Closed/completed tickets are immutable for normal ticket updates. Line items cannot be created or updated on completed or cancelled tickets.

### Invoice lifecycle

Common path:

```text
draft -> sent -> partial -> paid
```

Other valid terminal path:

```text
draft/sent/partial -> void
```

Rules:

- Invoices are created from ticket line items.
- `invoice.send` sets `sent_at` and `issued_at`.
- `invoice.record_payment` accumulates `amount_paid_cents`.
- Paid invoices are terminal and cannot be voided.

### Message lifecycle

```text
pending -> sent
pending -> cancelled
pending -> failed
pending -> skipped
```

Only `pending` messages can be cancelled through the public action API.

---

## 7. Error handling

Common codes:

| Code | HTTP status | Meaning |
|---|---:|---|
| `NOT_AUTHENTICATED` | 401 | Missing or invalid session cookie |
| `SESSION_EXPIRED` | 401 | Session existed but expired or was revoked |
| `INVALID_TOKEN` | 401/400 | Magic link token invalid, expired, or used |
| `RATE_LIMITED` | 429 | Too many auth attempts |
| `NOT_FOUND` | 404 | Resource does not exist, is deleted, or is hidden by user isolation |
| `VALIDATION_ERROR` | 422 | Request body/query failed Pydantic/FastAPI validation |
| `INVALID_REQUEST` | 400 | Unknown type/domain/action or malformed request |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
| `SERVICE_UNAVAILABLE` | 503 | Runtime dependency unavailable |

Client handling pattern:

```js
async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });

  const body = await response.json();
  if (!body.success) {
    const err = new Error(body.error?.message || 'API request failed');
    err.code = body.error?.code;
    err.status = response.status;
    err.requestId = body.meta?.request_id;
    throw err;
  }
  return body.data;
}
```

See `docs/ERROR_CODES.md` for the full error code registry.

---

## 8. Health endpoints

Liveness only:

```http
GET /health/live
```

Response data:

```json
{ "status": "alive" }
```

Runtime dependency checks:

```http
GET /health
GET /health/ready
```

Healthy response data:

```json
{
  "status": "healthy",
  "checks": {
    "database": { "status": "healthy" },
    "cache": { "status": "healthy" },
    "vault": { "status": "healthy" },
    "llm": { "status": "healthy" },
    "email": { "status": "healthy" }
  }
}
```

If any dependency is unhealthy, the endpoint returns HTTP `503`, error code `SERVICE_UNAVAILABLE`, and includes the same diagnostic object in `data`.

---

## 9. Current API boundaries

These are intentional current-state boundaries, not client assumptions to work around silently:

- There are no dedicated RESTful routes like `POST /customers` or `GET /tickets/<id>`. Use `/api/actions` and `/api/data`.
- Service catalog reads are list-only through `/api/data?type=services`; fetch all services and select the ID client-side.
- Addresses and line items do not have top-level read `type` values. Read addresses through customer includes, customer dossiers, or ticket packets. Read line items through ticket includes or ticket packets.
- Lead models exist in the codebase, but no lead HTTP endpoints are currently mounted.
- User isolation is enforced server-side through the authenticated session and database RLS. Clients do not send `user_id` in action payloads.
