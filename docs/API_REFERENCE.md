# CRM Internal Service API

The CRM is a private, workspace-scoped business-data service. It has no browser UI, login endpoint, session store, cookie authentication, public OpenAPI schema, or public application port.

## Network boundary

Run the application only on the private application network. `python main.py` binds Uvicorn to `127.0.0.1:8000`; a private reverse proxy or sidecar may reach it locally. Do not publish its application port through a public listener.

## Authentication

There are two authentication boundaries: **workspace tokens** for domain routes and a **lifecycle service secret** for provisioning routes. Health endpoints are the only unauthenticated paths.

### Workspace token authentication (domain routes)

Every non-health, non-lifecycle request requires a single header:

```http
Authorization: Bearer <workspace access token>
```

The middleware SHA-256 hashes the bearer credential and looks it up in the `workspace_access_tokens` table. The token must not be revoked or expired. Tokens carry scopes — `read` is required for `GET`/`HEAD`/`OPTIONS`, `write` for all other methods. If the required scope is missing, the server returns 403.

Workspace identity and timezone are resolved from the token's associated workspace row, not from request headers. `X-Workspace-ID` and `X-Workspace-Timezone` headers are **forbidden** on workspace-authenticated requests and return 400 if present.

On each successful request the middleware sets `last_used_at` on the token row and establishes the RLS context (`app.current_workspace_id`) for the duration of the request.

### Lifecycle service secret (provisioning routes)

Routes under `/api/lifecycle/` authenticate with a shared bearer secret:

```http
Authorization: Bearer <crm/lifecycle.service_secret from Vault>
```

The secret is loaded at startup from Vault field `crm/lifecycle.service_secret`. Startup fails if the secret is absent or empty. The service compares it using a constant-time comparison (`hmac.compare_digest`).

### Unauthenticated endpoints

Only infrastructure health endpoints skip authentication:

- `GET /health` — dependency-check diagnostic (database, Vault, LLM, email)
- `GET /health/ready` — same diagnostic check (readiness probe)
- `GET /health/live` — simple liveness probe (always returns `{"status": "alive"}`)

`/`, `/assets/*`, `/auth/*` are absent — no routes are registered for these paths. `/docs`, `/redoc`, and `/openapi.json` are disabled by default (`AppConfig.expose_docs = False`).

## Response envelope

