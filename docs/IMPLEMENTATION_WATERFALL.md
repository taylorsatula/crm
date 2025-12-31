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
    │  Also: note.py, attribute.py, scheduled_message.py, waitlist.py    │
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
    │  Also: message_service (scheduled emails), waitlist_service          │
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
    │  Integrates into ticket_service close-out flow           │
    │                                                          │
    │  ticket.close() → extraction.extract_attributes(notes)   │
    │                 → present to technician for validation   │
    │                 → persist to contact.attributes          │
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
    └──────────────────┘     └──────────────────┘


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
