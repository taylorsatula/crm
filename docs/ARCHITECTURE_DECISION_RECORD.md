!!!!!!!
Add this as a built-out line item in the requirements and then delete this comment when it is added. if this comment is here You and Taylor have not finished the task, Claude:

Add universal search like MacOS finder. All functionality indexed as an data attribute on top level functionality.
!!!!!!!

# Architecture Decision Record

## CRM/Appointment System for Service Businesses

**Created**: 2024-12-30
**Status**: Living Document
**Authors**: Taylor, Claude

---

## Executive Summary

This document captures the architectural decisions, constraints, and guiding principles for building a CRM and appointment scheduling system designed for service businesses. The system prioritizes clean primitives, lightweight operation on slow connections, and extensibility through predictable patterns.

The primary use case is a window cleaning service business, but the architecture is designed to generalize to other service industries with similar workflows: scheduled appointments, on-site service delivery, invoicing, and customer relationship tracking.

**Guiding Philosophy**: Build the right things, not all the things. Feature creep is how you end up with Square Appointments vol. 2. Every feature sounds good; not every feature should be built. KISS (Keep It Simple, Stupid) is a core design principle, not a fallback.

---

## Part 1: Problem Statement

### What We're Replacing

The current solution (Square Appointments) exhibits several pain points that inform our architectural decisions:

**Architectural Debt**
Square was originally a point-of-sale system. Appointments and invoicing were bolted on afterward, resulting in convoluted flows where the user mental model doesn't match the system model. Entities that should be peers are instead nested awkwardly. Actions that should be single operations require multiple steps across different screens.

**API Quality**
Square's API suffers from deep nesting, inconsistent patterns, and poor discoverability. While they've added an MCP server to help, this masks rather than solves the underlying design issues. A well-designed API shouldn't need a wrapper to be usable.

**Limited Search Capabilities**
The customer directory can only be searched by name or phone number. This is insufficient for a service business where you might need to find "the elderly woman in Owens Cross Roads" or "customers who had screen cleaning last spring." The system captures information but makes it inaccessible.

**No After-Action Reporting**
When a technician completes a job, there's no structured way to record observations about the customer, property, or service that can be queried later. Notes exist but they're unstructured text blobs that can't inform future interactions or marketing.

**No Audit Trail**
When a ticket is modified—services added, prices changed—there's no history. You see the final state but not how it got there. For a business that needs to understand its operations and occasionally resolve disputes, this is a gap.

**Poor Performance on Slow Connections**
The system loads excessive content for simple operations. When a technician is at a customer's house with one bar of LTE, they cannot reliably close out a ticket. For a mobile service business, this is a critical failure.

**Slow Feature Development**
Technical debt has accumulated to the point where adding new features is slow and risky. The hope is that building strong primitives and stable patterns from the start will enable faster, more predictable development.

### What We Want to Preserve

Not everything about the current system is wrong. These capabilities must be retained:

- **Appointment Scheduling**: Creating, modifying, and viewing appointments with calendar integration
- **Automated Reminders**: Set-and-forget notifications to customers before appointments
- **Recurring Appointments**: Interval-based scheduling for regular service customers
- **Remote Invoicing**: Send invoices without being physically present
- **Analytics**: Year-over-year comparisons, drilldowns by service type, trend analysis
- **Web/Mobile Parity**: Full functionality on both platforms, not a degraded mobile experience

---

## Part 2: Core Requirements

### Functional Requirements

**Ticket Management**
- Create, modify, cancel tickets (ticket = appointment, same entity)
- Tickets are mutable until closed, immutable after
- Full audit trail on all modifications
- Multiple technicians per ticket (one-to-many)
- Manual clock-in/clock-out for duration tracking
- Close-out flow with forced multi-step completion

**Customer Management**
- Contact records with multiple addresses (service locations)
- Customer preferences (prefers mornings/afternoons, etc.)
- Full-text and attribute-based search
- Accumulated attributes from service history and notes
- Waitlist for customers wanting earlier appointments

**Service Catalog**
- Fixed price services (standard rate)
- Flexible price services (price set at ticket creation, modifiable until close-out)
- Per-unit services (quantity × unit price)
- Physical items/products

**Invoicing**
- Invoice created from ticket (conversion) OR standalone
- Flow is one-way: ticket → invoice, never invoice → ticket
- Remote invoice delivery via email

**Scheduled Messages**
- Automated customer outreach (email only)
- Templatized messages with freeform customization
- "Reach out in X months" creates scheduled message
- Web UI to view/filter scheduled messages by date or customer
- Appointment confirmations with Accept/Decline/Request Modify
- Follow-up if ignored, stop if confirmed
- "Tomorrow" reminder before appointments

**Recurring Appointments**
- Interval-based scheduling
- Modifications: change this one OR change all future
- Template-based generation

**Analytics**
- Year-over-year tracking (this month vs. same month last year)
- Trends: line item types, average spend, neighborhood activity
- Export capabilities

### Non-Functional Requirements

**Performance**
The system must be usable on a single bar of LTE. This constrains everything: payload sizes, number of round trips, progressive loading strategies. If a technician can't close a ticket in the field, the system has failed.

**Extensibility**
New features should follow established patterns. A developer looking at the codebase should be able to predict where new code goes and how it should be structured. Patterns should be obvious, not clever.