Every domain response uses:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {
    "timestamp": "2026-01-15T14:30:00Z",
    "request_id": "uuid"
  }
}
```

Error responses set `success: false` and populate `error` with `{code, message}`. The `X-Request-ID` response header matches `meta.request_id`. IDs are UUIDs, times are ISO 8601 UTC, and money is integer cents.

## Workspace lifecycle API

All lifecycle routes are authenticated with the lifecycle service secret (see above). They manage workspace provisioning and access token issuance.

### `POST /api/lifecycle/workspaces`

Provision a workspace. Idempotent — re-provisioning updates the timezone.

```json
{
  "workspace_id": "uuid",
  "timezone": "America/Chicago"
}
```

### `DELETE /api/lifecycle/workspaces/{workspace_id}`

Delete a workspace. PostgreSQL cascading foreign keys remove its CRM records.

### `POST /api/lifecycle/workspaces/{workspace_id}/tokens`

Mint a scoped workspace access token. Returns the raw token once — it is not stored, only its SHA-256 hash.

```json
{
  "name": "mira-backend",
  "scopes": ["read", "write"],
  "expires_at": "2027-01-01T00:00:00Z"
}
```

Response includes the raw `token` (prefixed `crm_ws_`), `id`, `issued_at`, and `expires_at`. The caller must store the raw token; subsequent requests authenticate with it.

### `DELETE /api/lifecycle/workspaces/{workspace_id}/tokens/{token_id}`

Revoke an access token. Sets `revoked_at`; the token immediately stops authenticating.

### `PATCH /api/lifecycle/workspaces/{workspace_id}/timezone`

Update the stored timezone for a workspace.

```json
{
  "timezone": "America/New_York"
}
```

## Domain API

All domain routes are workspace-scoped via token authentication. Tables are protected by PostgreSQL RLS with `app.current_workspace_id`; no workspace context exposes no tenant data.

### Read — `GET /api/data`

Generic query endpoint. The `type` query parameter selects the entity:

| `type` | Required params | Optional params |
|--------|----------------|-----------------|
| `customers` | — | `id`, `search`, `limit`, `cursor`, `include` |
| `tickets` | `id`, `customer_id`, or `filter` | `include`, `limit` |
| `services` | — | `filter` |
| `invoices` | `id`, `customer_id`, or `filter` | `limit` |
| `messages` | `id`, `customer_id`, `ticket_id`, or `filter` | `limit` |
| `notes` | `id`, `customer_id`, or `ticket_id` | `limit` |
| `attributes` | `id` or `customer_id` | — |
| `square_sales` | `customer_id` | `limit` |
| `workspace_settings` | — | — |

**Customer includes**: `addresses`, `tickets`, `invoices`, `notes`, `messages`, `attributes`, `square_sales`

**Ticket includes**: `line_items`, `notes`, `messages`

**Ticket filters**: `upcoming`, `all`

**Invoice filters**: `unpaid`, `draft`, `all`

**Message filters**: `due`, `pending`, `sent`, `failed`, `cancelled`, `skipped`

**Service filters**: `active` (default returns all)

Customer listing uses cursor-based pagination (`cursor` + `limit`). `offset` is not supported on customer listings.

### Convenience read routes

| Route | Description |
|-------|-------------|
| `GET /api/data/tickets/today` | Tickets scheduled for today (workspace-local day) |
| `GET /api/data/tickets/current` | Currently clocked-in ticket, or `null` |
| `GET /api/data/today` | Today's tickets as full packets (ticket + customer + address + line items + attributes + notes + messages + invoices + closeout history) |
| `GET /api/data/tickets/{ticket_id}/packet` | Full packet for one ticket, including customer attributes, closeout profile facts, future plans, and follow-up actions |
| `GET /api/data/customers/{customer_id}/dossier` | Complete customer profile (addresses, attributes, closeout profile facts, future plans, actions, tickets, invoices, notes, messages, Square sales) |

### Mutate — `POST /api/actions`

Unified mutation endpoint. Body structure:

```json
{
  "domain": "ticket",
  "action": "create",
  "data": {}
}
```

| Domain | Actions |
|--------|---------|
| `customer` | `create`, `update`, `delete` |
| `ticket` | `create`, `update`, `delete`, `clock_in`, `clock_out`, `closeout`, `cancel` |
| `catalog` | `create`, `update`, `delete` |
| `line_item` | `create`, `update`, `delete` |
| `invoice` | `create_from_ticket`, `resolve_billing_hold`, `send`, `record_payment`, `void` |
| `note` | `create`, `delete` |
| `attribute` | `create`, `delete` |
| `message` | `schedule`, `cancel` |
| `address` | `create`, `update`, `delete` |
| `workspace_settings` | `update` |
| `square_import` | `apply_batch` |
| `workflow` | `book_new_customer_job` |

See the request models in `core/models/` and handler classes in `api/actions.py` for exact payload contracts.

### Structured ticket closeout

`ticket` / `closeout` is the only terminal completion action. It accepts the
canonical `CloseoutRequest`: `ticket_id`, `actual_duration_minutes`, aggregate
`work_reconciliation`, required `customer_capture`, `next_service`, concrete
`follow_up_actions`, and optional residual `technician_summary`. The existing
ticket line items are the quoted baseline. The command records only deviations,
requires an escalation packet containing a disposition and owned action for
damage, safety risk, customer concern/dispute, billing uncertainty, or required
return work, blocks invoice creation while a billing-uncertainty escalation is
not resolved, and releases that hold only through `invoice` / `resolve_billing_hold`
with the existing closeout total and a resolution note, performs final quantity and
price reconciliation transactionally,
stores provenance-bearing profile facts, creates the requested exact booking or
flexible plan, records owed actions, audits the aggregate, and then completes
the ticket. `customer_response` includes `unknown`; empty deviation, profile,
and action lists are valid when no content surfaced.
