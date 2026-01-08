# MCP Integration Guide

The CRM exposes an MCP (Model Context Protocol) server enabling an external LLM to act as an "office manager" - handling scheduling, customer management, leads, invoicing, and all CRM operations.

---

## Overview

### What the Model Can Do

With MCP integration, an LLM can:
- Query customers, tickets, leads, invoices, services
- Schedule and reschedule appointments
- Capture and process leads from phone calls
- Send invoices and track payments
- Provide daily briefings and operational summaries
- Search across all customer data

### Design Principles

1. **Evergreen** - Capabilities auto-generated from domain handlers; never goes stale
2. **Two-Layer Tools** - Raw API access + high-level workflows
3. **Human Oversight** - Restricted operations require human authorization
4. **First-Class Citizen** - MCP is architectural, not bolted on

---

## Tool Inventory

### Layer 1: Raw API Tools

Direct access to the CRM API. Use when workflow tools don't cover the need.

#### `crm_capabilities`

Discover available operations. Call this first to understand what actions you can take.

```json
{
  "name": "crm_capabilities",
  "input_schema": {
    "properties": {
      "domain": {
        "type": "string",
        "description": "Optional: filter to specific domain (ticket, contact, invoice, lead, message, service)"
      }
    }
  }
}
```

**Returns**: List of domains, their actions, parameter schemas, and permission levels.

---

#### `crm_query`

Query CRM data with filters, pagination, and relation expansion.

```json
{
  "name": "crm_query",
  "input_schema": {
    "properties": {
      "type": {
        "type": "string",
        "enum": ["contacts", "tickets", "services", "invoices", "leads", "messages", "attributes"],
        "description": "Entity type to query"
      },
      "id": {
        "type": "string",
        "description": "Get specific entity by ID"
      },
      "search": {
        "type": "string",
        "description": "Fuzzy search across name, email, phone, notes"
      },
      "filters": {
        "type": "object",
        "description": "Type-specific filters: {status: 'scheduled'} for tickets"
      },
      "include": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Relations to expand: ['addresses', 'line_items']"
      },
      "limit": {
        "type": "integer",
        "description": "Max results (default 20, max 100)"
      },
      "cursor": {
        "type": "string",
        "description": "Pagination cursor from previous response"
      }
    },
    "required": ["type"]
  }
}
```

---

#### `crm_action`

Execute any CRM action. All state changes go through this tool.

```json
{
  "name": "crm_action",
  "input_schema": {
    "properties": {
      "domain": {
        "type": "string",
        "enum": ["ticket", "contact", "invoice", "lead", "message", "service"],
        "description": "Action domain"
      },
      "action": {
        "type": "string",
        "description": "Action name (use crm_capabilities to discover)"
      },
      "data": {
        "type": "object",
        "description": "Action parameters (schema varies by action)"
      },
      "reasoning": {
        "type": "string",
        "description": "Required for soft_limit actions. Explain why you're taking this action."
      }
    },
    "required": ["domain", "action", "data"]
  }
}
```

---

### Layer 2: Workflow Tools

High-level orchestrations for common office manager tasks. Preferred over raw API for supported operations.

#### `schedule_appointment`

Full booking flow: customer lookup → availability → ticket creation → confirmation.

```json
{
  "name": "schedule_appointment",
  "input_schema": {
    "properties": {
      "customer_identifier": {
        "type": "string",
        "description": "Customer name, phone, email, or ID"
      },
      "address_identifier": {
        "type": "string",
        "description": "Address label ('Home'), full address, or ID"
      },
      "requested_date": {
        "type": "string",
        "description": "Date: 'YYYY-MM-DD', 'tomorrow', 'next Monday'"
      },
      "requested_time": {
        "type": "string",
        "description": "Time: 'morning', 'afternoon', '9am', '9:00-11:00'"
      },
      "services": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Service names or IDs"
      },
      "duration_estimate_minutes": {
        "type": "integer"
      },
      "notes": {
        "type": "string",
        "description": "Notes for technician"
      },
      "send_confirmation": {
        "type": "boolean",
        "default": true
      }
    },
    "required": ["customer_identifier", "requested_date"]
  }
}
```

---

#### `handle_reschedule_request`

Process a customer's reschedule request: find ticket → validate new time → cancel old → create new.

```json
{
  "name": "handle_reschedule_request",
  "input_schema": {
    "properties": {
      "ticket_id": {
        "type": "string",
        "description": "Ticket ID or customer identifier to find it"
      },
      "new_date": {"type": "string"},
      "new_time": {"type": "string"},
      "reason": {
        "type": "string",
        "description": "Reason for reschedule (audit trail)"
      }
    },
    "required": ["ticket_id", "new_date"]
  }
}
```

---