**Multi-Tenancy**
The system is multi-tenant from day one. Each business has isolated data. Initially, each business has a single user. The architecture must accommodate adding multiple users per business with role-based permissions without requiring a rewrite.

**Audit Trail**
Every entity gets change tracking. This is a universal pattern—build once, apply everywhere. Not a nice-to-have; a first-class requirement.

**Offline Tolerance**
While full offline-first architecture is not in initial scope, the system should degrade gracefully. Cached data should remain accessible. Operations should queue for sync when connectivity returns.

---

## Part 3: Domain Model

### Core Entities

**Contact**
A person or organization that receives services. Has contact information, one or more addresses (service locations), preferences (morning/afternoon), and accumulated attributes derived from service history and notes.

**Address**
A physical location where services are performed. Tied to a Contact but modeled separately because a customer may have multiple service locations (e.g., home and rental property).

**Service**
A catalog item representing work that can be performed. Has a pricing strategy:
- Fixed: Set price regardless of scope
- Flexible: Base service, price determined at ticket creation (modifiable until close-out)
- Per-Unit: Unit price multiplied by quantity

**Ticket**
The unified entity for scheduled and performed work. A ticket IS an appointment—not a separate entity. Contains:
- Scheduled time and address
- Line items (services rendered)
- Technician assignment(s) (one-to-many)
- Duration (clock-in/clock-out)
- Status tracking
- After-action notes
- Estimated pricing flag (optional)

Tickets are **mutable until closed, immutable after**. All modifications are captured in the audit trail.

When `is_price_estimated` is true, the ticket displays "Estimated" pricing in the UI and confirmation emails. At close-out, the technician must confirm/update the final price before completing the ticket.

**LineItem**
A service instance on a ticket. Captures the service performed, quantity (for per-unit), duration (for time-tracked), and final price.

**Invoice**
A billing document. Created from a ticket (conversion) OR created standalone. The flow is one-way: ticket → invoice. An invoice cannot create a ticket.

**Note**
Free-form text attached to tickets or contacts. Processed by LLM into structured attributes that become queryable.

**Attribute**
Structured data derived from notes or explicitly set. Lives on the Contact. Enables queries like "elderly customers" or "properties with screens." Schema is flexible to accommodate diverse attribute types—start flexible, shape later based on actual usage patterns.

**ScheduledMessage**
An automated email queued for future delivery. Created by "reach out in X months" flow or appointment confirmations. Has template reference and customization text.

**Waitlist**
Customers waiting for earlier appointments. Enables opportunistic scheduling when gaps appear and technician is in the area.

**Lead**
A potential customer captured from a phone call or inquiry. Contains freeform notes from the call which are processed by LLM into structured data (name, phone, email, address, service interest, source, urgency, property details). Leads follow a lifecycle: new → contacted → qualified → converted|archived. When converted, a Customer record is created and linked. Leads exist separately from Customers because they may never convert, and we don't want to pollute customer data with unqualified prospects.

### Entity Relationships

```
Contact (1) ←→ (many) Address
Contact (1) ←→ (many) Ticket
Contact (1) ←→ (many) Attribute
Contact (1) ←→ (many) Note
Contact (1) ←→ (many) ScheduledMessage
Contact (0-1) ←→ (0-1) Waitlist

Address (1) ←→ (many) Ticket

Ticket (1) ←→ (many) LineItem
Ticket (1) ←→ (many) Technician (User)
Ticket (1) ←→ (many) Note
Ticket (0-1) ←→ (0-1) Invoice
Ticket (1) ←→ (many) AuditEntry

Service (1) ←→ (many) LineItem

Invoice (standalone OR from Ticket)

Lead (0-1) → (0-1) Contact  (via conversion)
```

### Pricing Model Examples

**Fixed Price Service**
```
Service: "Gutter Cleaning"
Price: $150
→ LineItem captures: service_id, price=$150
```

**Flexible Price Service**
```
Service: "Interior and Exterior Window Cleaning"
→ At any point before close-out, technician sets/modifies: duration=3h30m, price=$562
→ LineItem captures: service_id, duration, price
→ Audit trail captures: original values, all modifications, final values
```

**Per-Unit Service**
```
Service: "Screen Cleaning"
Unit Price: $5
→ At ticket creation: quantity=20
→ LineItem captures: service_id, quantity=20, unit_price=$5, total=$100
```

---

## Part 4: The Close-Out Flow

This is the critical UX moment. It deserves its own section because getting it wrong means bad data, and bad data means bad decisions.

### The Flow

1. **Context-Aware Quick Action**
   Technician opens UI. Current ticket (based on time) surfaces as quick-action in the header. One tap to access.

2. **Initiate Close-Out**
   Tap ticket → tap "Close Out"

3. **Confirm Duration and Services**
   This is the last chance before immutability. Confirm:
   - Actual duration (clock-in/clock-out, but verify)
   - Services performed (may have changed from original booking)
   - Prices (especially for flexible services)
   - **If estimated**: Price confirmation is required—cannot skip

4. **Freeform Notes**
   Text field for observations: "Elderly woman, very nice. 20+ screens. Dog named Biscuit, keep gate closed."

5. **Schedule Next Service Prompt**
   Three options:
   - **Yes**: Schedule the next appointment now
   - **No**: No follow-up needed
   - **Reach out in X months**: Creates automated scheduled message

