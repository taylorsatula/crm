# Phase 4: API Routes

**Goal**: Expose domain functionality via HTTP with consistent patterns.

**Estimated files**: 4
**Dependencies**: Phases 0-3 complete

---

## Prerequisites

Before starting Phase 4, ensure:

1. All previous phases complete and verified
2. All core services tested and working
3. Auth middleware functional

---

## 4.1 api/health.py

**Purpose**: Infrastructure health checks.

### Implementation

```python
from fastapi import APIRouter

from clients.postgres_client import PostgresClient, PostgresError
from clients.valkey_client import ValkeyClient, ValkeyError
from clients.vault_client import VaultClient, VaultError
from api.base import success_response, error_response, APIResponse, ErrorCodes


router = APIRouter(tags=["health"])


def create_health_router(
    postgres: PostgresClient,
    valkey: ValkeyClient,
    vault: VaultClient
) -> APIRouter:
    """Factory to create health router with dependencies."""

    router = APIRouter(tags=["health"])

    @router.get("/health")
    async def health_check() -> APIResponse:
        """
        Check all infrastructure dependencies.

        Returns 200 with status of each component.
        Returns 503 if any critical component is unhealthy.
        """
        checks = {}
        all_healthy = True

        # Same pattern for each dependency: try health_check(), catch specific error
        for name, client, error_type in [
            ("database", postgres, PostgresError),
            ("cache", valkey, ValkeyError),
            ("vault", vault, VaultError),
        ]:
            try:
                client.health_check()
                checks[name] = {"status": "healthy"}
            except error_type as e:
                checks[name] = {"status": "unhealthy", "error": str(e)}
                all_healthy = False

        if all_healthy:
            return success_response({"status": "healthy", "checks": checks})
        else:
            return error_response(
                ErrorCodes.SERVICE_UNAVAILABLE,
                "One or more services unhealthy",
            )

    @router.get("/health/ready")
    async def readiness_check() -> APIResponse:
        """
        Readiness probe for Kubernetes/load balancers.

        Only checks if the app can handle requests.
        """
        try:
            postgres.health_check()
            return success_response({"status": "ready"})
        except Exception:
            return error_response(ErrorCodes.SERVICE_UNAVAILABLE, "Not ready")

    @router.get("/health/live")
    async def liveness_check() -> APIResponse:
        """
        Liveness probe for Kubernetes.

        Always returns OK if the process is running.
        """
        return success_response({"status": "alive"})

    return router
```

---

## 4.2 api/data.py

**Purpose**: Unified read operations with consistent patterns.

### Implementation

