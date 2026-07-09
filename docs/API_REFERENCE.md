# CRM Internal Service API

The CRM is a private, workspace-scoped business-data service. It has no browser UI, login endpoint, session store, cookie authentication, public OpenAPI schema, or public application port.

## Network and authentication boundary

Run the application only on the private application network. `python main.py` binds Uvicorn to `127.0.0.1:8000`; a private reverse proxy or sidecar may reach it locally. Do not publish its application port through a public listener.

Every non-health request requires all three headers:

```http
Authorization: Bearer <crm/internal.service_secret from Vault>
X-Workspace-ID: <UUID>
X-Workspace-Timezone: <IANA timezone>
```

The bearer secret is loaded at startup from Vault field `crm/internal.service_secret`. Startup fails if the secret is absent or empty. The service compares it using a constant-time comparison. The workspace ID comes only from the header; JSON payloads, query parameters, cookies, and legacy browser tokens are not identity sources.

`X-Workspace-Timezone` is validated as an IANA timezone and applies only to the request. It determines local-day ticket queries such as `GET /api/data/tickets/today`.

Only the infrastructure health endpoints are unauthenticated:

- `GET /health`
- `GET /health/ready`
- `GET /health/live`

`/`, `/assets/*`, `/auth/*`, `/docs`, `/redoc`, and `/openapi.json` are absent in the production configuration.

## Response envelope

Every domain response uses `{success, data, error, meta}`; the server also returns `X-Request-ID`. IDs are UUIDs, times are ISO 8601 UTC values, and money is integer cents.

## Workspace lifecycle

`POST /api/workspace/provision` creates the workspace from `X-Workspace-ID`. It is idempotent and accepts no body ID.

`DELETE /api/workspace` deletes the workspace from `X-Workspace-ID`. PostgreSQL cascading foreign keys remove its CRM records. It accepts no body ID.

## Domain API

The existing business endpoints remain private and workspace scoped:

- `GET /api/data` and its ticket/customer read convenience routes
- `POST /api/actions` for customer, ticket, catalog, line-item, invoice, note, message, attribute, and address mutations

See the request models in `core/models/` and action dispatch in `api/actions.py` for exact payload contracts. Domain tables are protected by PostgreSQL RLS with `app.current_workspace_id`; no workspace context exposes no tenant data.
