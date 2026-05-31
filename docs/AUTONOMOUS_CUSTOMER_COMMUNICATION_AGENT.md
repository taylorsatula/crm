# Autonomous Customer Communication Agent

This document supersedes `docs/BUSINESS_VOICE_LEARNING.md` as the design anchor
for customer communication automation. The older document describes one useful
piece: learning the business voice from real interactions. The system we are
building is larger than that. It is an autonomous customer-communication agent
whose leeway expands through explicit trust, category success, and owner
approval.

The goal is not to build a draft assistant. The goal is to build a controlled
operator that can answer customers, use CRM tools, and hand control back to the
owner when it reaches the edge of its authority.

---

## Mental Model

The agent is a customer-facing operator with an authority envelope.

That envelope is controlled by four inputs:

1. **Tenant-wide trust mode** - the broad ceiling on what the model may do.
2. **Per-channel tool policy** - which actions are allowed or blocked on SMS
   and email.
3. **Per-message risk classification** - the category and risk level of the
   current customer message.
4. **Confidence assessment** - whether the model believes it has enough
   context, authority, and business guidance to respond.

The model does not get to override these controls. Prompting may explain the
rules to the model, but deterministic code must enforce tool lockouts, hard
gates, quiet-hours rules, STOP handling, and summon states.

The agent earns proposed expansion of authority. It does not silently promote
itself. Trust can increase after explicit positive owner grading, successful
human release after a summon, and repeated category success. Once the threshold
is met, the system proposes a trust increase. The owner approves or rejects it.

Business voice learning is a subsystem inside this larger control loop. It
improves how the agent writes. It does not decide what the agent is allowed to
do.

---

## Current CRM Grounding

This feature is not a greenfield application. It has to fit into the CRM that
already exists.

The current app is assembled in `main.py` through a container and proxy pattern.
External clients and services are created during startup, stored on
`AppContainer`, and exposed to routers through proxy dictionaries. The
communication agent should follow that shape. Do not construct Telnyx clients,
LLM clients, database clients, or service classes inside request handlers.

The current API has two broad styles:

- Protected owner-facing routes under `/api`, using the shared response shape
  from `api/base.py`.
- Public infrastructure routes such as health checks, with explicit behavior.

Provider webhooks are a third case. They should be public from the session-auth
point of view, but they are not unauthenticated. They must verify provider
signatures before doing work. A webhook handler should ingest and normalize
events; it should not directly send customer replies.

The current data layer uses PostgreSQL RLS for user-scoped business data.
Services derive the current user from `utils.user_context`, insert `user_id`
themselves, and rely on the database connection to set `app.current_user_id`.
New operational communication tables should use that same model.

The current LLM boundary is `clients/llm_client.py`. LLM-backed pieces of this
feature should depend on that boundary and use structured outputs. The current
email boundary is `clients/email_client.py`; outbound email for this feature
should use it rather than introducing another email transport.

The existing `scheduled_messages` table and `MessageService` are useful
reference material, but they are not the conversation system. They model queued
scheduled emails/reminders. This feature needs separate channel thread,
message, summon, policy, trust, directive, raw event, and delayed outbound
queue records.

---

## Scope

### In Scope

- SMS/MMS customer conversations through Telnyx.
- Email customer conversations through the existing email gateway.
- Telnyx webhook ingestion for SMS events, outbound message status, call
  events, missed calls, and transcript-available events.
- Programmatic entrypoints for Telnyx voice/call events.
- A simple in-app SMS interface with customer search, manual phone entry,
  send/receive threads, and pill-bar controls for automation state.
- Owner-configured policy for allowed and blocked tools/actions per channel.
- LLM-assisted cleanup of owner-written policy text before activation.
- Confidence-gated autonomous replies.
- Human summons through an in-app DB-backed queue.
- Human takeover and explicit release back to automation.
- CRM tool use by the model, subject to trust mode, channel policy, customer
  confirmation, and hard gates.
- Delayed outbound sending for autonomous replies.
- Business-voice directives, fixed exemplars, distillation, owner approval,
  directive versioning, diff review, and rollback.
- Initial voice seed from Telnyx message history and mbox archives.
- Telnyx Vault secrets and health checks from day one.
- Telnyx webhook signature verification from day one.
- Quiet-hours controls for agent-initiated outreach.
- STOP/opt-out handling for SMS.

### Out of Scope

- A general email client UI.
- Telnyx number provisioning.
- Autonomous handling of voice-call transcripts.
- Injecting voice transcripts into written conversations.
- Learning from voice transcripts.
- Similar-past-conversation retrieval or similarity scoring.
- Probabilistic exemplar retrieval.
- Arbitrary speculative automation around Telnyx features that do not have a
  current CRM use case.

Voice/call events still need clean programmatic entrypoints because another
module will handle call intelligence. This system should accept and store those
events in a composable way, but it should not try to turn them into autonomous
written follow-ups.

---

## Channels And Thread Semantics

SMS and email do not have the same shape, so they should not be forced into one
thread model.

SMS is a phone-number conversation. It is short-form, often immediate, and
usually belongs to a rolling customer thread.

Email is subject/thread-header based. It may include longer messages, quoted
history, attachments, and slower reply expectations. Email should use the
existing email gateway for inbound and outbound transport.

The implementation should not force these into `scheduled_messages`. That table
can remain the scheduled-reminder system. Customer communication threads need
their own message records because they must carry direction, sender type,
provider message ids, autonomy state, summons, category decisions, and feedback
hooks.

Both channels should share:

- Customer identity resolution.
- Business voice directives.
- Fixed exemplar set.
- Owner policy.
- Trust mode.
- Message category taxonomy.
- Feedback and distillation pipeline.

Both channels should keep separate thread semantics internally.

The model replies on the same channel where the customer contacted the business.
If a customer sends SMS, the model replies by SMS. If a customer sends email,
the model replies by email.

---

## Telnyx Surfaces

Telnyx is the SMS/MMS transport and a source of voice/call events.

The implementation must include:

- Inbound SMS/MMS webhook handling.
- Outbound SMS/MMS sending.
- Outbound message status ingestion.
- Call started/ended event ingestion.
- Missed call event ingestion.
- Recording/transcript available event ingestion.
- Raw event persistence for events not handled directly by this module.
- Signature verification for inbound webhooks.
- Vault-backed Telnyx configuration.
- Health checks that fail loudly when required Telnyx configuration or
  connectivity is unavailable.

`TelnyxClient` should be a first-class external client like the current
database, cache, Vault, LLM, and email clients. It should be built from Vault
configuration during app startup, stored in the app container, included in
health checks, and tested with provider fakes rather than live network calls by
default.

The implementation must not include number provisioning. That has no current
use case in this CRM.

Voice/call event ingestion should be a clean boundary:

```
Telnyx webhook -> verified raw event -> normalized communication event
```

Downstream modules can subscribe to or query these events. This agent should
not add hidden behavior to voice events.

---

## Identity Resolution

Inbound customer messages resolve identity in this order:

1. Exact match on known phone number or email address.
2. Fuzzy customer match.
3. Lead creation.
4. Human review.

