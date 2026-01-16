# Implementation Guide

Step-by-step instructions for implementing the CRM system. Each phase builds on the previous and is documented in its own file.

## Design Philosophy

This system is built to **replace Square Appointments**, not become it. Every architectural decision prioritizes long-term maintainability over short-term convenience. We don't take shortcuts that accumulate into the kind of technical debt that makes systems painful to evolve.

Key principles:
- **Fail-fast on infrastructure errors** — silent failures create debugging nightmares
- **RLS at the database level** — user isolation is a guarantee, not a hope
- **Explicit over clever** — boring, predictable code that's easy to understand
- **Simplicity over premature optimization** — implement exactly what's needed, no more

---

## Phase Overview

| Phase | Focus | Files Created |
|-------|-------|---------------|
| [Phase 0](./PHASE_0_FOUNDATION.md) | Foundation | `utils/`, `auth/types.py`, `api/base.py` |
| [Phase 1](./PHASE_1_INFRASTRUCTURE.md) | Infrastructure Clients | `clients/` |
| [Phase 2](./PHASE_2_AUTH.md) | Auth System | `auth/` |
| [Phase 3](./PHASE_3_CORE_DOMAIN.md) | Core Domain | `core/` |
| [Phase 4](./PHASE_4_API_ROUTES.md) | API Routes | `api/` |
| [Phase 5](./PHASE_5_ASSEMBLY.md) | Application Assembly | `main.py` |

## Parallel Tracks

These can be developed alongside the main phases:

- **LLM Integration**: Can start after Phase 1 (needs vault_client)
- **Frontend**: Can start after Phase 0 (needs api/base.py patterns)

