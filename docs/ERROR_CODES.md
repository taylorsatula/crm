# Error Code Registry

Canonical reference for all error codes in the CRM system. Every error returned by the API uses one of these codes.

**Rules:**
1. Never invent new codes without adding them here first
2. Codes are SCREAMING_SNAKE_CASE
3. Messages are human-readable, codes are machine-parseable
4. Client code switches on `error.code`, displays `error.message`

---

## Authentication & Authorization

### `NOT_AUTHENTICATED`
**HTTP Status:** 401

**When to use:**
- Request to protected endpoint without session cookie
- Session cookie present but empty/malformed

**Example message:** `"Authentication required"`

**Client handling:** Redirect to login page. Clear any stale local state.

---

### `SESSION_EXPIRED`
**HTTP Status:** 401

**When to use:**
- Session token was valid but has expired
- Session was revoked (logout from another device)

**Example message:** `"Your session has expired. Please sign in again."`

**Client handling:** Redirect to login page. Show message explaining session expired (not an error on their part).

---

### `INVALID_TOKEN`
**HTTP Status:** 400

**When to use:**
- Magic link token doesn't exist
- Magic link token already used
- Magic link token expired

**Example message:**
- `"This link is invalid or has expired."`
- `"This link has already been used."`

**Client handling:** Show message with option to request new magic link. Don't reveal which specific reason (security).

---

### `RATE_LIMITED`
**HTTP Status:** 429

**When to use:**
- Too many magic link requests for an email
- Too many failed auth attempts
- Any rate-limited operation

**Example message:** `"Too many attempts. Please try again in 5 minutes."`

**Response includes:** `retry_after_seconds` in data for Retry-After header

**Client handling:** Disable submit button, show countdown timer. Don't let user spam requests.

---

## Resource Errors

### `NOT_FOUND`
**HTTP Status:** 404

**When to use:**
- Entity ID doesn't exist
- Entity exists but is soft-deleted
- Entity exists but belongs to different user (RLS filtered it out)

**Example messages:**
- `"Contact not found"`
- `"Ticket not found"`
- `"Service not found"`

**Client handling:** Show "not found" state. If navigating to stale link, offer to go back to list.

**Security note:** Use this for RLS-filtered entities too. Never reveal that an entity exists but user doesn't have access.

---

### `ALREADY_EXISTS`
**HTTP Status:** 409

**When to use:**
- Creating entity with unique constraint violation
- Email already registered (but be careful about leaking this)

**Example message:** `"A contact with this email already exists."`

**Client handling:** Highlight conflicting field, suggest finding existing record.

---

## Validation Errors

### `VALIDATION_ERROR`
**HTTP Status:** 422

**When to use:**
- Request body fails Pydantic validation
- Business rule validation fails (email format, required fields)
- Field value out of acceptable range

**Example messages:**
- `"name: field required"`
- `"email: invalid email format"`
- `"scheduled_at: must be in the future"`
- `"quantity: must be greater than 0"`

**Client handling:** Parse message to highlight specific fields. Show inline validation errors.

---

### `INVALID_REQUEST`
**HTTP Status:** 400

**When to use:**
- Request structure is malformed (not validation, just wrong shape)
- Missing required query parameters
- Unknown type/domain/action requested

**Example messages:**
- `"Unknown type: contactz. Valid types: contacts, tickets, services"`
- `"Unknown action: clse. Available: create, update, delete, close_out"`
- `"Missing required parameter: type"`

**Client handling:** This is usually a client bug, not user error. Log it. Show generic error to user.

---

## Ticket Lifecycle Errors

### `TICKET_IMMUTABLE`
**HTTP Status:** 409

**When to use:**
- Attempting to modify a closed ticket
- Attempting to add line items to closed ticket
- Attempting to change notes on closed ticket

**Example message:** `"This ticket has been closed and cannot be modified."`

**Client handling:** Refresh ticket state (may be stale). Show read-only view. If user needs changes, explain they must contact support or create adjustment.

---

### `TICKET_NOT_CLOCKABLE`
**HTTP Status:** 409

**When to use:**
- Clock in when not in SCHEDULED status
- Clock in when already clocked in
- Clock out when not clocked in
- Clock out when already clocked out