```python
from uuid import UUID
from fastapi import APIRouter, Query, Request, Depends

from api.base import success_response, error_response, APIResponse, ErrorCodes


router = APIRouter(prefix="/api/data", tags=["data"])


def create_data_router(services: dict) -> APIRouter:
    """
    Factory to create data router with service dependencies.

    Args:
        services: Dict mapping type names to service instances
                  {"contacts": contact_service, "tickets": ticket_service, ...}
    """

    router = APIRouter(prefix="/api/data", tags=["data"])

    @router.get("")
    async def get_data(
        request: Request,
        type: str = Query(..., description="Entity type: contacts, tickets, services, etc."),
        id: UUID | None = Query(None, description="Specific entity ID"),
        search: str | None = Query(None, description="Search query"),
        include: str | None = Query(None, description="Comma-separated relations to include"),
        limit: int = Query(100, ge=1, le=500),
    ) -> APIResponse:
        """
        Unified data retrieval endpoint.

        Supports:
        - Single entity lookup: ?type=contacts&id=xxx
        - List: ?type=contacts&limit=100
        - Search: ?type=contacts&search=john

        Returns:
        - Single entity: {success: true, data: {entity}}
        - List: {success: true, data: [{item}, {item}, ...]}
        """
        service = services.get(type)
        if not service:
            return error_response(
                ErrorCodes.INVALID_REQUEST,
                f"Unknown type: {type}. Valid types: {', '.join(services.keys())}"
            )

        includes = include.split(",") if include else []

        try:
            # Single entity lookup
            if id:
                if includes and hasattr(service, "get_with_relations"):
                    result = service.get_with_relations(id, includes)
                else:
                    result = service.get_by_id(id)

                if not result:
                    return error_response(ErrorCodes.NOT_FOUND, f"{type} not found")

                return success_response(result.model_dump(mode="json"))

            # Search
            if search and hasattr(service, "search"):
                items = service.search(search, limit=limit)
            # List
            elif hasattr(service, "list"):
                items = service.list(limit=limit)
            else:
                return error_response(
                    ErrorCodes.INVALID_REQUEST,
                    f"List operation not supported for {type}"
                )

            return success_response([item.model_dump(mode="json") for item in items])

        except ValueError as e:
            return error_response(ErrorCodes.VALIDATION_ERROR, str(e))
        except Exception as e:
            # Log error
            return error_response(ErrorCodes.INTERNAL_ERROR, "An error occurred")

    @router.get("/types")
    async def list_types() -> APIResponse:
        """List available entity types."""
        return success_response({
            "types": list(services.keys())
        })

    return router


# Type-specific routes for complex queries

def create_ticket_data_routes(ticket_service) -> APIRouter:
    """Additional routes specific to tickets."""

    router = APIRouter(prefix="/api/data/tickets", tags=["data", "tickets"])

    @router.get("/today")
    async def get_todays_tickets() -> APIResponse:
        """Get tickets scheduled for today."""
        from utils.timezone import now_utc
        from datetime import timedelta

        today_start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        tickets = ticket_service.list_for_date_range(today_start, today_end)
        return success_response({
            "items": [t.model_dump(mode="json") for t in tickets],
            "date": today_start.date().isoformat()
        })

    @router.get("/current")
    async def get_current_ticket() -> APIResponse:
        """
        Get the ticket for the current time slot.

        Used for quick-action in header during close-out.
        """
        ticket = ticket_service.get_current_ticket()
        if not ticket:
            return success_response({"ticket": None})
        return success_response({"ticket": ticket.model_dump(mode="json")})

    return router
```

---

## 4.3 api/actions.py

**Purpose**: Unified mutation operations with audit trail.

### Implementation