Unmatched inbound messages should not be handled autonomously at launch. They
should enter the in-app queue so the owner can initiate the exchange. The
database and service boundaries should leave room for future autonomy on first
contact, but the initial behavior is human initiation only.

Once the owner starts an SMS exchange manually, they can turn on auto-mode. The
model inherits the existing thread context and can continue seamlessly from the
human's messages.

---

## Trust Modes

Trust mode is tenant-wide. It defines the maximum autonomy the model can use.
Per-channel tool policy can further restrict that autonomy.

### `escalate_only`

The model never sends autonomously.

It can classify, summarize, prepare internal context, and summon the owner. It
cannot send a customer-facing reply.

### `reply`

The model can send SMS/email replies when confidence, category, and policy gates
pass.

It can use read-only CRM tools. It cannot mutate CRM state. If it needs to
change a ticket start time, update a customer record, book a job, or perform
another mutation, it must summon the owner.

### `safe_full`

The model can reply and use non-destructive CRM mutation tools.

Allowed examples:

- Create a note.
- Update a customer card.
- Create a ticket after customer confirmation.
- Reschedule a ticket after customer confirmation.

Blocked examples:

- Modify an invoice.
- Cancel a ticket.
- Delete records.
- Any action explicitly blocked by owner policy.

### `dangerous`

The model can perform destructive actions only when the owner has chosen this
mode and channel policy does not block the action.

This mode is still not a free-for-all. Some actions can be blocked with no
exceptions. Customer-facing destructive or consequential actions should still
require confirmation when ambiguous. If the instruction or customer intent is
unclear, the model must summon.

---

## Tool And Action Policy

The owner can configure allowlists and blocklists for tools/actions per channel.
The first-class channels for policy are:

- `sms`
- `email`

Voice is not a policy channel for this implementation.

The owner should be able to write policy in plain language. The system then
runs that text through an LLM cleanup pass that converts vague wording into a
clearer policy proposal. The owner can edit the proposal or provide feedback
for another cleanup pass. Only the final approved policy is persisted.

The final policy must be compiled into deterministic tool rules. Runtime
enforcement must not rely only on the model reading a paragraph in the prompt.

The runtime should use both:

- Prompt context: tells the model what the owner wants.
- Enforced lockouts: prevents disallowed tools/actions from being called.

If a blocked tool is needed to satisfy the customer, the model summons.

---

## Message Categories

The model classifies each inbound message into a category. Classification is per
message, not only per thread.

Initial categories:

- Scheduling.
- Rescheduling.
- Confirmations.
- Pricing.
- Complaints.
- Damage claims.
- Refunds.
- Legal threats.
- Employee accusations.
- Payment/invoice.
- General FAQ.

The category affects:

- Whether the message is hard-gated.
- Whether autonomous reply is allowed.
- Whether CRM tools can be used.
- Trust success counts.
- Future trust-increase proposals.
- Distillation input.

Hard-gated categories summon before any model-authored customer response. Some
messages are not fit for the model to draft. Examples include damage claims,
legal threats, refunds, pricing disputes, harassment, medical/safety issues,
and employee accusations unless the owner later configures otherwise.

The owner can add or revise hard gates through settings.

---

## Confidence Gate

Before a customer-facing autonomous reply, the model must assess whether it has
enough context and authority to respond.

The assessment should consider:

- The message category.
- The active trust mode.
- Channel tool policy.
- Whether the customer is matched.
- The active conversation.
- Customer card details.
- Upcoming scheduled appointments.
- Owner allow/block policy.
- Active voice directives.
- Fixed exemplars.
- Whether a CRM mutation is needed.
- Whether customer confirmation is required.
- Whether the message asks for something outside the model's authority.

The confidence output should be structured data, not prose. At minimum it
should include:

- Category.
- Confidence score.
- Required action, if any.
- Whether a CRM tool is needed.
- Whether customer confirmation is required.
- Whether the message is hard-gated.
- Whether the model may reply.
- Reason codes for summon or send.

The gate result drives code behavior. If `may_reply=false`, no customer-facing
reply is sent.

---

## Runtime Flow

The normal inbound flow is:

1. Receive channel event.
2. Verify webhook signature when applicable.
3. Store raw event.
4. Normalize event into channel-specific message/thread records.
5. Resolve customer identity.
6. If unmatched, queue for human initiation.
7. Load thread state.
8. Classify inbound message category.
9. Assemble context.
10. Resolve trust mode and per-channel tool policy.
11. Run confidence/risk assessment.
12. If hard-gated or low confidence, summon.
13. If tool use is needed, enforce tool policy.
14. If booking/rescheduling is needed, require customer confirmation before
    mutating CRM state.
15. Generate reply.
16. Queue delayed outbound send.
17. Send on the same channel after delay if not cancelled or superseded.
18. Record outcome and feedback hooks.

The flow should be implemented as explicit services with testable boundaries.
Do not bury channel behavior, trust evaluation, tool enforcement, and message
sending in one handler.

The route handler should be thin. For provider webhooks, the route verifies the
signature, calls the event ingestor, and returns the ingestion result. For
owner-facing routes, the route validates request data, calls a service, and
wraps the result with the shared API response shape. The runtime decision tree
belongs in services, not in FastAPI route functions.

---

## Summon And Release

A summon means the agent gives control to the owner.

Summons are stored in the database and exposed through an in-app queue. The
queue should include:

- Channel.
- Customer or lead, if matched.
- Thread reference.
- Current inbound message.
- Recent conversation context.
- Category.
- Confidence assessment.
- Hard-gate reason, if any.
- Tool/action the model wanted but could not perform, if any.

When the owner takes over, the thread remains human-owned until explicitly
released.

Release requires an API endpoint. After release, the model does not immediately
return to deep autonomy. On the next customer turn, the model must summon for
approval before returning to the normal autonomous path. This prevents a brittle
handoff where the model resumes full control immediately after a difficult
interaction.

If the owner never releases the thread, it stays dormant from the agent's point
of view. The owner can reply manually at their leisure.

---

## CRM Tool Use

The model may use CRM actions when trust and policy allow it.

The existing CRM action surface should be reused. The implementation should add
a model-facing tool layer that calls existing services or endpoints instead of
inventing a parallel CRM mutation path.

This matters because the current CRM already centralizes ticket, customer,
invoice, note, line-item, and scheduled-message behavior in service classes and
action handlers. The agent tool layer should be an authorization and orchestration
layer over those services, not a second implementation of CRM mutations.

Tool rules:

- Read-only tools are allowed in `reply`, `safe_full`, and `dangerous` unless
  blocked by channel policy.
- Mutation tools are blocked in `reply`.
- Non-destructive mutation tools are allowed in `safe_full` if not blocked.
- Destructive tools require `dangerous` and must not be blocked.
- Owner blocklist wins over trust mode.
- Ambiguous customer intent summons.
- Booking and rescheduling require customer confirmation before mutation.
- Failed delivery does not lower trust because it is not model behavior.

Examples of safe tools:

