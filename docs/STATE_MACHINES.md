# State Machines

Valid state transitions for entities with status fields. Invalid transitions should raise `INVALID_STATUS_TRANSITION`.

---

## Ticket Status

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
              ┌──────────┐                                    │
              │          │                                    │
    create ──►│ scheduled │──────────────────────────────────►│
              │          │           cancel                   │
              └────┬─────┘                                    │
                   │                                          │
                   │ clock_in                                 │
                   ▼                                          │
              ┌──────────┐                                    │
              │          │                                    │
              │in_progress├──────────────────────────────────►│
              │          │           cancel                   │
              └────┬─────┘                                    │
                   │                                     ┌────┴─────┐
                   │ close_out                           │          │
                   ▼                                     │ cancelled │
              ┌──────────┐                               │          │
              │          │                               └──────────┘
              │completed │
              │          │
              └──────────┘
                   ▲
                   │
                   └── IMMUTABLE (closed_at set)
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `scheduled` | `create()` | Default state |
| `scheduled` | `in_progress` | `clock_in()` | Sets `clock_in_at` |
| `scheduled` | `cancelled` | `cancel()` | Can cancel before starting |
| `in_progress` | `completed` | `close_out()` | Sets `closed_at`, ticket becomes immutable |
| `in_progress` | `cancelled` | `cancel()` | Rare, but allowed |

**Invalid:**
- `completed` → anything (immutable)
- `cancelled` → anything (terminal)
- `scheduled` → `completed` (must go through `in_progress`)

---

## Ticket Confirmation Status

```
              ┌──────────┐
              │          │
    create ──►│ pending  │
              │          │
              └────┬─────┘
                   │
       ┌───────────┼───────────┐
       │           │           │
       ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌────────────────────┐
  │         │ │         │ │                    │
  │confirmed│ │declined │ │reschedule_requested│
  │         │ │         │ │                    │
  └─────────┘ └─────────┘ └─────────┬──────────┘
                                    │
                                    │ after reschedule
                                    ▼
                               ┌─────────┐
                               │         │
                               │ pending │ (new ticket)
                               │         │
                               └─────────┘
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `pending` | ticket created | Default |
| `pending` | `confirmed` | customer clicks Accept | Sets `confirmed_at` |
| `pending` | `declined` | customer clicks Decline | Needs rescheduling |
| `pending` | `reschedule_requested` | customer clicks Request Change | Needs follow-up |
| `reschedule_requested` | (new ticket) | manual reschedule | Original ticket may be cancelled |

**Notes:**
- `confirmed` and `declined` are terminal for that ticket
- `reschedule_requested` typically leads to cancelling and creating new ticket

---

## Invoice Status

```
              ┌──────────┐
              │          │
    create ──►│  draft   │◄──────────────────────────────┐
              │          │                               │
              └────┬─────┘                               │
                   │                                     │
                   │ send()                              │
                   ▼                                     │
              ┌──────────┐                               │
              │          │────────────────────┐          │
              │   sent   │                    │          │
              │          │◄───────────┐       │          │
              └────┬─────┘            │       │          │
                   │                  │       │          │
       ┌───────────┴───────────┐      │       │          │
       │                       │      │       │          │
       │ partial_payment       │ full │       │          │
       ▼                       │      │       │          │
  ┌─────────┐                  │      │       │          │
  │         │                  │      │       │          │
  │ partial │──────────────────┘      │       │          │
  │         │    more payment         │       │          │
  └────┬────┘                         │       │          │
       │                              │       │          │
       │ final payment                │       │ void()   │ void()
       ▼                              ▼       │          │
  ┌──────────┐                   ┌─────────┐  │          │
  │          │                   │         │──┘          │
  │   paid   │                   │   void  │─────────────┘
  │          │                   │         │
  └──────────┘                   └─────────┘
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `draft` | `create()` | Default |
| `draft` | `sent` | `send()` | Sets `sent_at` |
| `draft` | `void` | `void()` | Discard before sending |
| `sent` | `partial` | `record_payment()` | When `amount_paid < total_amount` |
| `sent` | `paid` | `record_payment()` | When `amount_paid >= total_amount` |
| `sent` | `void` | `void()` | Rare - sets `voided_at` |
| `partial` | `partial` | `record_payment()` | Still not fully paid |
| `partial` | `paid` | `record_payment()` | Final payment received |

**Invalid:**
- `paid` → anything (terminal, financial record)
- `void` → anything (terminal)

---

## Scheduled Message Status