#### `process_lead`

Capture a new lead: raw notes → LLM extraction → create lead → schedule followup.

```json
{
  "name": "process_lead",
  "input_schema": {
    "properties": {
      "raw_notes": {
        "type": "string",
        "description": "Freeform notes from call. Will extract name, phone, email, etc."
      },
      "source": {
        "type": "string",
        "description": "Lead source: phone_call, website, referral"
      },
      "urgency": {
        "type": "string",
        "enum": ["low", "medium", "high"]
      },
      "schedule_followup": {"type": "boolean"},
      "followup_date": {"type": "string"}
    },
    "required": ["raw_notes"]
  }
}
```

---

#### `send_invoice`

Create and send invoice from ticket with Stripe Checkout payment link.

**Permission**: `soft_limit` - requires reasoning for financial operations

```json
{
  "name": "send_invoice",
  "input_schema": {
    "properties": {
      "ticket_id": {
        "type": "string",
        "description": "Create invoice from this ticket's line items"
      },
      "include_payment_link": {
        "type": "boolean",
        "default": true,
        "description": "Generate Stripe Checkout link for payment"
      },
      "notes": {"type": "string"},
      "due_days": {
        "type": "integer",
        "default": 30
      }
    },
    "required": ["ticket_id"]
  }
}
```

**Response includes**:
- `invoice_id` - created invoice ID
- `payment_link` - Stripe Checkout URL (if `include_payment_link: true`)
- `total_amount` - invoice total

**Note**: Customer is redirected to Stripe-hosted payment page. CRM never handles card data.

---

#### `daily_briefing`

Get comprehensive daily summary.

```json
{
  "name": "daily_briefing",
  "input_schema": {
    "properties": {
      "date": {
        "type": "string",
        "description": "Date for briefing (default: today)"
      },
      "include_week_preview": {"type": "boolean"}
    }
  }
}
```

**Returns**:
- Today's appointments with customer details
- Pending leads needing follow-up
- Overdue invoices
- Upcoming reminders
- Optional: week preview

---

#### `find_customer`

Fuzzy search across all customer data.

```json
{
  "name": "find_customer",
  "input_schema": {
    "properties": {
      "query": {
        "type": "string",
        "description": "Search: name, phone, address, 'elderly woman in Madison', etc."
      },
      "include_history": {
        "type": "boolean",
        "description": "Include service history summary"
      }
    },
    "required": ["query"]
  }
}
```

---

## Permission System

### Permission Levels

| Level | Behavior | Examples |
|-------|----------|----------|
| `unrestricted` | Execute immediately | Create, read, update |
| `soft_limit` | Requires `reasoning` field | Cancel appointment, archive lead |
| `requires_authorization` | Queues for human review | Delete customer w/ history, void paid invoice |

### Permission Mapping

| Operation | Permission | Why |
|-----------|------------|-----|
| Create entity | unrestricted | Low risk, audited |
| Update entity | unrestricted | Audited, reversible |
| Read/query | unrestricted | No side effects |
| Cancel appointment | soft_limit | Customer impact |
| Archive lead | soft_limit | Potential loss |
| Delete with history | requires_authorization | Data loss |
| Void paid invoice | requires_authorization | Financial |
| Bulk ops (>5 items) | requires_authorization | Blast radius |

---

## Model Authorization Queue

When a model requests an action requiring authorization:

### Flow

1. **Model calls restricted action**
   ```
   crm_action(domain="contact", action="delete", data={id: "..."})
   ```

2. **API returns authorization_required**
   ```json
   {
     "status": "authorization_required",
     "queue_id": "auth-456",
     "reason": "Customer has 15 tickets worth $4,500",
     "message": "Queued for your authorization."
   }
   ```

3. **Model informs user**
   > "I've queued that deletion for your authorization. The Johnsons have significant history, so I need you to confirm at /authorizations."

4. **Human reviews in web UI**
   - Sees action details, model's reasoning
   - Clicks: **Allow Once** | **Allow Always** | **Deny**

5. **Model polls or receives callback**
   - On authorized: action executes
   - On denied: model receives denial note

### Web UI (`/authorizations`)

```
┌─────────────────────────────────────────────────────────────────┐
│  Model Authorization Queue                           [2 pending] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ DELETE CUSTOMER                              2 minutes ago  ││
│  │ ───────────────────────────────────────────────────────────││
│  │ Customer: Johnson Family                                    ││
│  │ Reason: Has 15 completed tickets worth $4,500               ││
│  │                                                             ││
│  │ Model's reasoning:                                          ││
│  │ "User confirmed Johnsons moved out of state."               ││
│  │                                                             ││
│  │ [Allow Once]  [Allow Always]  [Deny]                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Authorization Options

| Option | Effect |
|--------|--------|
| **Allow Once** | Execute this action only. Permission level unchanged. |
| **Allow Always** | Execute + upgrade action to `unrestricted` for future. |
| **Deny** | Block action. Optional note sent to model. |

---

## Example Conversations

### Morning Briefing

```
Human: "What's on today?"