- Customer lookup.
- Appointment lookup.
- Availability lookup.
- Create note.
- Update customer card.
- Create ticket after customer confirmation.
- Reschedule ticket after customer confirmation.
- Send SMS.
- Send email.

Examples of destructive or high-risk tools:

- Cancel ticket.
- Modify invoice.
- Delete customer data.
- Void invoice.

---

## Delayed Outbound Sending

Autonomous replies should not feel like chatbot exchanges. Every autonomous
customer-facing reply is queued with a random delay from 1 to 10 minutes, biased
toward 3 to 5 minutes.

The queue should make cancellation possible. Cancellation is not the central
workflow, but delayed send naturally creates a window where the owner or system
can cancel a pending outbound message.

Queued outbound records should include:

- Channel.
- Thread.
- Customer or lead.
- Message body.
- Scheduled send time.
- Reason for delay.
- Autonomy decision metadata.
- Current status.

If a later event makes the message stale before send time, the system should
cancel or summon rather than send stale text.

---

## Quiet Hours And STOP Handling

Quiet hours apply to agent-initiated outreach only.

Default:

- Initiated outreach may send from 7:00am to 7:00pm.
- Timezone comes from `users.timezone`.
- Replies to customer-initiated messages may send at any time.

If a customer messages at 3:00am and the agent can reliably answer within its
authority, it may reply in the moment.

SMS STOP handling is required. If a customer opts out, the system must persist
that state and prevent further non-permitted SMS sends to that number. This is
not treated as a trust failure.

---

## Context Composition

Runtime context should be assembled from small, explicit providers. The goal is
to make it easy to add, remove, or reorder context without rewriting the agent.

Initial context providers:

- Active conversation.
- Customer card details.
- Owner allow/block policy.
- Scheduled upcoming appointments.
- Active business voice directives.
- Fixed exemplar set.

The context builder should be deterministic and inspectable. It should be clear
which provider contributed which content.

Do not implement similar-conversation retrieval for this version. The exemplar
set is fixed and always included.

---

## Business Voice Directives

Voice directives tell the model how the business communicates.

They are tenant-global, with contextual modifications by channel. There is one
business voice, but SMS and email can express it differently.

Directives are injected into every autonomous reply context.

Fixed exemplars are also included every time. Do not retrieve exemplars by
similarity. That adds maintenance burden and makes behavior harder to debug.

### Initial Voice Seed

The initial voice seed is generated from existing written communication before
the agent handles customers.

Sources:

- Telnyx message history.
- mbox archives.

The purpose is to extract:

- Baseline directives.
- Fixed exemplars.
- Style summary.
- Source metadata.

The mbox import should not filter by configured sender addresses for now.

The output should be reviewed by the owner before activation. Once approved, it
becomes the first active directive version and fixed exemplar set.

---

## Distillation

Distillation turns real interactions into better directives.

Inputs:

- Human takeovers.
- Owner rejections with required feedback.
- Owner approvals.
- Positive grading.
- Successful category interactions.
- Summon/release outcomes.

Distillation produces a full directive rewrite, not a collection of tiny patch
fragments. When the owner asks for revisions to the distillation output, the
distiller prompt must state that only the areas identified by the owner should
change. Unmentioned areas should remain stable between attempts.

No distilled directive becomes active without owner approval.

Directive versions must support:

- Diff review.
- Approval.
- Rejection.
- Manual edit.
- Rollback.

Rollback restores directive text. It does not roll back trust state.

---

## Trust Growth And Decline

Trust increases by proposal, not automatically.

Trust-increase signals:

- Explicit positive owner grading.
- Successful human release after summon.
- Repeated category success.

The default threshold for repeated category success is 15 approved/successful
interactions in the same category.

When the threshold is met, the system proposes a trust increase. The owner must
approve it.

Trust-decrease signals:

- Rejection.
- Customer complaint.
- Summon after bad assessment.
- Delivery to wrong customer.
- Policy/risk category hit.
- Unsafe or incorrect content.

Human edits before send do not count against trust. Editing is part of the
training process.

Delivery failures do not count against trust. They are transport failures, not
model behavior.

---

## Owner-Facing UI

The first UI surfaces are intentionally small.

### SMS Threads

The SMS view should support:

- Customer search.
- Manual phone entry.
- Thread list.
- Thread view.
- Send and receive SMS messages.
- Pill-bar controls for automation state.
- Auto-mode toggle.
- Summon state.
- Release control when a thread is human-owned.

If the owner starts a thread manually and enables auto-mode, the model inherits
the thread as context.

### Summon Queue

The summon queue should support:

- List pending summons.
- Open summon detail.
- Show why the model summoned.
- Show relevant conversation/customer context.
- Let owner reply manually.
- Let owner release the thread back to automation.
- Capture owner feedback.

### Policy Settings

Policy settings should support:

- Plain-language owner input.
- LLM-cleaned proposal.
- Owner feedback/edit loop.
- Final approval.
- Per-channel tool allow/block controls.
- Hard-gate category settings.

Only final approved policy is stored.

### Directive Review

Directive review should support:

- Proposed full directive text.
- Diff against active directive version.
- Owner edit.
- Owner feedback for another revision pass.
- Approve.
- Reject.
- Roll back to prior directive text.

---

## Data Model Direction

Exact schema should be reconciled with the current database before
implementation, but the system needs these concepts:

- Channel thread records for SMS and email.
- Channel message records.
- Raw provider event records.
- Normalized communication event records.
- Pending outbound message queue.
- Summon queue.
- Human takeover/release state.
- Message category records or enum-like constraints.
- Tenant trust setting.
- Per-channel tool policy.
- Compiled tool allow/block rules.
- Owner policy text.
- Business voice directive versions.
- Fixed exemplars.
- Distillation runs.
- Feedback events.
- SMS opt-out records.

The implementation should keep raw provider events separate from normalized
domain records. Raw events help debug provider behavior. Normalized records
drive CRM behavior.

For user-visible operational tables, follow the current schema pattern:

- `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`;
- RLS enabled;
- policy checks against `current_setting('app.current_user_id', true)::uuid`;
- indexes on user id plus status, foreign keys, or created/scheduled time;
- timestamps stored in UTC;
- table names added to the test reset fixture.

For append-only provider telemetry, either use RLS or explicitly document why
the table is `NO RLS`, as the current audit/message log tables do. Do not leave
that choice implicit.

---

## Service Boundaries

Expected service boundaries:

- `TelnyxClient` - outbound Telnyx calls and health checks.
- `TelnyxWebhookVerifier` - signature verification.
- `CommunicationEventIngestor` - raw event persistence and normalization.
- `SmsThreadService` - SMS thread/message lifecycle.
- `EmailThreadService` - email thread/message lifecycle.
- `IdentityResolutionService` - customer/lead matching.
- `CommunicationPolicyService` - owner policy and compiled tool rules.
- `TrustService` - tenant trust mode, category success, trust proposals.
- `MessageCategorizer` - per-message category classification.
- `ContextBuilder` - deterministic context assembly.
- `ConfidenceGate` - structured assessment before reply.
- `CustomerAgentRuntime` - orchestrates a single inbound message decision.
- `OutboundQueueService` - delayed sends and cancellation.
- `SummonService` - summon creation, owner takeover, release.
- `DirectiveService` - active directives, versions, rollback.
- `DistillationService` - directive synthesis and revision attempts.
- `VoiceSeedService` - Telnyx history and mbox import into initial directives.

