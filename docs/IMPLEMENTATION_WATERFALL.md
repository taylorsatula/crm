# Implementation Waterfall

## CRM System - Module Dependencies and Build Order

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CRM SYSTEM - IMPLEMENTATION WATERFALL                      ║
╚══════════════════════════════════════════════════════════════════════════════╝


┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 0: FOUNDATION (No Dependencies)                                       │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
    │  utils/          │     │  auth/           │     │  api/            │
    │  timezone.py     │     │  types.py        │     │  base.py         │
    │                  │     │  exceptions.py   │     │  (response fmt)  │
    │  UTC utilities   │     │  config.py       │     │                  │
    └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
             │                        │                        │
             ▼                        ▼                        ▼
    ┌──────────────────┐
    │  utils/          │
    │  user_context.py │
    │                  │
    │  Contextvar      │
    └────────┬─────────┘
             │
             ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: INFRASTRUCTURE CLIENTS                                             │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────────┐
                              │  clients/        │
                              │  vault_client.py │
                              │                  │
                              │  Secrets mgmt    │
                              └────────┬─────────┘
                                       │
             ┌─────────────────────────┼─────────────────────────┐
             │                         │                         │
             ▼                         ▼                         ▼
    ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
    │  clients/        │     │  clients/        │     │  (future)        │
    │  postgres_client │     │  valkey_client   │     │  clients/        │
    │                  │     │                  │     │  email_client    │
    │  + Connection    │     │  + Connection    │     │                  │
    │    pooling       │     │    pooling       │     │  Transactional   │
    │  + RLS context   │     │  + Session store │     │  email delivery  │
    │    injection     │     │  + Rate limiting │     │                  │
    │                  │     │                  │     │                  │
    │  DEPENDS ON:     │     │  DEPENDS ON:     │     │  DEPENDS ON:     │
    │  - user_context  │     │  - vault_client  │     │  - vault_client  │
    │  - vault_client  │     │                  │     │                  │
    └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
             │                        │                        │
             ▼                        ▼                        ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: AUTH SYSTEM                                                        │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
    │  auth/           │     │  auth/           │     │  auth/           │
    │  database.py     │     │  rate_limiter.py │     │  security_       │
    │                  │     │                  │     │  logger.py       │
    │  User lookup,    │     │  Token attempt   │     │                  │
    │  session persist │     │  throttling      │     │  Auth event      │
    │                  │     │                  │     │  audit trail     │
    │  DEPENDS ON:     │     │  DEPENDS ON:     │     │                  │
    │  - postgres_     │     │  - valkey_client │     │  DEPENDS ON:     │
    │    client        │     │                  │     │  - postgres_     │
    └────────┬─────────┘     └────────┬─────────┘     │    client        │
             │                        │               └────────┬─────────┘
             │                        │                        │
             └────────────┬───────────┴────────────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  auth/           │
                 │  session.py      │
                 │                  │
                 │  Session token   │
                 │  create/verify   │
                 │  activity extend │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - valkey_client │
                 │  - database      │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  auth/           │
                 │  email_service.py│
                 │                  │
                 │  Magic link      │
                 │  delivery        │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - email_client  │
                 │  - config        │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  auth/           │
                 │  service.py      │
                 │                  │
                 │  Core auth logic │
                 │  - request_link  │
                 │  - verify_token  │
                 │  - create_session│
                 │                  │
                 │  DEPENDS ON:     │
                 │  - database      │
                 │  - session       │
                 │  - rate_limiter  │
                 │  - email_service │
                 │  - security_log  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  auth/           │
                 │  security_       │
                 │  middleware.py   │
                 │                  │
                 │  Request-level   │
                 │  auth enforce    │
                 │  User context    │
                 │  injection       │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - service       │
                 │  - session       │
                 │  - user_context  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  auth/           │
                 │  api.py          │
                 │                  │
                 │  HTTP routes:    │
                 │  /auth/request   │
                 │  /auth/verify    │
                 │  /auth/logout    │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - service       │
                 │  - middleware    │
                 │  - api/base      │
                 └────────┬─────────┘
                          │
                          ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: CORE DOMAIN                                                        │