6. **Confirmation Page**
   Shows frozen attributes based on inputs PLUS extracted NLP structured content. The technician sees what the system extracted and validates it before finalizing. Human-in-the-loop for extraction quality.

7. **Complete Ticket**
   Technician presses "Complete Ticket." Ticket becomes immutable.

8. **Payment/Invoice Prompt**
   - Take payment (future: Stripe integration)
   - Send remote invoice
   - Skip (if paid already or handled separately)

9. **Return to Calendar**
   Back to home base (day/week/month view).

### Design Philosophy

Technicians are **forced to complete the whole flow**. No shortcuts. No "I'll fill this in later." If they're going to be lazy, they do it clear-eyed—skipping a step they consciously saw.

The confirmation page with extracted content serves two purposes:
1. Human validates LLM extraction quality
2. Technician reviews what they're about to commit

This friction is intentional. It produces better data.

---

## Part 5: Technical Architecture

### Technology Choices

**Backend**: Python with FastAPI
- Mature async support when needed
- Excellent type hints
- Pydantic for validation
- Straightforward deployment

**Database**: PostgreSQL
- Row Level Security for tenant isolation
- JSONB for flexible attributes
- Full-text search built in
- pgvector available if we need embeddings later

**Frontend**: Vanilla HTML/CSS/JavaScript
- No framework overhead
- Minimal bundle size
- Progressive enhancement
- Works without JavaScript for core flows

**LLM Integration**: OpenAI-compatible API format
- Provider flexibility (Qwen3 initially)
- Well-documented format
- Tool calling support

**Email**: Transactional email service (specific provider TBD)
- Appointment confirmations
- Scheduled outreach messages
- Invoice delivery

### Directory Structure

```
crm/
├── api/           # FastAPI routes
│   ├── base.py    # Response format, error handling
│   ├── actions.py # State mutations (domain-routed)
│   ├── data.py    # Read operations (type-routed)
│   └── auth.py    # Authentication endpoints
├── core/          # Domain models, business logic
│   ├── models/    # Pydantic models
│   ├── services/  # Business logic
│   └── audit.py   # Universal audit trail
├── clients/       # External service clients
│   ├── postgres.py
│   ├── llm.py
│   └── email.py
├── auth/          # Authentication system
├── utils/         # Cross-cutting utilities
│   └── timezone.py
├── config/        # Configuration management
├── templates/     # Email templates
└── static/        # Frontend assets
```

### API Design

**Unified Response Format**

Every endpoint returns the same structure:

```json
{
  "success": true,
  "data": { },
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  },
  "meta": {
    "timestamp": "...",
    "request_id": "..."
  }
}
```

**Actions Endpoint**

State-changing operations go through `/api/actions`:

```json
POST /api/actions
{
  "domain": "ticket",
  "action": "close",
  "data": {
    "ticket_id": "...",
    "duration_minutes": 262,
    "notes": "...",
    "next_service": "reach_out",
    "reach_out_months": 3
  }
}
```

Domain handlers define their available actions with schemas specifying required fields, optional fields, and types. Validation happens at the infrastructure level, execution happens in domain handlers.

All mutations generate audit trail entries automatically.

**Data Endpoint**

Read operations go through `/api/data`:

```
GET /api/data?type=contacts&search=owens+cross+roads&limit=20
GET /api/data?type=tickets&id=123&include=line_items,audit_trail
GET /api/data?type=scheduled_messages&filter=pending&customer_id=456
```

Query parameters handle filtering, pagination, and field selection. The `type` parameter routes to the appropriate handler.

**Why This Split**

Separating reads from writes provides clarity about what operations have side effects. The actions endpoint can enforce CSRF protection, audit logging, and other write-specific concerns uniformly. The data endpoint can focus on caching, pagination, and query optimization.

### Database Design

**Row Level Security**

Every user-scoped table has an RLS policy. The application sets `app.current_user_id` on connection checkout, and PostgreSQL enforces isolation automatically:

```sql
CREATE POLICY user_isolation ON contacts
  USING (user_id = current_setting('app.current_user_id')::uuid);
```