Model uses: daily_briefing()

Model: "Here's your briefing for January 15th:

**Today's Schedule (4 appointments)**
- 9:00 AM: Johnson residence - Window cleaning (3 hrs)
- 1:00 PM: Smith Dental - Exterior windows (2 hrs)
- 3:30 PM: Garcia home - Screen cleaning (1 hr)
- 5:00 PM: Park Place HOA - Common areas (2 hrs)

**Pending Leads (2 new)**
- Mary Thompson (high urgency) - wants quote for large home
- Riverside Apartments - bulk pricing inquiry

**Overdue Invoices (1)**
- Invoice #1234 to Wilson - $450, 15 days overdue

Want me to handle any of these?"
```

### Handling a Phone Call

```
Human: "Just got off the phone. Elderly woman named Martha, lives on 456 Oak
Street in Madison. Large Victorian, 25+ windows. Husband passed last year.
Wants a quote, interested in regular service."

Model uses: process_lead(
  raw_notes="Elderly woman Martha, 456 Oak Street Madison. Large Victorian
  25+ windows. Husband passed last year, can't do outdoor maintenance.
  Wants quote, interested in regular service.",
  source="phone_call",
  urgency="medium",
  schedule_followup=true,
  followup_date="3 days"
)

Model: "I've created Martha's lead record. Extracted:
- Name: Martha
- Address: 456 Oak Street, Madison
- Property: Large Victorian, 25+ windows
- Context: Recently widowed, needs ongoing help
- Interest: Quote + potential recurring service

Follow-up reminder set for 3 days. Want me to schedule a quote visit?"
```

### Reschedule Request

```
Human: "Mrs. Garcia just called - needs to move her 3:30 to tomorrow afternoon."

Model uses: crm_query(type="tickets", filters={date: "today", search: "Garcia"})
Model uses: handle_reschedule_request(
  ticket_id="ticket-789",
  new_date="tomorrow",
  new_time="afternoon",
  reason="Customer request - scheduling conflict"
)

Model: "Done! Rescheduled Mrs. Garcia's screen cleaning:
- Old: Today at 3:30 PM
- New: Tomorrow at 2:00 PM

Sent her a confirmation. You now have a gap 3:30-5:00 PM before Park Place.
Want me to check the waitlist for that slot?"
```

### Authorization Required

```
Human: "Delete the Johnson account."

Model uses: crm_action(
  domain="contact",
  action="delete",
  data={id: "cust-123"},
  reasoning="User requested. Johnsons confirmed moved out of state."
)

API returns: authorization_required

Model: "I've queued that deletion for your authorization. The Johnsons have
15 completed tickets worth $4,500 - that's significant history to remove.

You can approve at /authorizations. I've noted that they moved out of state."
```

---

## Running the MCP Server

```bash
# Start CRM API
uvicorn main:app --port 8000

# Start MCP server (connects to CRM API)
python -m mcp.server \
  --api-url http://localhost:8000 \
  --token YOUR_API_TOKEN
```

### Configuration

| Env Var | Description | Default |
|---------|-------------|---------|
| `CRM_API_URL` | CRM API base URL | `http://localhost:8000` |
| `CRM_API_TOKEN` | Authentication token | Required |
| `MCP_LOG_LEVEL` | Logging level | `INFO` |

---

## API Reference

### Capabilities Endpoint

```
GET /api/capabilities
```

Returns all available domains, actions, data types, and their schemas. Auto-generated from domain handler registrations.

**Response:**
```json
{
  "success": true,
  "data": {
    "version": "1.0",
    "domains": [
      {
        "domain": "ticket",
        "description": "Ticket lifecycle management",
        "actions": [
          {
            "name": "create",
            "permission": "unrestricted",
            "parameters": {...}
          },
          {
            "name": "cancel",
            "permission": "soft_limit",
            "parameters": {...}
          }
        ]
      }
    ],
    "data_types": [
      {
        "type": "tickets",
        "filters": ["status", "date", "customer_id"],
        "includes": ["line_items", "customer", "address"]
      }
    ]
  }
}
```

### Authorization Endpoints

```
GET /api/authorizations
```
List pending authorization requests.

```
POST /api/authorizations/{id}
{
  "decision": "authorized" | "denied",
  "notes": "Optional explanation",
  "upgrade_permission": true  // For "Allow Always"
}
```
Decide on an authorization request.

```
GET /api/authorizations/{id}
```
Check status of specific request (for model polling).