└─────────────────────────────────────────────────────────────────────────────┘

                 ┌──────────────────┐
                 │  core/           │
                 │  audit.py        │
                 │                  │
                 │  Universal       │
                 │  change tracking │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - postgres_     │
                 │    client        │
                 │  - user_context  │
                 └────────┬─────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  core/models/ (Pydantic models - minimal dependencies)               │
    ├─────────────────────────────────────────────────────────────────────┤
    │                                                                      │
    │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
    │  │ contact │  │ address │  │ service │  │ ticket  │  │ invoice │   │
    │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘   │
    │       │            │            │            │            │         │
    │       └────────────┴─────┬──────┴────────────┴────────────┘         │
    │                          │                                          │
    │                          ▼                                          │
    │                    ┌───────────┐                                    │
    │                    │ line_item │                                    │
    │                    └───────────┘                                    │
    │                                                                      │
    │  Also: note.py, attribute.py, scheduled_message.py, waitlist.py,   │
    │        lead.py                                                      │
    └─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  core/services/ (Business logic)                                     │
    ├─────────────────────────────────────────────────────────────────────┤
    │                                                                      │
    │  ┌────────────────────┐     ┌────────────────────┐                  │
    │  │ contact_service    │     │ catalog_service    │                  │
    │  │                    │     │                    │                  │
    │  │ - create/update    │     │ - service CRUD     │                  │
    │  │ - search           │     │ - pricing logic    │                  │
    │  │ - attribute mgmt   │     │                    │                  │
    │  └─────────┬──────────┘     └─────────┬──────────┘                  │
    │            │                          │                              │
    │            └────────────┬─────────────┘                              │
    │                         ▼                                            │
    │            ┌────────────────────┐                                    │
    │            │ ticket_service     │                                    │
    │            │                    │                                    │
    │            │ - create/modify    │                                    │
    │            │ - close-out flow   │                                    │
    │            │ - status machine   │                                    │
    │            │ - line item mgmt   │                                    │
    │            │                    │                                    │
    │            │ DEPENDS ON:        │                                    │
    │            │ - contact_service  │                                    │
    │            │ - catalog_service  │                                    │
    │            │ - audit            │                                    │
    │            └─────────┬──────────┘                                    │
    │                      │                                               │
    │                      ▼                                               │
    │  ┌────────────────────┐     ┌────────────────────┐                  │
    │  │ invoice_service    │     │ scheduling_service │                  │
    │  │                    │     │                    │                  │
    │  │ - create from      │     │ - recurring appts  │                  │
    │  │   ticket           │     │ - interval logic   │                  │
    │  │ - standalone       │     │ - modify one/all   │                  │
    │  │ - send remote      │     │                    │                  │
    │  │                    │     │ DEPENDS ON:        │                  │
    │  │ DEPENDS ON:        │     │ - ticket_service   │                  │
    │  │ - ticket_service   │     │                    │                  │
    │  └────────────────────┘     └────────────────────┘                  │
    │                                                                      │
    │  Also: message_service (scheduled emails), waitlist_service,         │
    │        lead_service (lead capture, conversion, LLM extraction)      │
    └─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: API ROUTES                                                         │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  api/            │
    │  health.py       │
    │                  │
    │  Infrastructure  │
    │  health checks   │
    │                  │
    │  DEPENDS ON:     │
    │  - all clients   │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  api/            │     │  api/            │
    │  actions.py      │     │  data.py         │
    │                  │     │                  │
    │  State mutations │     │  Read operations │
    │  Domain routing  │     │  Type routing    │
    │  Audit logging   │     │  Expansion       │
    │                  │     │  Pagination      │
    │  DEPENDS ON:     │     │                  │
    │  - all core/     │     │  DEPENDS ON:     │
    │    services      │     │  - all core/     │
    │  - auth/         │     │    services      │
    │    middleware    │     │  - auth/         │
    │  - api/base      │     │    middleware    │
    └────────┬─────────┘     │  - api/base      │
             │               └────────┬─────────┘
             │                        │
             └───────────┬────────────┘
                         │
                         ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: APPLICATION ASSEMBLY                                               │