**Example messages:**
- `"Cannot clock in: ticket is not scheduled"`
- `"Already clocked in"`
- `"Cannot clock out: not clocked in"`

**Client handling:** Refresh ticket state. Button states should reflect actual status.

---

### `TICKET_NOT_CLOSEABLE`
**HTTP Status:** 409

**When to use:**
- Attempting close-out on cancelled ticket
- Attempting close-out on already-closed ticket
- Attempting close-out without required data (no line items, etc.)

**Example messages:**
- `"Cannot close: ticket has no line items"`
- `"Cannot close: ticket is cancelled"`
- `"Ticket already closed"`

**Client handling:** Show appropriate state. For missing data, guide user to add required items first.

---

### `INVALID_STATUS_TRANSITION`
**HTTP Status:** 409

**When to use:**
- Any state machine violation not covered by specific codes above
- Attempting to un-cancel a ticket
- Attempting to reopen a closed ticket

**Example message:** `"Cannot transition from 'completed' to 'in_progress'"`

**Client handling:** Refresh state. This usually means client has stale data.

---

## Contact & Address Errors

### `CONTACT_HAS_DEPENDENCIES`
**HTTP Status:** 409

**When to use:**
- Deleting contact with open tickets
- Deleting contact with unpaid invoices
- Deleting contact with pending scheduled messages

**Example message:** `"Cannot delete contact: 3 open tickets exist. Close or reassign them first."`

**Client handling:** Show list of blocking dependencies with links to resolve them.

---

### `ADDRESS_IN_USE`
**HTTP Status:** 409

**When to use:**
- Deleting address that's used by scheduled tickets

**Example message:** `"Cannot delete address: 2 upcoming appointments are scheduled here."`

**Client handling:** Show blocking tickets. Offer to reschedule or reassign.

---

## Invoice Errors

### `INVOICE_ALREADY_SENT`
**HTTP Status:** 409

**When to use:**
- Modifying invoice that's already been sent
- Changing line items on sent invoice

**Example message:** `"Invoice has been sent and cannot be modified. Create a new invoice or void this one."`

**Client handling:** Show invoice as read-only. Offer void option if appropriate.

---

### `INVOICE_ALREADY_PAID`
**HTTP Status:** 409

**When to use:**
- Voiding a paid invoice
- Modifying a paid invoice

**Example message:** `"Invoice has been marked as paid and cannot be modified."`

**Client handling:** Show paid state. If truly incorrect, explain refund process.

---

## Service Catalog Errors

### `SERVICE_IN_USE`
**HTTP Status:** 409

**When to use:**
- Deleting service that appears on open tickets
- Deactivating service with scheduled appointments

**Example message:** `"Cannot delete service: used in 5 open tickets."`

**Client handling:** Offer to deactivate instead of delete, or show blocking tickets.

---

## Scheduled Message Errors

### `MESSAGE_ALREADY_SENT`
**HTTP Status:** 409

**When to use:**
- Cancelling message that's already been sent
- Modifying sent message

**Example message:** `"Message has already been sent."`

**Client handling:** Show sent state. Cannot undo.

---

### `MESSAGE_SEND_FAILED`
**HTTP Status:** 500 (or store as status on entity)

**When to use:**
- Email delivery failed
- Stored as status on the message entity, not thrown as API error

**Example message:** `"Message delivery failed: invalid email address"`

**Client handling:** Show retry option. Show specific failure reason if available.

---

## Lead Errors

### `LEAD_NOT_FOUND`
**HTTP Status:** 404

**When to use:**
- Lead ID doesn't exist
- Lead exists but is soft-deleted
- Lead exists but belongs to different user (RLS filtered)

**Example message:** `"Lead not found"`

**Client handling:** Show "not found" state. May be stale link.

---

### `LEAD_ALREADY_CONVERTED`
**HTTP Status:** 409

**When to use:**
- Attempting to modify a converted lead
- Attempting to convert an already-converted lead
- Attempting to archive a converted lead
- Attempting any state transition on a converted lead

**Example message:** `"Lead has been converted to a customer and cannot be modified."`

**Response includes:** `converted_customer_id` in data for linking to customer record

**Client handling:** Show converted state. Link to the customer record.

---

### `LEAD_ARCHIVED`
**HTTP Status:** 409