```
              ┌──────────┐
              │          │
   schedule──►│ pending  │
              │          │
              └────┬─────┘
                   │
       ┌───────────┼───────────┐
       │           │           │
       │ cancel()  │ send()    │ send() fails
       ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐
  │         │ │         │ │         │
  │cancelled│ │  sent   │ │ failed  │
  │         │ │         │ │         │
  └─────────┘ └─────────┘ └────┬────┘
                               │
                               │ retry()
                               ▼
                          ┌─────────┐
                          │         │
                          │ pending │
                          │         │
                          └─────────┘
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `pending` | `schedule()` | Default |
| `pending` | `sent` | message worker | Sets `sent_at`, logs to `message_log` |
| `pending` | `cancelled` | `cancel()` | Manual cancellation |
| `pending` | `failed` | message worker | Delivery failed, logs error |
| `failed` | `pending` | `retry()` | Increments `retry_count`, reschedules |

**Notes:**
- `sent` is terminal
- `cancelled` is terminal
- `failed` can retry up to configured max attempts

---

## Lead Status

```
              ┌──────────┐
              │          │
    create ──►│   new    │
              │          │
              └────┬─────┘
                   │
       ┌───────────┼───────────────────────────┐
       │           │                           │
       │ contact() │ qualify()                 │ archive()
       ▼           │                           ▼
  ┌──────────┐     │                     ┌──────────┐
  │          │     │                     │          │
  │contacted │     │                     │ archived │
  │          │     │                     │          │
  └────┬─────┘     │                     └──────────┘
       │           │                           ▲
       │ qualify() │                           │
       ▼           ▼                           │
  ┌────────────────────┐                       │
  │                    │                       │
  │     qualified      │───────────────────────┤ archive()
  │                    │                       │
  └─────────┬──────────┘                       │
            │                                  │
            │ convert()                        │
            ▼                                  │
  ┌──────────┐                                 │
  │          │                                 │
  │converted │─────────────────────────────────┘
  │          │    (cannot archive converted)
  └──────────┘
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `new` | `create()` | Default state |
| `new` | `contacted` | `contact()` | Mark that follow-up happened |
| `new` | `qualified` | `qualify()` | Skip contacted if immediately qualified |
| `new` | `converted` | `convert()` | Quick conversion (immediate sale) |
| `new` | `archived` | `archive()` | Dead lead |
| `contacted` | `qualified` | `qualify()` | Confirmed interest |
| `contacted` | `converted` | `convert()` | Direct conversion |
| `contacted` | `archived` | `archive()` | No interest after contact |
| `qualified` | `converted` | `convert()` | Creates customer, sets `converted_customer_id` |
| `qualified` | `archived` | `archive()` | Lost opportunity |

**Terminal States:**
- `converted` - Lead became a customer (immutable)
- `archived` - Lead is dead/lost

**Conversion:**
When `convert()` is called:
1. Creates new customer record from lead data
2. Sets `converted_at` timestamp
3. Sets `converted_customer_id` to link lead → customer
4. Lead becomes immutable

**Notes:**
- Leads can be converted from any non-terminal state
- Archive is available from any non-terminal state except `converted`
- No "unarchive" - create a new lead if needed

---

## Model Authorization Status

```
              ┌──────────┐
              │          │
   request ──►│ pending  │
              │          │
              └────┬─────┘
                   │
       ┌───────────┼───────────┐
       │           │           │
       │ authorize │ deny()    │ (timeout)
       ▼           ▼           ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │          │ │          │ │          │
  │authorized│ │  denied  │ │ expired  │
  │          │ │          │ │          │
  └──────────┘ └──────────┘ └──────────┘
```

**Transitions:**

| From | To | Trigger | Notes |
|------|-----|---------|-------|
| (new) | `pending` | Model requests restricted action | Auto-created |
| `pending` | `authorized` | Human clicks "Allow Once" or "Allow Always" | Action executes |
| `pending` | `denied` | Human clicks "Deny" | Action blocked, note returned to model |
| `pending` | `expired` | Timeout (default 24 hours) | Auto-transition by worker |

**Terminal States:**
- `authorized` - Human approved, action executed
- `denied` - Human rejected
- `expired` - No decision made in time

**Notes:**
- All states are terminal - no re-review
- If expired and still needed, model must create new request
- "Allow Always" also upgrades the action's permission level for future calls

---

## State Validation Pattern

Enforce valid transitions in service methods:

```python
VALID_TICKET_TRANSITIONS = {
    "scheduled": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),  # Terminal
    "cancelled": set(),  # Terminal
}

def _validate_transition(self, current: str, target: str) -> None:
    """Raise if transition is invalid."""
    valid_targets = VALID_TICKET_TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise ValueError(
            f"Invalid status transition: {current} → {target}. "
            f"Valid transitions from {current}: {valid_targets or 'none (terminal state)'}"
        )
```

Usage:
```python
def cancel(self, ticket_id: UUID) -> Ticket:
    ticket = self.get_by_id(ticket_id)
    self._validate_transition(ticket.status, "cancelled")
    # ... proceed with cancellation
```

---

## Quick Reference

| Entity | States | Terminal States |
|--------|--------|-----------------|
| Ticket status | scheduled, in_progress, completed, cancelled | completed, cancelled |
| Ticket confirmation | pending, confirmed, declined, reschedule_requested | confirmed, declined |
| Invoice | draft, sent, partial, paid, void | paid, void |
| Scheduled Message | pending, sent, cancelled, failed | sent, cancelled |
| Lead | new, contacted, qualified, converted, archived | converted, archived |
| Model Authorization | pending, authorized, denied, expired | authorized, denied, expired |