```python
from uuid import UUID
from typing import Any
from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.base import success_response, error_response, APIResponse, ErrorCodes


class ActionRequest(BaseModel):
    """Request body for action execution."""
    domain: str  # "contact", "ticket", etc.
    action: str  # "create", "update", "close_out", etc.
    data: dict[str, Any]


router = APIRouter(prefix="/api/actions", tags=["actions"])


def create_actions_router(handlers: dict) -> APIRouter:
    """
    Factory to create actions router with domain handlers.

    Args:
        handlers: Dict mapping domain names to handler instances
                  {"contact": ContactActionHandler, "ticket": TicketActionHandler, ...}
    """

    router = APIRouter(prefix="/api/actions", tags=["actions"])

    @router.post("")
    async def execute_action(request: Request, body: ActionRequest) -> APIResponse:
        """
        Execute a domain action.

        Request format:
        {
            "domain": "ticket",
            "action": "close_out",
            "data": {
                "ticket_id": "...",
                "duration_minutes": 180,
                "notes": "..."
            }
        }

        All actions:
        - Require authentication (handled by middleware)
        - Generate audit trail entries
        - Return consistent response format
        """
        handler = handlers.get(body.domain)
        if not handler:
            return error_response(
                ErrorCodes.INVALID_REQUEST,
                f"Unknown domain: {body.domain}. Valid domains: {', '.join(handlers.keys())}"
            )

        action_method = getattr(handler, body.action, None)
        if not action_method or body.action.startswith("_"):
            available = [m for m in dir(handler) if not m.startswith("_") and callable(getattr(handler, m))]
            return error_response(
                ErrorCodes.INVALID_REQUEST,
                f"Unknown action: {body.action}. Available: {', '.join(available)}"
            )

        try:
            result = action_method(**body.data)

            # Convert Pydantic models to dict for response
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")

            return success_response(result)

        except ValueError as e:
            return error_response(ErrorCodes.VALIDATION_ERROR, str(e))
        except PermissionError as e:
            return error_response(ErrorCodes.NOT_AUTHENTICATED, str(e))
        except Exception as e:
            # Log the actual error
            import traceback
            traceback.print_exc()
            return error_response(ErrorCodes.INTERNAL_ERROR, "An error occurred")

    @router.get("/schema/{domain}")
    async def get_action_schema(domain: str) -> APIResponse:
        """
        Get available actions and their schemas for a domain.

        Useful for building dynamic UIs and validation.
        """
        handler = handlers.get(domain)
        if not handler:
            return error_response(ErrorCodes.NOT_FOUND, f"Unknown domain: {domain}")

        actions = {}
        for name in dir(handler):
            if name.startswith("_"):
                continue
            method = getattr(handler, name)
            if callable(method):
                # Extract type hints for parameters
                import inspect
                sig = inspect.signature(method)
                params = {}
                for param_name, param in sig.parameters.items():
                    if param_name == "self":
                        continue
                    params[param_name] = {
                        "required": param.default == inspect.Parameter.empty,
                        "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "any"
                    }
                actions[name] = {
                    "parameters": params,
                    "doc": method.__doc__
                }

        return success_response({
            "domain": domain,
            "actions": actions
        })

    return router


# Domain-specific action handlers
# Pattern: thin wrapper that validates params, calls service, returns model_dump(mode="json")

class ContactActionHandler:
    """Action handler for contact domain."""

    def __init__(self, contact_service, address_service):
        self.contact_service = contact_service
        self.address_service = address_service

    def create(self, name: str, email: str | None = None, phone: str | None = None, notes: str | None = None) -> dict:
        """Create a new contact."""
        from core.models.contact import ContactCreate
        data = ContactCreate(name=name, email=email, phone=phone, notes=notes)
        return self.contact_service.create(data).model_dump(mode="json")

    def update(self, contact_id: str, **fields) -> dict:
        """Update contact fields. Same pattern as create()."""
        from core.models.contact import ContactUpdate
        return self.contact_service.update(UUID(contact_id), ContactUpdate(**fields)).model_dump(mode="json")

    def delete(self, contact_id: str) -> dict:
        """Delete a contact."""
        self.contact_service.delete(UUID(contact_id))
        return {"deleted": True, "contact_id": contact_id}

    # Additional methods follow same pattern: add_address, etc.


class TicketActionHandler:
    """Action handler for ticket domain."""

    def __init__(self, ticket_service, line_item_service):
        self.ticket_service = ticket_service
        self.line_item_service = line_item_service

    # Simple CRUD methods follow ContactActionHandler pattern
    def create(self, contact_id: str, address_id: str, scheduled_at: str, scheduled_duration_minutes: int | None = None) -> dict:
        from core.models.ticket import TicketCreate
        from utils.timezone import parse_iso
        data = TicketCreate(contact_id=UUID(contact_id), address_id=UUID(address_id),
                           scheduled_at=parse_iso(scheduled_at), scheduled_duration_minutes=scheduled_duration_minutes)
        return self.ticket_service.create(data).model_dump(mode="json")

    def clock_in(self, ticket_id: str) -> dict:
        return self.ticket_service.clock_in(UUID(ticket_id)).model_dump(mode="json")

    def clock_out(self, ticket_id: str) -> dict:
        return self.ticket_service.clock_out(UUID(ticket_id)).model_dump(mode="json")

    # Close-out is more complex - two-phase flow
    def initiate_close_out(self, ticket_id: str, confirmed_duration_minutes: int, notes: str | None = None) -> dict:
        """Start close-out flow. Returns extracted attributes for review."""
        result = self.ticket_service.initiate_close_out(UUID(ticket_id), confirmed_duration_minutes, notes)
        return {
            "ticket": result.ticket.model_dump(mode="json"),
            "extracted_attributes": result.extracted_attributes.model_dump(mode="json") if result.extracted_attributes else None
        }

    def finalize_close_out(self, ticket_id: str, confirmed_attributes: dict,
                          next_service: str, reach_out_months: int | None = None) -> dict:
        """Finalize close-out after technician confirms. Marks ticket as completed (immutable)."""
        from core.services.ticket_service import NextServiceAction
        ticket = self.ticket_service.finalize_close_out(
            UUID(ticket_id), confirmed_attributes, NextServiceAction(next_service), reach_out_months
        )
        return ticket.model_dump(mode="json")

    def cancel(self, ticket_id: str, reason: str | None = None) -> dict:
        return self.ticket_service.cancel(UUID(ticket_id), reason).model_dump(mode="json")

    # Additional methods: add_line_item (same pattern as create)
```

---