└─────────────────────────────────────────────────────────────────────────────┘

                 ┌──────────────────┐
                 │  main.py         │
                 │                  │
                 │  FastAPI app     │
                 │  - Mount routes  │
                 │  - Middleware    │
                 │  - Lifespan      │
                 │    (startup/     │
                 │     shutdown)    │
                 │                  │
                 │  DEPENDS ON:     │
                 │  - Everything    │
                 └──────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                         LLM INTEGRATION WATERFALL                             ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  PARALLEL TRACK (Can develop alongside Phase 2-3)                            │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  clients/        │
    │  llm_client.py   │
    │                  │
    │  OpenAI-compat   │
    │  interface       │
    │  (Qwen3 initial) │
    │                  │
    │  DEPENDS ON:     │
    │  - vault_client  │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  core/           │
    │  extraction.py   │
    │                  │
    │  Note → Attrib   │
    │  extraction      │
    │  Prompt mgmt     │
    │                  │
    │  DEPENDS ON:     │
    │  - llm_client    │
    │  - core/models   │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────────────────────────────────────────────┐
    │  Integrates into:                                        │
    │                                                          │
    │  1. ticket_service close-out flow                        │
    │     ticket.close() → extract_attributes(notes)           │
    │                    → present to technician for validation│
    │                    → persist to contact.attributes       │
    │                                                          │
    │  2. lead_service capture flow                            │
    │     lead.create() → extract_lead_data(raw_notes)         │
    │                   → populate editable fields             │
    │                   → user reviews/edits before save       │
    └──────────────────────────────────────────────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                           MCP INTEGRATION WATERFALL                           ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  PARALLEL TRACK (Can develop alongside Phase 3-4)                            │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  api/            │
    │  capabilities.py │
    │                  │
    │  Auto-generated  │
    │  from domain     │
    │  handlers        │
    │                  │
    │  DEPENDS ON:     │
    │  - action_       │
    │    handlers      │
    │  - data_services │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  model_          │
    │  authorization/  │
    │                  │
    │  - queue table   │
    │  - service       │
    │  - API routes    │
    │                  │
    │  DEPENDS ON:     │
    │  - postgres_     │
    │    client        │
    │  - auth          │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  mcp/            │
    │  server.py       │
    │                  │
    │  MCP server      │
    │  entry point     │
    │                  │
    │  DEPENDS ON:     │
    │  - capabilities  │
    │  - authorization │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  mcp/tools/      │     │  mcp/tools/      │
    │  raw.py          │     │  workflows.py    │
    │                  │     │                  │
    │  crm_capabilities│     │  schedule_appt   │
    │  crm_query       │     │  daily_briefing  │
    │  crm_action      │     │  process_lead    │
    │                  │     │  find_customer   │
    │                  │     │  etc.            │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             └───────────┬────────────┘
                         ▼
    ┌──────────────────────────────────────────────────────────┐
    │  templates/authorizations/                                │
    │                                                          │
    │  - queue.html      (list pending authorizations)         │
    │  - detail.html     (review single authorization)         │
    │                                                          │
    │  Web UI for human review of model actions                │
    └──────────────────────────────────────────────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                         STRIPE INTEGRATION WATERFALL                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  PARALLEL TRACK (Can develop alongside Phase 3-4)                            │