**When to use:**
- Attempting to contact an archived lead
- Attempting to qualify an archived lead
- Attempting to convert an archived lead

**Example message:** `"Lead has been archived."`

**Client handling:** Show archived state. Suggest creating new lead if prospect re-engages.

---

### `LEAD_INVALID_TRANSITION`
**HTTP Status:** 409

**When to use:**
- Invalid state machine transition (uses `INVALID_STATUS_TRANSITION` pattern)
- See STATE_MACHINES.md for valid lead transitions

**Example messages:**
- `"Cannot transition from 'converted' to 'contacted'"`
- `"Cannot archive a converted lead"`

**Client handling:** Refresh lead state. Show current status.

---

## Model Authorization Errors

### `AUTHORIZATION_REQUIRED`
**HTTP Status:** 202 (Accepted)

**When to use:**
- Model requested an action that requires human authorization
- Action has been queued for review
- NOT an error - indicates pending human review

**Example message:** `"This action requires authorization. Request queued for review."`

**Response includes:**
- `queue_id` - ID of the authorization request
- `reason` - Why authorization is required
- `expires_at` - When the request will expire if not acted upon

**Client/MCP handling:** Inform user action is pending. Poll for result or wait for callback.

---

### `AUTHORIZATION_DENIED`
**HTTP Status:** 403

**When to use:**
- Human reviewed the authorization request and denied it
- Model attempted to re-execute a denied action

**Example message:** `"Authorization denied: [human's note if provided]"`

**Response includes:**
- `queue_id` - Original authorization request ID
- `denied_by` - Who denied it
- `denied_at` - When
- `notes` - Human's explanation (if provided)

**Client/MCP handling:** Inform user. Do not retry without new user instruction.

---

### `AUTHORIZATION_EXPIRED`
**HTTP Status:** 410 (Gone)

**When to use:**
- Authorization request was not reviewed before expiration
- Model attempted to execute an action with an expired authorization

**Example message:** `"Authorization request expired. Please retry to create a new request."`

**Client/MCP handling:** Create new authorization request if action still needed.

---

### `AUTHORIZATION_PENDING`
**HTTP Status:** 202 (Accepted)

**When to use:**
- Model polling for authorization result that's still pending
- NOT an error - indicates still waiting for human review

**Example message:** `"Authorization pending human review."`

**Response includes:**
- `queue_id` - Authorization request ID
- `requested_at` - When queued
- `expires_at` - Deadline for human review

**Client/MCP handling:** Continue polling or wait.

---

## Infrastructure Errors

### `INTERNAL_ERROR`
**HTTP Status:** 500

**When to use:**
- Unexpected exception
- Bug in application code
- Any error that shouldn't happen

**Example message:** `"An unexpected error occurred"` (never expose details)

**Logging:** Full stack trace server-side. Include request_id for correlation.

**Client handling:** Show generic error. Include request_id so user can report it. Offer retry.

---

### `SERVICE_UNAVAILABLE`
**HTTP Status:** 503

**When to use:**
- Database unreachable
- Valkey unreachable
- Vault unreachable
- Any required infrastructure down

**Example message:** `"Service temporarily unavailable. Please try again."`

**Client handling:** Show maintenance-style message. Auto-retry with backoff. Check `/health` endpoint.

---

### `LLM_UNAVAILABLE`
**HTTP Status:** 503

**When to use:**
- Local LLM endpoint unreachable
- Remote LLM fallback also failed
- LLM timeout during extraction

**Example message:** `"Note processing temporarily unavailable. You can continue without extracted attributes."`

**Client handling:** Allow close-out to proceed without extraction. Flag for later processing or manual entry.

---

## Error Response Format