## Critical Path

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
   │            │           │           │           │
   │            │           │           │           └── main.py
   │            │           │           └── core/models, core/services
   │            │           └── auth/* (full system)
   │            └── clients/postgres, clients/valkey, clients/vault
   └── utils/timezone, utils/user_context, api/base, auth/types
```

## Verification Checkpoints

Each phase ends with verification steps. Do not proceed until all checks pass.

---

## Architectural Decisions (Resolved)

These decisions have been made and should be reflected throughout implementation:

### 1. Email Provider

**Decision**: Self-hosted mail server with SMTP

Taylor has a mail server configured for good deliverability. We'll use standard SMTP rather than a third-party API (Resend, SendGrid, etc.). The `auth/email_service.py` should use Python's `smtplib` or `aiosmtplib`.

Configuration needed:
- `SMTP_HOST`: Mail server hostname
- `SMTP_PORT`: Port (typically 587 for TLS)
- `SMTP_USER`: Authentication username
- `SMTP_PASSWORD`: Authentication password
- `SMTP_FROM`: From address for system emails

### 2. Attribute Extraction Timing

**Decision**: Synchronous extraction during close-out

When a technician enters notes during ticket close-out, the LLM extraction happens immediately. The extracted attributes are displayed on the confirmation page for the technician to review before finalizing. This provides human-in-the-loop validation without requiring a separate review queue.

Flow:
```
Notes entered → LLM extraction (wait) → Show results on confirmation → Technician approves → Ticket closed
```

Latency is acceptable because:
- Close-out is already a deliberate, multi-step process
- Immediate feedback is more valuable than async review that might never happen
- Local micromodel keeps latency reasonable

### 3. Soft Delete Scope

**Decision**: Soft delete for business entities, hard delete for ephemeral data

| Entity | Delete Strategy | Rationale |
|--------|-----------------|-----------|
| Contact | Soft delete | Historical record, may have linked tickets |
| Ticket | Soft delete | Audit trail, financial records |
| Invoice | Soft delete | Financial/legal requirements |
| Note | Soft delete | Part of customer history |
| LineItem | Soft delete | Part of ticket audit trail |
| Address | Hard delete | Orphaned when contact deleted, no independent history |
| MagicLinkToken | Hard delete | Ephemeral auth tokens, expire anyway |
| ScheduledMessage | Hard delete | Queue items, no value after sent/cancelled |
| Session | Hard delete (via TTL) | Stored in Valkey with automatic expiry |

Soft delete implementation:
- Add `deleted_at TIMESTAMPTZ` column
- RLS policies include `AND deleted_at IS NULL`
- "Delete" operations set `deleted_at = now()`
- Admin queries can include deleted records when needed

### 4. List Endpoints

**Decision**: Simple limit-based lists without pagination

For a single-user business CRM, dataset sizes are naturally bounded:
- Typical service business has 100-1000 active customers
- Tickets per year: 500-5000
- Full list queries complete in <100ms

Simple approach:
```
GET /api/data?type=contacts&limit=100
```

Returns up to `limit` items, newest first. No pagination cursors, no complex state management. If you need more items, increase the limit.

**Benefits**:
- Simpler client code (no cursor tracking, no "load more" logic)
- Simpler server code (no cursor encoding/decoding utilities)
- Works perfectly for the actual scale of the problem
- Can add pagination later if datasets grow beyond expectations

**When to reconsider**: If a single entity type regularly exceeds 10,000 active records.

### 5. Frontend Approach

**Decision**: Server-rendered HTML with vanilla JavaScript enhancement

The frontend uses:
- **FastAPI + Jinja2**: Server-side HTML templating (Jinja2 is Python's standard templating engine, similar to Handlebars/EJS)
- **Vanilla JavaScript**: Progressive enhancement for interactivity
- **No framework**: No React, Vue, etc.—minimizes bundle size for slow mobile connections

Jinja2 basics (for Taylor's reference):
```html
<!-- templates/contacts/list.html -->
{% extends "base.html" %}

{% block content %}
<h1>Contacts</h1>
<ul>
  {% for contact in contacts %}
    <li>{{ contact.name }} - {{ contact.email }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

This approach:
- Works without JavaScript (progressive enhancement)
- Minimal payload size (no framework bundle)
- SEO-friendly if ever needed
- Simple mental model: request → server renders HTML → response

JavaScript is added for:
- Form validation
- Async updates (clock in/out)
- Calendar interactions
- Anything that benefits from not doing a full page reload

### 6. LLM Integration

**Decision**: Local micromodel with remote provider fallback

Architecture from MIRA codebase:
- Primary: Local micromodel (Qwen3 or similar) for low latency, no per-token cost
- Fallback: Remote provider (configurable) when local unavailable or for complex tasks
- Whitelabel interface: Single abstraction that routes to appropriate provider

Configuration:
- `LLM_LOCAL_ENDPOINT`: Local model endpoint
- `LLM_REMOTE_PROVIDER`: Remote provider name (anthropic, openai, etc.)
- `LLM_REMOTE_API_KEY`: Remote provider API key (via Vault)
- `LLM_PREFER_LOCAL`: Whether to try local first (default: true)

The LLM client from MIRA provides:
- Unified interface regardless of provider
- Automatic fallback handling
- Tool/function calling support
- Usage tracking

---

## File Reference

After all phases complete, the project structure will be:

```
crm/
├── main.py
├── api/
│   ├── __init__.py
│   ├── base.py
│   ├── health.py
│   ├── data.py
│   └── actions.py
├── auth/
│   ├── __init__.py
│   ├── types.py
│   ├── exceptions.py
│   ├── config.py
│   ├── database.py
│   ├── rate_limiter.py
│   ├── security_logger.py
│   ├── session.py
│   ├── email_service.py
│   ├── service.py
│   ├── security_middleware.py
│   └── api.py
├── clients/
│   ├── __init__.py
│   ├── vault_client.py
│   ├── postgres_client.py
│   ├── valkey_client.py
│   └── llm_client.py
├── core/
│   ├── __init__.py
│   ├── audit.py
│   ├── extraction.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── contact.py
│   │   ├── address.py
│   │   ├── service.py
│   │   ├── ticket.py
│   │   ├── line_item.py
│   │   ├── invoice.py
│   │   ├── note.py
│   │   ├── attribute.py
│   │   └── scheduled_message.py
│   └── services/
│       ├── __init__.py
│       ├── contact_service.py
│       ├── address_service.py
│       ├── catalog_service.py
│       ├── ticket_service.py
│       ├── invoice_service.py
│       ├── note_service.py
│       ├── attribute_service.py
│       └── message_service.py
├── utils/
│   ├── __init__.py
│   ├── timezone.py
│   └── user_context.py
├── templates/
│   ├── base.html
│   ├── auth/
│   ├── calendar/
│   ├── contacts/
│   ├── tickets/
│   └── ...
├── static/
│   ├── css/
│   └── js/
└── tests/
    └── ...
```