These services can share lower-level clients and existing CRM services. They
should not duplicate customer, ticket, invoice, note, or scheduled-message
logic.

---

## API Direction

Expected API surfaces:

- Telnyx webhook endpoint for provider events.
- Email gateway inbound entrypoint, if the gateway does not already call one.
- SMS thread list/detail endpoints.
- Send manual SMS endpoint.
- Toggle auto-mode endpoint.
- Summon queue list/detail endpoints.
- Human reply endpoint.
- Release thread endpoint.
- Policy draft/cleanup/approve endpoints.
- Tool rule settings endpoints.
- Directive version list/detail endpoints.
- Distillation run create/revise/approve/reject endpoints.
- Rollback directive endpoint.
- Trust proposal list/approve/reject endpoints.

The existing unified action/data patterns should be reused where they fit. New
routes are acceptable where webhook semantics or UI-specific reads need clearer
interfaces.

Owner/UI endpoints should live under `/api` and use the shared response
contract. Provider webhooks should not be hidden inside `/api/actions`; they
need dedicated routes because they have provider authentication, raw event
durability, and retry semantics.

---

## Infrastructure And Configuration

Required Telnyx configuration should live in Vault.

Expected configuration values:

- Telnyx API key.
- Telnyx webhook signing material.
- Telnyx messaging profile or equivalent send configuration.
- Business SMS number or numbers.
- Telnyx health-check target, if needed.

The concrete Vault path should follow the existing convention: callers pass a
relative service path and `VaultClient` scopes it under `crm/`. A
`get_telnyx_config()` helper should load required fields from `crm/telnyx`,
cache them consistently with the existing config helpers, and fail fast when a
required field is missing.

Health checks should cover:

- Database.
- Cache.
- Vault.
- LLM.
- Email gateway.
- Telnyx.

Telnyx should be added to the same health-check map as the current runtime
clients. `/health` and `/health/ready` should report Telnyx failures as
dependency failures. `/health/live` should remain process-only.

---

## Implementation Path

### 1. Schema And Models

Add the communication tables, Pydantic models, and tests first.

This establishes the domain contract before provider logic or agent orchestration
is added.

Also update the test database reset fixture in the same pass. A schema change
without reset coverage will produce order-dependent service tests once the new
tables start storing state.

### 2. Provider Boundaries

Implement Telnyx client, webhook verification, raw event storage, and normalized
event ingestion.

Wire Telnyx health checks through app startup and health routes.

Use the existing email gateway for email transport. Do not build an email UI.

### 3. Thread And Identity Services

Implement SMS and email thread semantics separately.

Add identity resolution:

1. Exact phone/email.
2. Fuzzy customer match.
3. Lead creation.
4. Human review queue.

Unmatched messages should queue for owner initiation.

### 4. Policy And Trust

Implement tenant-wide trust mode.

Implement per-channel tool policy.

Implement policy cleanup:

1. Owner writes plain language.
2. LLM proposes cleaned policy.
3. Owner edits or provides feedback.
4. Final approved policy is stored.
5. Policy compiles into deterministic allow/block rules.

Implement category success counts and trust proposals with a default threshold
of 15.

### 5. Agent Runtime

Implement category classification, context composition, confidence gate, tool
enforcement, summon behavior, and delayed outbound queue.

The runtime should be testable without live Telnyx or live LLM calls by using
fake clients and deterministic model outputs.

Use `LLMClient.generate()` for policy cleanup, message categorization,
confidence assessment, distillation, and voice seed synthesis. Require
structured JSON outputs at those service boundaries so tests can assert exact
state transitions instead of parsing prose.

### 6. Human Surfaces

Implement:

- SMS thread UI.
- Auto-mode pill controls.
- Summon queue.
- Release endpoint and UI control.
- Policy settings.
- Directive review.

Keep the UI focused on operating the system, not explaining the system.

### 7. Voice Seed And Distillation

Implement Telnyx history import and mbox import for the initial voice seed.

Implement directive versions, fixed exemplars, distillation runs, owner review,
revision attempts, approval, rejection, and rollback.

### 8. Production Verification

Production readiness means:

- Telnyx secrets are Vault-backed.
- Telnyx webhook signatures are verified.
- Telnyx health checks exist.
- Email gateway path is exercised.
- Database RLS works for new tables.
- Outbound queue handles delay, cancellation, stale messages, and send failure.
- STOP handling blocks SMS sends.
- Quiet hours block only initiated outreach.
- Summons prevent customer-facing model replies.
- Release requires the next model turn to summon for approval.
- Tool lockouts are enforced in code.
- Destructive actions cannot execute outside allowed trust and policy.
- Directive activation requires owner approval.
- Rollback restores directive text.

---

## Testing Requirements

Use hermetic tests for the core behavior.

Follow the repo's current test style:

- client tests use fakes or HTTP mocks and assert request payloads;
- health tests use simple objects with `health_check()` methods;
- service tests use real DB fixtures and `as_test_user`;
- RLS tests switch between the primary and secondary test users;
- LLM-backed service tests use deterministic fake LLM responses.

Required test groups:

- Schema/model validation.
- Identity resolution order.
- SMS thread creation and message append.
- Email thread creation and message append.
- Telnyx webhook signature verification.
- Raw event persistence.
- Normalized event ingestion.
- Trust mode enforcement.
- Per-channel tool allow/block enforcement.
- Policy cleanup approval flow.
- Category classification parsing.
- Hard-gated category summon.
- `escalate_only` never sends.
- `reply` blocks CRM mutations.
- `safe_full` allows non-destructive confirmed mutations.
- `dangerous` still respects explicit blocklist.
- Booking/rescheduling requires customer confirmation.
- Human takeover blocks autonomy.
- Release causes next turn approval summon.
- Delayed outbound scheduling.
- Delayed outbound cancellation.
- Quiet-hours behavior for initiated outreach.
- Reply-at-any-time behavior for customer-initiated messages.
- STOP opt-out behavior.
- Directive diff/approval/rollback.
- Distillation revision preserves untouched text.
- Initial voice seed from Telnyx history.
- Initial voice seed from mbox.

Live provider tests should be gated behind explicit environment variables and
should not run in the normal test suite.

---

## Design Constraints

Keep the surfaces composable.

Do not hide unrelated behavior behind provider webhooks. A Telnyx call event
should not accidentally trigger written follow-up automation. It should become a
stored event that another module can consume.

Do not build similarity retrieval, dynamic exemplar surfacing, or a generalized
automation graph for this version. The maintainable path is fixed exemplars,
explicit directives, explicit policy, and deterministic gates.

Do not treat the LLM as the enforcement boundary. The model can recommend,
classify, and explain. Code decides whether a message sends or a tool executes.

Do not let trust grow silently. The model earns proposals. The owner grants
authority.

------------------------------

## Technical Reference For Implementation