This moves isolation from application code (where it can be forgotten) to the database (where it's enforced unconditionally).

**Audit Trail Pattern**

Universal audit pattern applied to all entities:

```sql
CREATE TABLE audit_log (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,      -- 'ticket', 'contact', etc.
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,           -- 'create', 'update', 'delete'
  changes JSONB NOT NULL,         -- {field: {old: x, new: y}}
  user_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
```

Audit entries are immutable. They capture what changed, when, and by whom.

**Connection Management**

A connection pool manages database connections. On checkout:
1. Get connection from pool
2. Set `app.current_user_id` for RLS
3. Execute queries
4. Return connection to pool

The user context is always set or cleared—never inherited from a previous checkout. This prevents data leaking between requests.

**Raw SQL Over ORM**

We use raw SQL rather than an ORM for several reasons:
- Explicit about when queries execute
- No hidden N+1 problems
- Clear memory management
- Direct access to PostgreSQL features (RLS, JSONB, etc.)
- Easier to optimize

### LLM Integration

**Unified Provider Interface**

All LLM calls go through a single client that handles:
- Request formatting (OpenAI-compatible)
- Error handling and retries
- Usage tracking
- Model selection

```python
llm = LLMClient()
response = llm.generate(
    messages=[...],
    tools=[...]  # Optional tool definitions
)
```

**After-Action Processing**

When a ticket is closed with notes, the LLM extracts structured attributes:

```
Input: "Elderly woman, very nice. House has 20+ screens, takes longer than usual.
        Dog named Biscuit, keep gate closed."

Output attributes:
- customer_demographic: elderly
- property_screen_count: 20+
- service_duration_note: longer_than_usual
- pet: dog (name: Biscuit)
- property_note: keep gate closed
```

These attributes attach to the Contact and become searchable. The schema is flexible—we store what the LLM extracts and let patterns emerge from real usage rather than over-designing upfront.

The extracted content is shown to the technician on the confirmation page before close-out is finalized. This provides human validation of extraction quality.

### Email System

**Template Architecture**

Developer-built HTML templates with variable injection points. UI provides simple plaintext editor for template content. Variables like `{{customer_name}}`, `{{appointment_date}}`, `{{custom_message}}` get substituted at send time.

**Message Types**
- Appointment confirmation (Accept/Decline/Request Modify links)
- Appointment reminder ("Your appointment is tomorrow")
- Follow-up for unconfirmed appointments
- Scheduled outreach ("Reach out in X months")
- Invoice delivery

**Customer Response Handling**
- Accept: Mark confirmed, stop follow-ups
- Decline: Flag for rescheduling
- Request Modify: Flag for manual follow-up
- Ignored: Send follow-up sequence

### Authentication

**Magic Link Flow**

1. User enters email
2. System sends email with one-time token
3. User clicks link, token is verified
4. Session token issued, stored in cookie

No passwords to store, reset, or manage. Session tokens have configurable expiration with activity-based extension.

**Multi-Tenancy Model**

Initially: `user_id` equals business. One user, one business.

Future: Add `organization_id`. Users belong to organizations. RLS policies scope to organization. Users have roles within their organization.

The migration path:
1. Add `organization_id` to relevant tables (nullable initially)
2. Create organizations for existing users
3. Update RLS policies to use organization
4. Add role system
5. Make `organization_id` required

---

## Part 6: Design Principles

### KISS (Keep It Simple, Stupid)

This is the prime directive. Feature creep is how you end up rebuilding the thing you're trying to escape.

Every feature sounds good in isolation. SMS notifications? Great idea. Travel time tracking? Useful. GPS geofencing for auto clock-in? Slick. But each feature adds:
- Code to write and maintain
- Edge cases to handle
- UI surface area
- Documentation
- Potential bugs

The discipline is saying "not yet" to good ideas so you can ship the essential ones well.

**Concrete Applications**:
- Email only for messaging (no SMS initially)
- No travel time tracking
- Manual clock-in/clock-out (no GPS automation)
- No customer login portal
- No payment processing (invoices link externally, Stripe integration later)

### Fail Fast, Fail Loud

When required infrastructure fails, the error must propagate immediately. Never catch a database exception and return an empty list—that makes outages look like missing data and creates debugging nightmares.

```python
# Wrong
def get_contacts():
    try:
        return db.query("SELECT * FROM contacts")
    except:
        return []  # Database outage now looks like "no contacts"

# Right
def get_contacts():
    return db.query("SELECT * FROM contacts")  # Let it raise
```

Reserve exception handling for:
- Adding context before re-raising
- Genuinely optional features (analytics, caching)
- Retry logic with limits

### No Premature Abstraction

Write the straightforward solution first. Don't create abstractions until you have at least two concrete use cases. A function called from one place doesn't need to be extracted. A configuration with one value doesn't need to be parameterized.

Complexity added "just in case" usually becomes technical debt that obscures the actual logic and makes changes harder.

### Types as Contracts

Type hints are executable documentation. Use specific types:
- `UUID` not `str` for identifiers
- `datetime` not `str` for timestamps
- `Decimal` not `float` for money

Avoid `Optional[X]` except for genuine domain optionality (a preference that may not be set). Never use `Optional` to mean "this might fail"—let it fail loudly instead.

### Lightweight by Default

Every API response should return the minimum viable payload. Use query parameters for expansion:

```
GET /api/data?type=tickets&id=123
→ Returns ticket summary

GET /api/data?type=tickets&id=123&include=line_items,audit_trail
→ Returns ticket with expanded relations
```

This keeps default payloads small for slow connections while allowing clients to request more data when needed.

### UTC Everywhere

All timestamps stored in UTC. All timestamp comparisons in UTC. Convert to local timezone only at the display boundary—the moment you're rendering for a human to read.

This eliminates an entire class of timezone bugs and makes queries simpler (no timezone conversion in WHERE clauses).

### Patterns Over Cleverness

The codebase should be predictable. A developer looking at how contacts work should immediately understand how tickets work because they follow the same patterns. Favor boring, obvious code over clever solutions that require explanation.

### Forced Completion Over Convenience

For critical flows (like ticket close-out), make users complete all steps. No "save for later" on half-done close-outs. If they skip something, they do it consciously, not accidentally. Friction that produces good data is worth it.

---

## Part 7: Development Approach

### What Gets Built First

The foundational patterns must be established before domain features:

1. **API Base**: Response format, error handling, request ID generation
2. **Database Client**: Connection pooling, RLS enforcement, query methods
3. **Audit Trail**: Universal change tracking pattern
4. **Authentication**: Magic link flow, session management, user context
5. **LLM Client**: OpenAI-compatible interface for Qwen3

These create the infrastructure that all features build upon. Getting them right avoids painful migrations later.

### Feature Development Order

After foundations, features build in dependency order:

1. **Contacts and Addresses**: Foundation for everything else
2. **Service Catalog**: Required for tickets
3. **Tickets with Close-Out Flow**: Core workflow
4. **Notes and Attributes**: LLM-powered enrichment
5. **Calendar Views**: Day/week/month home base
6. **Email System**: Confirmations, reminders, templates
7. **Scheduled Messages**: Automated outreach
8. **Invoicing**: Revenue capture
9. **Recurring Appointments**: Automation layer
10. **Analytics**: Insight from accumulated data

Each feature follows the established patterns: actions for mutations, data for reads, consistent error handling, RLS-enforced isolation, universal audit trail.

### What We're NOT Building (Yet)

Explicitly out of scope for initial development:

- Multiple users per business (roles/permissions)
- SMS messaging (email only)
- Travel time tracking
- GPS/geofence automation
- Offline-first with local database
- Native mobile apps (web works on mobile)
- Payment processing (invoices link externally, Stripe later)
- Inventory management (beyond simple product catalog)
- Route optimization
- Customer-facing login portal
- Conditional/rule-based outreach automation

These may come later. They're excluded now to maintain focus and avoid building Square vol. 2.

### Data Migration

CSV import for:
- Existing customers from Square
- Historical appointments/tickets

Format TBD based on Square export capabilities.

---

## Part 8: Future Features

Features explicitly identified for later development, after core is stable:

### Waitlist with Opportunistic Scheduling

Customers can join a waitlist for earlier appointments. When a gap appears in the schedule and a technician is in the area, the system suggests waitlisted customers who could fill that slot.

### Conditional Reachouts / Rule Builder

Automated emails triggered by conditions:
- Business metrics: "Email all customers in Madison when 30-day appointment count drops X%"
- External data: "When pollen season ends (external API), send PollenSeason template"
- Time-based: "Customers who haven't booked in 6 months"

This is event-driven marketing automation. Requires rule builder UI.

### Stripe Payment Integration

Accept payment at close-out. Currently out of scope; invoices link to external payment.

### Multi-User Per Business

Add `organization_id`, role system, permissions. The RLS and auth patterns are designed to accommodate this without rewrite.

### Neighborhood Clustering

Group customers by geographic area for route planning and regional analytics. Implementation TBD—may be zip code, may be clustering algorithm.

---

## Part 9: Reference Architecture (MIRA)

### Why MIRA Matters

MIRA is a separate project by the same developer that demonstrates many of the patterns we want to adopt. It's a conversational AI system with:

- Event-driven architecture
- PostgreSQL with RLS for user isolation
- Raw SQL over ORM
- Clean API patterns (actions/data split)
- Magic link authentication

We're not copying MIRA wholesale, but it serves as a reference for how these patterns work in practice.

### Patterns to Adopt

**API Response Format**
MIRA's `APIResponse` dataclass with `{success, data, error, meta}` structure. Consistent across all endpoints.

**Domain Handlers**
Actions route to domain-specific handlers that define their available operations declaratively. Validation is separated from execution.

**Database Client**
Connection pooling with explicit RLS context setting. Clear about when connections are acquired and released.

**User Context Propagation**
Context variables carry user identity through the call stack. Set once at the API boundary, automatically available to all downstream code.

---

## Part 10: Open Questions

Questions to resolve as development progresses:

**Recurring Appointment Model**
How do we model a recurring series? Options:
- Single parent with generated children
- Template that generates independent appointments
- Each appointment links to next in series

Need to support: change-this-one vs. change-all-future.

**Search Implementation**
For rich search across attributes, what's the right approach?
- PostgreSQL full-text search on denormalized text
- JSONB containment queries on attributes
- Embedding-based semantic search
- Combination

**Email Service Provider**
Which transactional email service? Considerations:
- Deliverability
- Template support
- Webhook handling for bounces/complaints
- Cost at scale

**Attribute Schema Evolution**
As patterns emerge from LLM extraction, when and how do we formalize them? Stay flexible forever, or graduate common attributes to structured fields?

---

## Part 11: MCP Integration

### Overview

The CRM exposes an MCP (Model Context Protocol) server enabling an external LLM to act as an "office manager" - handling scheduling, customer management, leads, invoicing, and all CRM operations. The MCP is a first-class citizen of the architecture, not bolted on.

### Design Decision: Evergreen Capabilities

**Decision**: The MCP discovers available operations via a `/api/capabilities` endpoint that is auto-generated from domain handler registrations.

**Rationale**:
- Single source of truth: add an action to a handler, MCP automatically sees it
- No manual synchronization between API and MCP tool definitions
- MCP never goes stale as API evolves
- Domain handlers already declaratively define their operations

### Design Decision: Two-Layer Tool Architecture

**Decision**: Provide two layers of MCP tools:
1. **Raw API tools** (`crm_capabilities`, `crm_query`, `crm_action`) - direct passthrough to actions/data endpoints
2. **Workflow tools** (`schedule_appointment`, `daily_briefing`, etc.) - high-level orchestrations for common tasks

**Rationale**:
- Raw tools ensure nothing is blocked - LLM can always fall back to primitives
- Workflow tools reduce token usage and error rate for common patterns
- Workflows encode business logic (e.g., sending confirmation after scheduling)
- Two layers complement each other - use workflows when available, raw when needed

### Design Decision: Model Authorization Queue

**Decision**: Actions requiring human oversight go to a Model Authorization Queue with three permission levels:
- `unrestricted` - execute immediately
- `soft_limit` - execute but require reasoning field
- `requires_authorization` - queue for human review

**Rationale**:
- Some operations need human oversight (deleting customers with history, voiding paid invoices)
- Better UX than blocking the model entirely - action is queued, not rejected
- Human sees model's reasoning in context, can make informed decision
- "Allow always" option lets permissions evolve based on trust

### Design Decision: Allow Once vs Allow Always

**Decision**: When human reviews an authorization request, they can:
- **Allow Once** - execute this specific action, don't change permissions
- **Allow Always** - execute and upgrade this action to `unrestricted`
- **Deny** - reject with optional note to model

**Rationale**:
- "Allow Once" handles edge cases without creating permanent policy changes
- "Allow Always" reduces friction as trust builds
- Permissions can tighten over time if issues arise (manual override)
- Deny with note helps model learn what's acceptable

### MCP Tool Inventory

**Layer 1: Raw API**
| Tool | Purpose |
|------|---------|
| `crm_capabilities` | Discover available domains, actions, data types |
| `crm_query` | Query any data type with filters, pagination, expansion |
| `crm_action` | Execute any action on any domain |

**Layer 2: Workflows**
| Tool | Purpose |
|------|---------|
| `schedule_appointment` | Customer lookup → availability → ticket → confirmation |
| `handle_reschedule_request` | Find ticket → validate new time → cancel old → create new |
| `process_lead` | Raw notes → LLM extraction → create lead → schedule followup |
| `send_invoice` | Create from ticket → send to customer |
| `daily_briefing` | Today's schedule + pending leads + overdue invoices |
| `find_customer` | Fuzzy search across name/phone/email/address/notes |

### Permission Mapping

| Operation | Permission | Rationale |
|-----------|------------|-----------|
| Create entity | unrestricted | Low risk, easily reversible |
| Update entity | unrestricted | Audited, reversible |
| Read/query | unrestricted | No side effects |
| Cancel appointment | soft_limit | Requires reasoning |
| Archive lead | soft_limit | Requires reasoning |
| Delete entity with history | requires_authorization | Data loss risk |
| Void paid invoice | requires_authorization | Financial impact |
| Bulk operations (>5 items) | requires_authorization | Blast radius |

---

## Part 12: Stripe Integration

### Overview

Stripe Checkout handles payment processing. The CRM has zero PCI DSS scope - all card entry happens on Stripe's hosted page. CRM stores only Stripe reference IDs, never payment data.

### Design Decision: Stripe Checkout for Zero PCI Scope

**Decision**: Use Stripe Checkout Sessions for all payment collection. Customer is redirected to Stripe-hosted payment page.

**Rationale**:
- Customer never enters card data on CRM domain
- All sensitive payment handling delegated to Stripe
- No PCI DSS compliance burden on CRM
- Stripe handles 3D Secure, fraud detection, card validation
- CRM stores only reference IDs (`cus_xxx`, `cs_xxx`, `pi_xxx`)

**What CRM Stores**:
- `stripe_customer_id` on Contact - links CRM customer to Stripe customer
- `stripe_checkout_session_id` on Invoice - the checkout session created for payment
- `stripe_payment_intent_id` on Invoice - the payment intent (useful for refunds later)

**What CRM Does NOT Store**:
- Card numbers, CVV, expiration dates
- Bank account details
- Any PCI-sensitive data

### Design Decision: Webhook-Driven Payment Status

**Decision**: Payment status updates come from Stripe webhooks, not API polling.

**Rationale**:
- Real-time updates without polling overhead
- Stripe guarantees webhook delivery with retries
- Single source of truth for payment state
- Handles edge cases (customer closes browser after payment, network issues)

**Webhook Flow**:
1. Customer completes payment on Stripe Checkout
2. Stripe sends `checkout.session.completed` event to `/api/webhooks/stripe`
3. CRM verifies webhook signature (prevents spoofing)
4. CRM extracts `invoice_id` from session metadata
5. CRM calls `invoice_service.record_payment()` to update status
6. Audit trail records payment event

### Design Decision: Stripe Customer Linking

**Decision**: Create Stripe Customer on first invoice send, link via `stripe_customer_id`.

**Rationale**:
- Lazy creation - no Stripe Customer until needed
- Enables Stripe Customer Portal for payment history
- Future: saved payment methods, subscriptions
- One Stripe Customer per CRM Contact

**Flow**:
```
Invoice send requested
├── Check contact.stripe_customer_id
├── If null: Create Stripe Customer from contact data
│   └── Store stripe_customer_id on contact
├── Create Checkout Session with customer reference
├── Store checkout_session_id on invoice
└── Send email with payment link
```

### Design Decision: MCP Payment Access (soft_limit)

**Decision**: MCP can trigger invoice sending with payment links, but requires `reasoning` field.

**Rationale**:
- Model should be able to handle invoicing workflow
- Financial operations warrant explicit reasoning
- Audit trail captures why model sent invoice
- Human can review if patterns look problematic

### Payment Flow Diagram

```
1. Invoice Created (from ticket close-out or MCP)
         │
         ▼
2. Invoice Sent
   ├── Create/retrieve Stripe Customer (from contact)
   ├── Create Stripe Checkout Session
   │   └── success_url, cancel_url, line_items, customer, metadata
   ├── Store checkout_session_id on invoice
   └── Send email with payment_link
         │
         ▼
3. Customer Clicks Link
   └── Redirected to Stripe-hosted checkout page
         │
         ▼
4. Customer Pays (on Stripe's domain)
   └── Stripe processes card (CRM never sees card data)
         │
         ▼
5. Stripe Webhook → CRM
   ├── POST /api/webhooks/stripe
   ├── Verify signature (STRIPE_WEBHOOK_SECRET)
   ├── Extract invoice_id from metadata
   ├── Set user context (from invoice lookup)
   └── invoice_service.record_payment()
         │
         ▼
6. Invoice Status Updated
   └── sent → paid (or partial if partial payment)
```

### Secrets Management

| Secret | Storage | Purpose |
|--------|---------|---------|
| `STRIPE_SECRET_KEY` | Vault | API authentication |
| `STRIPE_WEBHOOK_SECRET` | Vault | Webhook signature verification |
| `STRIPE_PUBLISHABLE_KEY` | Config (not secret) | Client-side identification |

---

## Part 13: Input Sanitization

### Overview

Defense-in-depth sanitization strips sensitive data (credit card numbers, SSNs) from freeform text fields. Even though Stripe handles payment processing, users might accidentally paste card numbers into notes fields.

### Design Decision: Three-Layer Defense

**Decision**: Sanitize at frontend, backend, and database layers - but only for notes/message fields.

**Rationale**:
- Defense in depth - any single layer can fail
- Frontend gives immediate user feedback
- Backend is authoritative (can't be bypassed)
- Database triggers are last line of defense
- Limited scope avoids false positives on structured fields

| Layer | Purpose | Behavior |
|-------|---------|----------|
| Frontend (JS) | Immediate feedback | Strip on blur/submit, warn user |
| Backend (API) | Authoritative | Strip before processing, log to security_events |
| Database (trigger) | Last defense | Strip on INSERT/UPDATE |

### Design Decision: Visible Redaction

**Decision**: Replace sensitive data with `[REDACTED]` and show user warning.

**Rationale**:
- User knows something happened (not silent)
- Can see where data was in context
- Warning educates about the policy
- Logged to `security_events` for monitoring

### Design Decision: Specific Patterns

**Decision**: Target specific sensitive data patterns, not broad numeric detection.

**Patterns Stripped**:
| Pattern | Regex | Example |
|---------|-------|---------|
| Credit card | `\b(?:\d[ -]*?){13,19}\b` | 4111-1111-1111-1111 |
| SSN | `\b\d{3}-?\d{2}-?\d{4}\b` | 123-45-6789 |

**NOT Stripped** (false positive prevention):
- Phone numbers (different format: `(256) 555-1234`)
- Zip codes (5 or 9 digits)
- Invoice/ticket IDs
- Dates

### Columns Protected

**Notes fields:**
- `customers.notes`
- `tickets.notes`
- `leads.raw_notes`
- `notes.content`

**Message fields:**
- `scheduled_messages.body`

---

## Appendix A: Terminology

| Term | Definition |
|------|------------|
| Contact | A customer—person or organization receiving services |
| Address | A physical location where services are performed |
| Service | A catalog item representing work that can be done |
| Ticket | Scheduled and/or performed work (ticket = appointment, same entity) |
| Line Item | A single service instance on a ticket |
| Invoice | Billing document, created from ticket or standalone |
| Attribute | Structured data point attached to a contact, derived from notes or set explicitly |
| Scheduled Message | Automated email queued for future delivery |
| Waitlist | Customers waiting for earlier appointment availability |
| Lead | Potential customer captured from phone call/inquiry, pre-conversion |
| Close-Out | The process of completing a ticket, making it immutable |
| Conversion | The process of turning a lead into a customer record |
| RLS | Row Level Security—PostgreSQL feature for automatic data isolation |
| MCP | Model Context Protocol—Anthropic's protocol for AI tool integration |
| Model Authorization | Human review/approval of restricted model actions |
| Capabilities Endpoint | API endpoint that advertises available operations to MCP |
| Stripe Checkout Session | Stripe-hosted payment page instance for collecting payment |
| Payment Intent | Stripe's record of a payment attempt |
| Webhook | HTTP callback from Stripe to notify of payment events |

---

## Appendix B: Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12-30 | PostgreSQL over other databases | RLS for multi-tenancy, JSONB for flexibility, proven reliability |
| 2024-12-30 | Raw SQL over ORM | Explicit query execution, no hidden behavior, direct PostgreSQL feature access |
| 2024-12-30 | Actions/Data API split | Clear separation of reads and writes, consistent patterns |
| 2024-12-30 | Magic link auth | No password management, proven pattern from MIRA |
| 2024-12-30 | Vanilla frontend | Minimal bundle size, crucial for slow mobile connections |
| 2024-12-30 | OpenAI-compatible LLM format | Provider flexibility, well-documented, tool calling support |
| 2024-12-30 | User-scoped RLS initially | Simpler model, clear migration path to org-scoped later |
| 2024-12-30 | Ticket = Appointment | Single entity, not two linked entities. Simplifies model. |
| 2024-12-30 | Universal audit trail | Every entity audited with same pattern. Build once, apply everywhere. |
| 2024-12-30 | Email only (no SMS) | KISS. Avoid feature creep. SMS can come later. |
| 2024-12-30 | Manual clock-in/clock-out | No GPS complexity. Simple and reliable. |
| 2024-12-30 | No travel time tracking | Out of scope for initial build. Keep focused. |
| 2024-12-30 | Forced close-out flow | Multi-step wizard with no shortcuts. Friction produces good data. |
| 2024-12-30 | Attributes on Contact only | No separate Property entity. Let schema emerge from usage. |
| 2024-12-30 | Templatized emails | Developer HTML wrapper, user plaintext content with variables. |
| 2025-01-07 | Separate leads table (not extending customers) | Leads have different lifecycle, may never convert, don't pollute customer data |
| 2025-01-07 | raw_notes as source of truth for leads | Capture everything during call, structure later via LLM |
| 2025-01-07 | Simple reminder_at timestamp for leads | Placeholder for future CalDAV integration, avoid over-engineering |
| 2025-01-07 | Lead LLM extraction with human validation | Balance speed of capture with data quality |
| 2025-01-07 | MCP as first-class citizen | LLM can do everything a human can; architectural integration not bolt-on |
| 2025-01-07 | Auto-generated capabilities endpoint | Single source of truth; MCP never goes stale as API evolves |
| 2025-01-07 | Two-layer MCP tools (raw + workflows) | Raw for flexibility, workflows for common patterns and reduced token usage |
| 2025-01-07 | Model Authorization Queue | Human oversight for destructive ops without blocking model entirely |
| 2025-01-07 | Allow Once / Allow Always / Deny | Flexible authorization that can evolve with trust |
| 2025-01-07 | Stripe Checkout for payments | Zero PCI scope - customer pays on Stripe's domain, not ours |
| 2025-01-07 | Webhook-driven payment status | Stripe pushes events; no polling required |
| 2025-01-07 | Stripe Customer lazy creation | Create on first invoice send, link via stripe_customer_id |
| 2025-01-07 | Store reference IDs only | stripe_customer_id, stripe_checkout_session_id, stripe_payment_intent_id |
| 2025-01-07 | Ticket-level estimated pricing flag | Simple boolean, shows "Estimated" in UI/emails, requires confirmation at close-out |
| 2025-01-07 | Three-layer input sanitization | Frontend + backend + DB triggers for notes/messages only |
| 2025-01-07 | Visible redaction with warning | Replace with [REDACTED], show user warning, log to security_events |

---

## Appendix C: File References

Key files in the MIRA codebase that demonstrate referenced patterns:

| Pattern | File |
|---------|------|
| API Response Format | `cns/api/base.py` |
| Actions Routing | `cns/api/actions.py` |
| Data Routing | `cns/api/data.py` |
| Database Client | `clients/postgres_client.py` |
| Authentication | `auth/api.py` |

---

## Appendix D: Example Ticket Lifecycle

A complete example showing ticket flow:

**1. Creation**
```
Customer: Jane Smith
Address: 123 Main Street, Madison, AL 35758
Service: Interior and Exterior Window Cleaning (flexible)
Scheduled: 2024-01-15 9:00 AM
Technician: Taylor
```

**2. Appointment Confirmation Sent**
```
Email to Jane with Accept/Decline/Request Modify links
Jane clicks Accept
System marks confirmed, stops follow-up sequence
```

**3. Day Before Reminder**
```
Automated email: "Your appointment is tomorrow at 9:00 AM"
```

**4. Day Of**
```
Technician arrives, taps clock-in
Work performed
Technician taps clock-out
Duration recorded: 3h 22m
```

**5. Close-Out Flow**
```
Technician opens current ticket (surfaced as quick-action)
Taps "Close Out"
Confirms: duration=3h22m, services=[Int/Ext Windows, Screen Cleaning x20]
Confirms: price=$562 + $100 = $662
Enters notes: "Elderly woman, very nice. Dog named Biscuit, keep gate closed.
               Complex sill on 2nd story, brought extension ladder."
Selects: "Reach out in 6 months"
Reviews confirmation page with extracted attributes:
  - customer_demographic: elderly
  - pet: dog (Biscuit)
  - property_note: keep gate closed
  - equipment_needed: extension ladder
  - property_detail: complex 2nd story sill
Presses "Complete Ticket"
Ticket becomes immutable
```

**6. Invoice**
```
Technician selects "Send Remote Invoice"
Invoice created from ticket
Email sent to Jane with payment link
```

**7. Scheduled Follow-Up**
```
Scheduled message created: Send in 6 months
July 2024: Automated email sent suggesting booking
```

**8. Next Year's Scheduling**
```
When booking Jane again, technician sees:
- Last service: 3h22m
- Notes: extension ladder needed, 2nd story sill complexity
- Preferences: (none recorded yet)
Can confidently schedule 4-hour block
```

---

*This document should be updated as significant architectural decisions are made or requirements evolve.*
