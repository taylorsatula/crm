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