This section is for the implementation pass. It is intentionally more
mechanical than the prose above. Use it to write red tests before implementation
and to keep the first build grounded in current repo patterns.

### Current Repo Touchpoints

- `main.py` assembles runtime dependencies through `AppContainer`, `_ContainerRef`,
  `_ContainerProxy`, `_service_proxies()`, and `_health_proxies()`. New clients
  and services must be wired there instead of being constructed inside route
  handlers.
- `api/base.py` defines the response contract. Protected owner/UI endpoints
  should return `success_response(...).model_dump(mode="json")` and use the
  request id from `request.state.request_id`.
- `api/middleware.py` sets `X-Request-ID` and `request.state.request_id`.
  Tests should assert request id propagation for new routes.
- `auth/security_middleware.py` protects `/api/*` by default. Provider webhooks
  need explicit public-path treatment plus their own signature verification.
- `api/actions.py` and `api/data.py` provide generic action/read patterns.
  Reuse those patterns for ordinary owner-facing reads and mutations where
  they fit. Use dedicated route modules for provider webhooks and thread-like
  UI flows where generic `/api/actions` would obscure behavior.
- `schema.sql` uses user-scoped tables with `user_id`, RLS policies based on
  `current_setting('app.current_user_id', true)::uuid`, and explicit indexes.
  Operational communication-agent tables should follow that pattern.
- `audit_log` and `message_log` are append-only admin/log tables without RLS.
  Only use `NO RLS` for raw provider telemetry or append-only logs, and document
  that choice in the schema.
- Services derive `user_id` from `utils.user_context.get_current_user_id()` on
  insert. Do not pass `user_id` through public service method parameters.
- Services use direct SQL through `PostgresClient`, `uuid4()`, `now_utc()`,
  Pydantic `model_validate(row)`, `ValueError` for missing mutation targets,
  and `AuditLogger.log_change()` after state changes.
- `tests/conftest.py` truncates all mutable tables in `reset_db_state`. Every
  new table, including append-only test logs, must be added there.
- `clients/vault_client.py` scopes secrets under `crm/<service>`. Telnyx config
  should use a `crm/telnyx` secret path and a helper similar to existing email
  and LLM config helpers.
- `api/health.py` duck-types health checks by calling `.health_check()` on each
  object in `AppContainer.health_checks`. `TelnyxClient` must implement
  `health_check() -> bool` and be included in health proxies.
- `clients/email_client.py` is the outbound email transport. Do not build a new
  email transport or an email client UI.
- `clients/llm_client.py` is the LLM boundary. LLM-backed services should use
  `LLMClient.generate()` with structured outputs and hermetic fakes in tests.
  Do not require live LLM calls in normal tests.

### Required New Modules

Add concrete names during implementation, but keep these ownership boundaries:

- `clients/telnyx_client.py`
  - `TelnyxClient`
  - `TelnyxError`
  - outbound SMS/MMS send
  - provider health check
- `clients/vault_client.py`
  - `get_telnyx_config()`
  - required fields loaded from `crm/telnyx`
- `api/telnyx_webhooks.py`
  - public Telnyx webhook endpoint
  - signature verification
  - raw-event-first ingestion
- `api/communications.py`
  - protected owner/UI endpoints for SMS threads, summon queue, policy,
    directives, trust proposals, and delayed outbounds
- `core/models/communication.py`
  - thread, message, event, outbound, summon, policy, directive, trust models
- `core/services/communication_event_ingestor.py`
  - raw event persistence and normalization
- `core/services/sms_thread_service.py`
  - SMS thread/message lifecycle
- `core/services/email_thread_service.py`
  - email thread/message lifecycle
- `core/services/identity_resolution_service.py`
  - exact match, fuzzy match, lead creation, human-review fallback
- `core/services/communication_policy_service.py`
  - owner policy cleanup, approval, compiled tool allow/block rules
- `core/services/trust_service.py`
  - tenant trust mode, category success counts, trust proposals
- `core/services/message_categorizer.py`
  - LLM-backed per-message category classification
- `core/services/context_builder.py`
  - deterministic context provider assembly
- `core/services/confidence_gate.py`
  - LLM-backed structured gate result
- `core/services/customer_agent_runtime.py`
  - orchestration for one inbound message
- `core/services/outbound_queue_service.py`
  - delayed sends, cancellation, stale-message handling
- `core/services/summon_service.py`
  - summon creation, takeover, release, next-turn approval requirement
- `core/services/directive_service.py`
  - active directives, versions, rollback
- `core/services/distillation_service.py`
  - directive synthesis, revision, owner approval
- `core/services/voice_seed_service.py`
  - Telnyx history and mbox seed import

### Required Schema Concepts

Use the existing naming style and reconcile exact table names during the schema
pass. These concepts must exist:

- `communication_raw_events`
  - append-only provider payload storage
  - provider, event_type, provider_event_id, payload JSONB, received_at
  - signature verification result metadata
  - `NO RLS` only if treated as provider telemetry; otherwise use RLS
- `communication_events`
  - normalized event records
  - user_id, provider, channel, event_type, raw_event_id, customer_id, lead_id
  - status, occurred_at, created_at
- `sms_threads`
  - user_id, customer_id nullable, lead_id nullable, phone_number
  - autonomy_state: `human_owned`, `auto_enabled`, `summoned`, `dormant`
  - release_pending_approval boolean
  - created_at, updated_at
- `email_threads`
  - user_id, customer_id nullable, lead_id nullable, email address
  - provider thread/message ids where available
  - autonomy_state and release_pending_approval
- `communication_messages`
  - user_id, thread_type, thread_id, channel
  - direction: `inbound`, `outbound`
  - sender_type: `customer`, `owner`, `agent`, `provider`
  - body, subject nullable, provider_message_id nullable
  - category nullable, created_at, sent_at/delivered_at nullable
- `outbound_message_queue`
  - user_id, channel, thread reference, customer_id/lead_id nullable
  - body/subject, scheduled_for, status
  - autonomy_decision JSONB
  - cancel/stale reason fields
- `summons`
  - user_id, channel, thread reference, customer_id/lead_id nullable
  - inbound_message_id, category, confidence JSONB, reason, status
  - owner response/decision fields
  - release tracking
- `communication_policy`
  - user_id, trust_mode, owner_policy_text, cleaned_policy_text
  - status: `draft`, `active`
  - updated_at
- `communication_tool_rules`
  - user_id, channel, tool_name, rule: `allow` or `block`
  - source: `compiled_policy`, `manual`
- `trust_category_stats`
  - user_id, category, success_count, negative_count
  - last_success_at, last_negative_at
- `trust_proposals`
  - user_id, proposed_mode or proposed_rule, reason, evidence JSONB
  - status: `pending`, `approved`, `rejected`
- `business_voice_directive_versions`
  - user_id, version_number, directive_text, exemplars JSONB
  - status: `draft`, `active`, `rejected`, `rolled_back`
  - created_at, approved_at
- `distillation_runs`
  - user_id, input_summary JSONB, proposed_directive_text
  - revision_instructions, status