All errors follow this structure:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "TICKET_IMMUTABLE",
    "message": "This ticket has been closed and cannot be modified."
  },
  "meta": {
    "timestamp": "2024-01-15T14:30:00Z",
    "request_id": "req-abc123"
  }
}
```

---

## Error Code to HTTP Status Mapping

| Code | HTTP Status | Category |
|------|-------------|----------|
| `NOT_AUTHENTICATED` | 401 | Auth |
| `SESSION_EXPIRED` | 401 | Auth |
| `INVALID_TOKEN` | 400 | Auth |
| `RATE_LIMITED` | 429 | Auth |
| `NOT_FOUND` | 404 | Resource |
| `ALREADY_EXISTS` | 409 | Resource |
| `VALIDATION_ERROR` | 422 | Validation |
| `INVALID_REQUEST` | 400 | Validation |
| `TICKET_IMMUTABLE` | 409 | Business Logic |
| `TICKET_NOT_CLOCKABLE` | 409 | Business Logic |
| `TICKET_NOT_CLOSEABLE` | 409 | Business Logic |
| `INVALID_STATUS_TRANSITION` | 409 | Business Logic |
| `CONTACT_HAS_DEPENDENCIES` | 409 | Business Logic |
| `ADDRESS_IN_USE` | 409 | Business Logic |
| `INVOICE_ALREADY_SENT` | 409 | Business Logic |
| `INVOICE_ALREADY_PAID` | 409 | Business Logic |
| `SERVICE_IN_USE` | 409 | Business Logic |
| `MESSAGE_ALREADY_SENT` | 409 | Business Logic |
| `LEAD_NOT_FOUND` | 404 | Resource |
| `LEAD_ALREADY_CONVERTED` | 409 | Business Logic |
| `LEAD_ARCHIVED` | 409 | Business Logic |
| `LEAD_INVALID_TRANSITION` | 409 | Business Logic |
| `AUTHORIZATION_REQUIRED` | 202 | Model Authorization |
| `AUTHORIZATION_DENIED` | 403 | Model Authorization |
| `AUTHORIZATION_EXPIRED` | 410 | Model Authorization |
| `AUTHORIZATION_PENDING` | 202 | Model Authorization |
| `INTERNAL_ERROR` | 500 | Infrastructure |
| `SERVICE_UNAVAILABLE` | 503 | Infrastructure |
| `LLM_UNAVAILABLE` | 503 | Infrastructure |

---

## Adding New Error Codes

When you need a new error code:

1. **Check this list first.** Often an existing code fits.
2. **Add it here before using it.** Document when to use, example message, client handling.
3. **Choose the right HTTP status:**
   - 400: Client sent bad request (malformed, missing params)
   - 401: Not authenticated
   - 404: Resource doesn't exist
   - 409: Conflict with current state (most business logic errors)
   - 422: Validation failed on well-formed request
   - 429: Rate limited
   - 500: Server bug
   - 503: Infrastructure down
4. **Name it clearly.** `TICKET_IMMUTABLE` not `ERR_042`.
5. **Add to ErrorCodes class** in `api/base.py`.

---

## Client-Side Error Handling Pattern

```javascript
async function apiCall(endpoint, options) {
  const response = await fetch(endpoint, options);
  const data = await response.json();

  if (!data.success) {
    switch (data.error.code) {
      case 'NOT_AUTHENTICATED':
      case 'SESSION_EXPIRED':
        redirectToLogin();
        break;

      case 'RATE_LIMITED':
        showRateLimitMessage(data.error.message);
        break;

      case 'VALIDATION_ERROR':
        showFieldErrors(data.error.message);
        break;

      case 'NOT_FOUND':
        showNotFound();
        break;

      case 'TICKET_IMMUTABLE':
      case 'TICKET_NOT_CLOCKABLE':
      case 'INVALID_STATUS_TRANSITION':
      case 'LEAD_ALREADY_CONVERTED':
      case 'LEAD_ARCHIVED':
      case 'LEAD_INVALID_TRANSITION':
        // Stale state - refresh and show current
        refreshAndShowState();
        break;

      case 'SERVICE_UNAVAILABLE':
      case 'LLM_UNAVAILABLE':
        showRetryMessage();
        break;

      case 'AUTHORIZATION_REQUIRED':
      case 'AUTHORIZATION_PENDING':
        // Action queued for human review (MCP responses)
        showAuthorizationPending(data.data.queue_id);
        break;

      case 'AUTHORIZATION_DENIED':
        // Human denied the model's request
        showAuthorizationDenied(data.data.notes);
        break;

      case 'AUTHORIZATION_EXPIRED':
        // Request expired before human reviewed it
        showAuthorizationExpired();
        break;

      default:
        showGenericError(data.error.message, data.meta.request_id);
    }

    throw new ApiError(data.error.code, data.error.message);
  }

  return data.data;
}
```