│  Zero PCI scope - CRM stores only Stripe reference IDs                       │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  clients/        │
    │  stripe_client.py│
    │                  │
    │  Stripe API      │
    │  wrapper         │
    │  - create_       │
    │    customer      │
    │  - create_       │
    │    checkout_     │
    │    session       │
    │  - verify_       │
    │    webhook       │
    │                  │
    │  DEPENDS ON:     │
    │  - vault_client  │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  api/webhooks/   │
    │  stripe.py       │
    │                  │
    │  Webhook handler │
    │  - Signature     │
    │    verification  │
    │  - Event routing │
    │  - User context  │
    │    from invoice  │
    │                  │
    │  DEPENDS ON:     │
    │  - stripe_client │
    │  - invoice_      │
    │    service       │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────────────────────────────────────────────┐
    │  Schema additions (to existing tables):                  │
    │                                                          │
    │  contacts:                                               │
    │    + stripe_customer_id TEXT    (cus_xxx)                │
    │                                                          │
    │  invoices:                                               │
    │    + stripe_checkout_session_id TEXT  (cs_xxx)           │
    │    + stripe_payment_intent_id TEXT    (pi_xxx)           │
    │                                                          │
    │  No new tables - just reference ID columns               │
    └────────────────────────────────────────────────────────────┘
             │
             ▼
    ┌──────────────────────────────────────────────────────────┐
    │  Integrates into:                                        │
    │                                                          │
    │  1. invoice_service.send()                               │
    │     └── Create/retrieve Stripe Customer                  │
    │     └── Create Checkout Session                          │
    │     └── Store session_id on invoice                      │
    │     └── Include payment_link in email                    │
    │                                                          │
    │  2. Webhook handler: checkout.session.completed          │
    │     └── Verify signature                                 │
    │     └── Extract invoice_id from metadata                 │
    │     └── Set user context                                 │
    │     └── invoice_service.record_payment()                 │
    │                                                          │
    │  3. MCP send_invoice workflow (soft_limit)               │
    │     └── Returns payment_link in response                 │
    └──────────────────────────────────────────────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                              FRONTEND WATERFALL                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  PARALLEL TRACK (Can develop alongside backend phases)                       │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  static/         │
    │  css/base.css    │
    │                  │
    │  Design system   │
    │  Mobile-first    │
    │  Thumb-friendly  │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  templates/      │     │  static/         │
    │  auth/           │     │  js/api.js       │
    │                  │     │                  │
    │  - login.html    │     │  Fetch wrapper   │
    │  - check-email   │     │  Error handling  │
    │    .html         │     │  Response parse  │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             └───────────┬────────────┘
                         ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  templates/      │     │  templates/      │
    │  calendar/       │     │  contacts/       │
    │                  │     │                  │
    │  - day.html      │     │  - list.html     │
    │  - week.html     │     │  - detail.html   │
    │  - month.html    │     │  - search.html   │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             └───────────┬────────────┘
                         ▼
                 ┌──────────────────┐
                 │  templates/      │
                 │  ticket/         │
                 │                  │
                 │  - create.html   │
                 │  - detail.html   │
                 │  - close-out/    │  ← Multi-step wizard
                 │    ├─ step1.html │    (forced completion)
                 │    ├─ step2.html │
                 │    ├─ step3.html │
                 │    └─ confirm    │
                 │      .html       │
                 └────────┬─────────┘
                          │
                          ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  templates/      │     │  templates/      │
    │  invoice/        │     │  messages/       │
    │                  │     │                  │
    │  - create.html   │     │  - scheduled.htm │
    │  - send.html     │     │  - templates.htm │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             └───────────┬────────────┘
                         ▼
                 ┌──────────────────┐
                 │  templates/      │
                 │  leads/          │
                 │                  │
                 │  - capture.html  │  ← Quick freeform entry
                 │  - review.html   │    (LLM extraction review)
                 │  - list.html     │
                 └──────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                          CRITICAL PATH SUMMARY                                ║
╚══════════════════════════════════════════════════════════════════════════════╝

  Phase 0          Phase 1           Phase 2         Phase 3         Phase 4
  ────────         ────────          ────────        ────────        ────────

  timezone    ─┐
               ├──► postgres ──┐
  user_context─┘               │
                               ├──► auth/* ──► core/audit ──┐
  vault ──────────► valkey ────┘                            │
                                                            ├──► api/actions
  api/base ─────────────────────────────────────────────────┤
                                                            ├──► api/data
  auth/types ───► auth/database ──► auth/service ───────────┘
  auth/config     auth/session      auth/middleware
  auth/except     auth/rate_limit   auth/api
                  auth/sec_log


  MINIMUM VIABLE PATH TO FIRST ENDPOINT:
  ═══════════════════════════════════════

  utils/timezone.py ──► utils/user_context.py ──► clients/vault_client.py
                                                           │
           ┌───────────────────────────────────────────────┘
           ▼
  clients/postgres_client.py ──► clients/valkey_client.py
           │                              │
           └──────────────┬───────────────┘
                          ▼
                    api/base.py
                          │
                          ▼
                   api/health.py  ← First testable endpoint
```