- `feedback_events`
  - user_id, message_id/thread reference, category
  - signal_type: positive grade, rejection, complaint, successful release,
    category success, bad assessment, wrong customer, policy hit
  - notes, created_at
- `sms_opt_outs`
  - user_id, phone_number, opted_out_at, source_message_id

Every user-visible operational table must:

- include `user_id`;
- enable RLS;
- include a policy using `current_setting('app.current_user_id', true)::uuid`;
- have indexes for common owner UI and runtime lookups;
- be added to `tests/conftest.py::reset_db_state`;
- have model/service tests for RLS isolation.

### Required API Surfaces

Provider webhooks:

- `POST /webhooks/telnyx`
  - public path, not session-authenticated
  - verifies Telnyx signature before processing
  - stores raw event first
  - returns a minimal success response after durable ingestion
- Email inbound endpoint
  - only if the existing gateway needs this app to expose one
  - public path with gateway authentication
  - raw inbound payload first, then normalized email thread/message

Protected owner/UI routes under `/api`:

- `GET /api/communications/sms/threads`
- `POST /api/communications/sms/threads`
  - create or open manual thread by customer id or phone number
- `GET /api/communications/sms/threads/{thread_id}`
- `POST /api/communications/sms/threads/{thread_id}/messages`
  - owner manual send
- `POST /api/communications/sms/threads/{thread_id}/auto-mode`
  - enable/disable auto-mode
- `GET /api/communications/summons`
- `GET /api/communications/summons/{summon_id}`
- `POST /api/communications/summons/{summon_id}/reply`
  - owner reply while thread is human-owned
- `POST /api/communications/threads/{thread_type}/{thread_id}/release`
  - release to model; sets next-turn approval requirement
- `GET /api/communications/outbound`
  - list delayed pending outbound messages
- `POST /api/communications/outbound/{outbound_id}/cancel`
- `GET /api/communications/policy`
- `POST /api/communications/policy/draft`
  - store owner plain-language draft and request cleanup
- `POST /api/communications/policy/refine`
  - owner feedback on cleanup proposal
- `POST /api/communications/policy/approve`
  - activate final cleaned policy and compiled tool rules
- `GET /api/communications/tool-rules`
- `PUT /api/communications/tool-rules`
- `GET /api/communications/directives`
- `POST /api/communications/directives/seed`
  - run/review initial Telnyx + mbox seed flow
- `POST /api/communications/distillation-runs`
- `POST /api/communications/distillation-runs/{run_id}/revise`
- `POST /api/communications/distillation-runs/{run_id}/approve`
- `POST /api/communications/distillation-runs/{run_id}/reject`
- `POST /api/communications/directives/{version_id}/rollback`
- `GET /api/communications/trust-proposals`
- `POST /api/communications/trust-proposals/{proposal_id}/approve`
- `POST /api/communications/trust-proposals/{proposal_id}/reject`

Model-facing CRM tools:

- must call existing CRM services or existing action handlers;
- must not duplicate customer/ticket/invoice/note mutation logic;
- must pass through `CommunicationPolicyService` before execution;
- must record attempted, allowed, blocked, and executed actions for audit.

### Decision Tree: Provider Event Entry

```text
Provider event arrives
|
+-- provider == telnyx?
|   |
|   +-- signature valid?
|       |
|       +-- no --> reject request; store nothing except security log if available
|       |
|       +-- yes --> store raw event
|                 |
|                 +-- event is inbound SMS/MMS? ----------> SMS inbound tree
|                 +-- event is outbound SMS status? ------> outbound status tree
|                 +-- event is call/missed/transcript? ---> voice event tree
|                 +-- unknown event? ---------------------> keep raw event; mark ignored
|
+-- provider == email_gateway?
    |
    +-- gateway auth valid?
        |
        +-- no --> reject request
        |
        +-- yes --> store raw event
                  |
                  +-- inbound email? ------> email inbound tree
                  +-- delivery status? ----> outbound status tree
                  +-- unknown event? ------> keep raw event; mark ignored
```

Red-test assertions:

- invalid Telnyx signature does not create normalized events;
- valid Telnyx inbound SMS stores raw event before normalized message;
- unknown valid Telnyx event is durable but does not trigger automation;
- provider webhook routes do not require session auth;
- provider webhook routes still include request id behavior.

### Decision Tree: SMS Inbound Message

```text
Inbound SMS/MMS normalized
|
+-- phone number has STOP opt-out command?
|   |
|   +-- yes --> persist opt-out; do not run agent; optionally acknowledge per provider rules
|   |
|   +-- no --> continue
|
+-- resolve identity
    |
    +-- exact customer phone match? ----> attach customer
    +-- fuzzy customer match? ----------> attach candidate if confidence rule passes
    +-- lead creation possible? --------> create/attach lead
    +-- otherwise ----------------------> human initiation queue; stop
|
+-- thread exists for phone/customer?
    |
    +-- no --> create sms_thread
    +-- yes --> append message
|
+-- thread autonomy_state
    |
    +-- human_owned/dormant --> store inbound; summon/queue for owner; stop
    +-- summoned -----------> store inbound; append to existing summon; stop
    +-- auto_enabled -------> agent runtime tree
```

Red-test assertions:

- STOP creates `sms_opt_outs` and blocks agent runtime;
- exact customer match beats fuzzy match;
- unmatched inbound creates human-review/summon state and no outbound message;
- human-owned thread never invokes autonomous send;
- auto-enabled matched thread invokes category/classification path.

### Decision Tree: Email Inbound Message

```text
Inbound email normalized
|
+-- resolve thread by provider thread id / headers
|   |
|   +-- found --> append to email_thread
|   +-- not found --> create email_thread after identity resolution
|
+-- resolve identity
    |
    +-- exact customer email match? ----> attach customer
    +-- fuzzy customer match? ----------> attach candidate if confidence rule passes
    +-- lead creation possible? --------> create/attach lead
    +-- otherwise ----------------------> human initiation queue; stop
|
+-- email_thread autonomy_state
    |
    +-- human_owned/dormant --> store inbound; summon/queue for owner; stop
    +-- summoned -----------> store inbound; append to existing summon; stop
    +-- auto_enabled -------> agent runtime tree
```

Red-test assertions:

- email uses email-thread semantics, not SMS phone-thread semantics;
- reply channel remains email;
- inbound email does not require an email-client UI;
- unmatched inbound email does not send autonomously.

### Decision Tree: Telnyx Voice/Call Event

```text
Telnyx call/missed/transcript event normalized
|
+-- store raw event
|
+-- create normalized communication_event
|
+-- attach customer if exact phone match exists
|
+-- event type
    |
    +-- call started/ended ------> persist only
    +-- missed call ------------> persist only
    +-- transcript available ---> persist pointer/metadata only
    +-- other ------------------> persist ignored/unknown
|
+-- never inject into written conversation
+-- never trigger autonomous follow-up
+-- never enter voice-learning corpus
```

Red-test assertions:

- transcript event creates no SMS/email outbound;
- transcript event is not included in context builder output;
- call events remain queryable for other modules.

### Decision Tree: Outbound Provider Status Event