## 4.4 Request ID Middleware

**Purpose**: Generate and propagate request IDs for tracing.

### Implementation

```python
# api/middleware.py

from uuid import uuid4
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Add request ID to every request for tracing.

    - Generates UUID for each request
    - Stores in request.state for access in handlers
    - Adds X-Request-ID header to response
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check for existing request ID (from load balancer, etc.)
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid4())

        # Store in request state
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers["X-Request-ID"] = request_id

        return response
```

---

## 4.5 Error Handling

**Purpose**: Global exception handler for consistent error responses.

### Implementation

```python
# api/errors.py

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.base import error_response, ErrorCodes


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPExceptions."""
    request_id = getattr(request.state, "request_id", None)

    # Map status codes to error codes
    code_map = {
        400: ErrorCodes.INVALID_REQUEST,
        401: ErrorCodes.NOT_AUTHENTICATED,
        403: ErrorCodes.NOT_AUTHENTICATED,
        404: ErrorCodes.NOT_FOUND,
        429: ErrorCodes.RATE_LIMITED,
        500: ErrorCodes.INTERNAL_ERROR,
        503: ErrorCodes.SERVICE_UNAVAILABLE,
    }

    error_code = code_map.get(exc.status_code, ErrorCodes.INTERNAL_ERROR)

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            error_code,
            exc.detail,
            request_id=request_id
        ).model_dump(mode="json")
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    request_id = getattr(request.state, "request_id", None)

    # Format validation errors nicely
    errors = []
    for error in exc.errors():
        loc = " -> ".join(str(l) for l in error["loc"])
        errors.append(f"{loc}: {error['msg']}")

    return JSONResponse(
        status_code=422,
        content=error_response(
            ErrorCodes.VALIDATION_ERROR,
            "; ".join(errors),
            request_id=request_id
        ).model_dump(mode="json")
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = getattr(request.state, "request_id", None)

    # Log the actual error
    import traceback
    traceback.print_exc()

    return JSONResponse(
        status_code=500,
        content=error_response(
            ErrorCodes.INTERNAL_ERROR,
            "An unexpected error occurred",
            request_id=request_id
        ).model_dump(mode="json")
    )
```

---

## API Response Examples

All responses follow the same envelope structure:

```json
{
  "success": true,              // false for errors
  "data": { ... },              // null for errors; varies by endpoint (see below)
  "error": null,                // {code, message} for errors
  "meta": {
    "timestamp": "2024-01-15T14:30:00Z",
    "request_id": "req-789"
  }
}
```

**Data field variations:**
- **List**: `{items: [...], next_cursor: "...", has_more: bool}`
- **Single entity**: The entity object directly (may include nested `addresses`, etc.)
- **Action result**: Varies by action (e.g., `{ticket: {...}}` for clock_in)
- **Error**: `data` is null; `error` contains `{code: "NOT_FOUND", message: "..."}`

---

## Phase 4 Verification Checklist

Before proceeding to Phase 5:

### API Tests

- [ ] `GET /health` returns infrastructure status
- [ ] `GET /health/ready` returns ready status
- [ ] `GET /health/live` always returns OK

### Data Endpoint Tests

- [ ] `GET /api/data?type=contacts` returns paginated list
- [ ] `GET /api/data?type=contacts&id=xxx` returns single contact
- [ ] `GET /api/data?type=contacts&search=xxx` searches correctly
- [ ] `GET /api/data?type=contacts&cursor=xxx` paginates correctly
- [ ] Invalid type returns proper error

### Action Endpoint Tests

- [ ] `POST /api/actions` with valid contact.create works
- [ ] `POST /api/actions` with valid ticket.clock_in works
- [ ] `POST /api/actions` with invalid domain returns error
- [ ] `POST /api/actions` with invalid action returns error
- [ ] Validation errors return proper format

### Middleware Tests

- [ ] All responses have X-Request-ID header
- [ ] Request ID propagates to error responses
- [ ] Auth middleware blocks unauthenticated requests
- [ ] Auth middleware allows public endpoints

### Response Format

- [ ] All responses match `{success, data, error, meta}` structure
- [ ] Errors always include code and message
- [ ] Meta always includes timestamp and request_id

---

## Next Phase

Proceed to [Phase 5: Application Assembly](./PHASE_5_ASSEMBLY.md)