```text
Outbound status event normalized
|
+-- match provider_message_id to queued/sent outbound
    |
    +-- no match --> store normalized event; mark unmatched; stop
    |
    +-- match found
        |
        +-- provider status == delivered/sent
        |   |
        |   +-- mark outbound delivered/sent
        |   +-- do not change trust by delivery alone
        |
        +-- provider status == failed/rejected/bounced
        |   |
        |   +-- mark outbound failed
        |   +-- preserve provider error
        |   +-- do not decrease trust
        |
        +-- provider status == unknown/intermediate
            |
            +-- record status event
            +-- leave outbound in current terminal/non-terminal state as appropriate
```

Red-test assertions:

- unmatched status events are durable and do not crash ingestion;
- delivery success does not increase trust by itself;
- provider failure does not decrease trust;
- provider error details are stored for operator debugging.

### Decision Tree: Agent Runtime

```text
Agent runtime starts for matched inbound written message
|
+-- active trust_mode == escalate_only?
|   |
|   +-- yes --> create summon; no reply; stop
|
+-- thread.release_pending_approval == true?
|   |
|   +-- yes --> generate internal assessment; create approval summon; no send; stop
|
+-- classify message category
|
+-- category hard-gated?
|   |
|   +-- yes --> create summon; no draft/customer reply; stop
|
+-- build context
|   |
|   +-- active conversation
|   +-- customer card details
|   +-- owner policy
|   +-- upcoming appointments
|   +-- active directives
|   +-- fixed exemplars
|
+-- run confidence gate
    |
    +-- may_reply == false --> create summon; no send; stop
    |
    +-- may_reply == true
        |
        +-- model needs CRM tool? ----> tool policy tree
        +-- no tool needed ----------> generate reply -> outbound queue tree
```

Red-test assertions:

- `escalate_only` never sends even with high confidence;
- release-pending approval creates summon on next turn;
- hard-gated category does not generate customer-facing draft;
- `may_reply=false` cannot create outbound queue records;
- context builder output identifies each provider section.

### Decision Tree: Tool Policy Enforcement

```text
Model requests tool/action
|
+-- owner blocklist contains tool for channel?
|   |
|   +-- yes --> block tool; create summon; stop
|
+-- trust_mode
    |
    +-- escalate_only --> block all customer-facing sends/tools; summon
    |
    +-- reply
    |   |
    |   +-- read-only tool? ----> allow
    |   +-- mutation tool? -----> block; summon
    |
    +-- safe_full
    |   |
    |   +-- read-only tool? ----------------------> allow
    |   +-- non-destructive mutation? ------------> confirmation tree if needed
    |   +-- destructive/high-risk mutation? ------> block; summon
    |
    +-- dangerous
        |
        +-- explicitly blocked no-exceptions? ----> block; summon
        +-- ambiguous customer intent? -----------> summon
        +-- customer-facing consequential action? -> confirmation tree if needed
        +-- otherwise ----------------------------> allow
```

Red-test assertions:

- blocklist wins over `dangerous`;
- `reply` mode permits read-only lookup and blocks ticket mutation;
- `safe_full` permits create note and confirmed reschedule;
- destructive action outside `dangerous` always blocks;
- blocked tool creates summon with blocked tool metadata.

### Decision Tree: Booking Or Rescheduling

```text
Model wants booking/rescheduling mutation
|
+-- customer has clearly confirmed exact slot/details?
|   |
|   +-- no --> send same-channel confirmation question if reply is allowed
|   |          OR summon if confirmation question is not allowed
|   |
|   +-- yes
|       |
|       +-- tool allowed by trust/channel policy?
|           |
|           +-- no --> summon
|           |
|           +-- yes --> execute CRM mutation through existing service/action path
|                     |
|                     +-- mutation succeeds --> send delayed confirmation reply
|                     +-- mutation fails ----> summon; do not improvise
```

Red-test assertions:

- model cannot create/reschedule ticket before customer confirmation;
- confirmed reschedule in `reply` still summons because mutation is blocked;
- confirmed reschedule in `safe_full` can execute if channel policy allows;
- mutation failure does not lower trust and does not send false confirmation.

### Decision Tree: Summon, Takeover, Release

```text
Summon created
|
+-- status = pending
+-- thread.autonomy_state = summoned
+-- customer-facing model send disabled
|
+-- owner opens summon
    |
    +-- owner replies manually
    |   |
    |   +-- send on same channel
    |   +-- record takeover feedback signal
    |   +-- thread remains human_owned
    |
    +-- owner dismisses/handles outside system
    |   |
    |   +-- thread remains human_owned or dormant
    |
    +-- owner releases thread
        |
        +-- thread.autonomy_state = auto_enabled
        +-- release_pending_approval = true
        +-- next inbound customer turn must create approval summon
```

Red-test assertions:

- pending summon blocks outbound queue sends for that thread;
- owner reply stores message as owner-authored, not agent-authored;
- release sets `release_pending_approval`;
- the next inbound after release summons instead of full autonomous send;
- after owner approves that next turn, normal autonomy can resume.

### Decision Tree: Delayed Outbound Queue

```text
Agent has approved customer-facing reply
|
+-- channel == sms
|   |
|   +-- phone opted out? --> block send; summon or mark blocked
|
+-- initiated outreach?
|   |
|   +-- yes --> quiet hours tree
|   +-- no  --> continue
|
+-- calculate delay
|   |
|   +-- random 1-10 minutes, biased 3-5
|
+-- create outbound queue row status=pending
|
+-- before send time
|   |
|   +-- owner/system cancels? ------> status=cancelled; do not send
|   +-- newer inbound makes stale? -> status=stale; summon or recompute
|   +-- thread summoned? ----------> status=blocked; do not send
|
+-- send time reached
    |
    +-- sms --> TelnyxClient.send_message()
    +-- email --> EmailGatewayClient.send_email()
    |
    +-- provider success --> status=sent
    +-- provider failure --> status=failed; no trust penalty
```

Red-test assertions:

- all autonomous replies create delayed queue rows instead of immediate sends;
- delay is within 1-10 minutes;
- pending outbound can be cancelled;
- stale outbound does not send;
- failed provider delivery records failure without trust decrease.

### Decision Tree: Quiet Hours

```text
Outbound candidate
|
+-- is this a reply to customer-initiated inbound?
|   |
|   +-- yes --> quiet hours do not block
|
+-- is this agent-initiated outreach?
    |
    +-- no --> quiet hours do not block
    |
    +-- yes
        |
        +-- users.timezone local time between 7:00am and 7:00pm?
            |
            +-- yes --> allow queue/send path
            +-- no  --> queue for next allowed window
```

Red-test assertions:

- 3:00am customer inbound can receive autonomous reply if gates pass;
- 3:00am agent-initiated outreach queues for next allowed window;
- timezone source is `users.timezone`, not server local time.

### Decision Tree: STOP Handling

```text
Inbound SMS body received
|
+-- body is opt-out command?  (STOP and required variants)
|   |
|   +-- yes
|       |
|       +-- persist sms_opt_out
|       +-- cancel pending non-permitted SMS outbounds to number
|       +-- do not run agent
|       +-- do not count as trust penalty
|
+-- body is opt-in command?  (START and required variants)
    |
    +-- yes --> clear opt-out if allowed by provider rules
    |
    +-- no  --> normal SMS inbound tree
```

Red-test assertions:

- STOP blocks future SMS sends to that number;
- STOP cancels pending SMS queue rows for that number;
- STOP does not affect email sends;
- STOP does not decrease model trust.

### Decision Tree: Policy Cleanup And Tool Rules

```text
Owner writes plain-language policy
|
+-- save draft
|
+-- LLM cleanup pass
|   |
|   +-- structured cleaned policy
|   +-- proposed tool allow/block rules per channel
|
+-- owner reviews proposal
    |
    +-- owner edits directly ------> recompute/validate compiled rules
    +-- owner gives feedback ------> another LLM cleanup pass
    +-- owner rejects -------------> discard draft
    +-- owner approves ------------> persist final only
                                      activate compiled rules
```

Red-test assertions:

- draft policy does not affect runtime;
- final approval is required before compiled rules activate;
- only final approved policy is persisted as active;
- compiled block rule prevents tool execution even if prompt text would allow it.

### Decision Tree: Trust Accounting

```text
Interaction outcome recorded
|
+-- outcome type
    |
    +-- explicit positive owner grade
    |   |
    |   +-- increment category success
    |
    +-- successful human release after summon
    |   |
    |   +-- increment category success
    |
    +-- repeated category success
    |   |
    |   +-- success_count >= 15?
    |       |
    |       +-- yes --> create trust proposal
    |       +-- no  --> no proposal
    |
    +-- rejection/customer complaint/bad assessment/wrong customer/policy hit
    |   |
    |   +-- record negative signal
    |   +-- consider trust decrease/proposal depending implementation rules
    |
    +-- human edit before send
    |   |
    |   +-- training signal only; no trust decrease
    |
    +-- provider delivery failure
        |
        +-- transport signal only; no trust decrease
```

Red-test assertions:

- 15 category successes creates a pending trust proposal;
- trust mode does not change until proposal approval;
- provider delivery failure does not decrement trust;
- human edit before send does not decrement trust;
- wrong-customer delivery records negative trust signal.

### Decision Tree: Directive Distillation

```text
Distillation requested or threshold reached
|
+-- gather inputs
|   |
|   +-- takeovers
|   +-- rejections with written feedback
|   +-- approvals
|   +-- positive grades
|   +-- summon/release outcomes
|
+-- generate full directive rewrite
|
+-- owner reviews diff
    |
    +-- approve --> create active directive version
    |
    +-- reject --> mark run rejected; active version unchanged
    |
    +-- edit manually --> save edited draft; owner can approve
    |
    +-- request revision
        |
        +-- distiller receives feedback
        +-- prompt says only owner-specified areas should change
        +-- produce revised full text
        +-- return to owner review
|
+-- rollback requested
    |
    +-- restore prior directive text only
    +-- do not roll back trust state
```

Red-test assertions:

- distillation output never activates without owner approval;
- rejection leaves active directives unchanged;
- revision preserves untouched sections when owner targets specific area;
- rollback changes directive text and leaves trust stats unchanged.

### Decision Tree: Initial Voice Seed

```text
Owner starts initial voice seed
|
+-- collect source data
|   |
|   +-- Telnyx message history
|   +-- mbox archives
|
+-- normalize written communication samples
|
+-- generate proposed directives + fixed exemplars + style summary
|
+-- owner reviews
    |
    +-- approve --> create first active directive version and exemplar set
    +-- edit ----> save edited version; owner can approve
    +-- reject --> no active directive changes
```

Red-test assertions:

- voice seed does not filter mbox by configured sender addresses;
- generated seed is not active before approval;
- approved seed creates active directive version and fixed exemplar set;
- fixed exemplars are always included by context builder.

### Red/Green Test Inventory

Initial implementation should start with focused red tests in this order:

1. `tests/clients/test_telnyx_client.py`
   - constructor fails on missing required config
   - outbound SMS request uses expected Telnyx auth/payload
   - health check returns true on provider success
   - provider/network errors raise `TelnyxError`
2. `tests/api/test_telnyx_webhooks.py`
   - invalid signature rejects request
   - valid inbound SMS stores raw event and normalized message
   - valid call/transcript event stores event and triggers no automation
3. `tests/core/models/test_communication_models.py`
   - enums validate trust modes, channels, directions, statuses, categories
4. `tests/core/services/test_sms_thread_service.py`
   - create manual thread by customer and by phone
   - append inbound/outbound messages
   - RLS isolation
   - auto-mode toggle state transitions
5. `tests/core/services/test_identity_resolution_service.py`
   - exact phone/email match
   - fuzzy match fallback
   - lead creation fallback
   - unmatched human-review fallback
6. `tests/core/services/test_communication_policy_service.py`
   - draft policy inactive
   - cleanup proposal requires approval
   - compiled block rule prevents tool execution
7. `tests/core/services/test_confidence_gate.py`
   - structured LLM output parsed
   - malformed/negative gate result prevents send
   - hard-gated category prevents reply
8. `tests/core/services/test_customer_agent_runtime.py`
   - `escalate_only` never sends
   - `reply` blocks CRM mutation
   - `safe_full` permits confirmed non-destructive mutation
   - `dangerous` still respects explicit blocklist
9. `tests/core/services/test_outbound_queue_service.py`
   - delayed queue row created for autonomous reply
   - delay is within configured range
   - cancellation and stale handling block send
   - failed delivery has no trust penalty
10. `tests/core/services/test_summon_service.py`
    - summon blocks autonomy
    - takeover stores owner-authored reply
    - release sets next-turn approval requirement
11. `tests/core/services/test_trust_service.py`
    - 15 category successes creates proposal
    - trust mode changes only after owner approval
    - provider failure and human edit do not decrease trust
12. `tests/core/services/test_directive_service.py`
    - approval activates directive
    - rejection leaves active version unchanged
    - rollback restores directive text only
13. `tests/core/services/test_distillation_service.py`
    - revision prompt preserves untouched areas by contract
    - owner approval required before activation
14. `tests/core/services/test_voice_seed_service.py`
    - Telnyx history samples normalize
    - mbox samples normalize without sender filtering
    - seed approval creates directive/exemplar version

### Implementation Invariants

- No customer-facing send occurs from a provider webhook handler directly.
  Webhooks ingest and normalize. Runtime and outbound queue decide sending.
- No LLM result can execute a tool until code checks trust mode, channel policy,
  hard gates, confirmation requirements, and thread ownership.
- No unapproved directive or policy draft affects runtime.
- No thread in `summoned`, `human_owned`, or `dormant` state sends autonomously.
- No released thread returns directly to full autonomy; next turn requires
  approval summon.
- No SMS send occurs to an opted-out phone number.
- No initiated outreach sends outside 7:00am-7:00pm in `users.timezone`.
- No provider delivery failure changes model trust.
- No model-facing CRM tool duplicates existing customer/ticket/invoice/note
  service logic.
- No new user-visible operational table ships without RLS and reset-test
  coverage.
