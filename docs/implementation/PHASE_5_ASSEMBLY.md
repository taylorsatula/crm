# Phase 5: Application Assembly

**Goal**: Wire everything together into a runnable application.

**Estimated files**: 2-3
**Dependencies**: Phases 0-4 complete

---

## Prerequisites

Before starting Phase 5, ensure:

1. All previous phases complete and verified
2. All tests passing
3. Database schema applied
4. External services running (Vault, PostgreSQL, Valkey)

---

## 5.1 main.py

**Purpose**: Application entry point and dependency wiring.

### Implementation

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Infrastructure clients
from clients.vault_client import get_database_url, get_valkey_url, get_email_config, get_llm_config
from clients.postgres_client import PostgresClient
from clients.valkey_client import ValkeyClient
from clients.email_client import EmailGatewayClient
from clients.llm_client import LLMClient

# Auth components
from auth.config import AuthConfig
from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger
from auth.service import AuthService
from auth.security_middleware import AuthMiddleware
from auth.api import create_auth_router

# Core components
from core.audit import AuditLogger
from core.event_bus import EventBus
from core.extraction import AttributeExtractor
from core.services.customer_service import CustomerService
from core.services.address_service import AddressService
from core.services.catalog_service import CatalogService
from core.services.ticket_service import TicketService
from core.services.line_item_service import LineItemService
from core.services.invoice_service import InvoiceService
from core.services.note_service import NoteService
from core.services.attribute_service import AttributeService
from core.services.message_service import MessageService

# Event handlers
from core.handlers.ticket_completion_handler import handle_ticket_completed
from core.handlers.ticket_cancellation_handler import handle_ticket_cancelled
from core.handlers.invoice_payment_handler import handle_invoice_paid

# API components
from api.middleware import RequestIDMiddleware
from api.errors import register_error_handlers
from api.data import create_data_router
from api.actions import create_actions_router


# Global references for dependency injection
# These are set during lifespan and used by route dependencies
postgres: PostgresClient = None
valkey: ValkeyClient = None
auth_config: AuthConfig = None
auth_service: AuthService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup (initializing clients) and shutdown (cleanup).
    """
    global postgres, valkey, auth_config, auth_service

    # ===== STARTUP =====

    # 1. Initialize infrastructure clients
    print("Initializing PostgreSQL client...")
    postgres = PostgresClient(get_database_url())

    print("Initializing Valkey client...")
    valkey = ValkeyClient(get_valkey_url())

    print("Initializing LLM client...")
    llm_config = get_llm_config()
    llm = LLMClient(api_key=llm_config["api_key"])

    # 2. Initialize auth components
    print("Initializing auth system...")
    auth_config = AuthConfig()

    email_creds = get_email_config()
    email_client = EmailGatewayClient(
        gateway_url=email_creds["gateway_url"],
        api_key=email_creds["api_key"],
        hmac_secret=email_creds["hmac_secret"],
    )

    auth_db = AuthDatabase(postgres)
    session_manager = SessionManager(valkey, auth_config)
    rate_limiter = RateLimiter(valkey, auth_config)
    security_logger = SecurityLogger(postgres)

    auth_service = AuthService(
        config=auth_config,
        auth_db=auth_db,
        session_manager=session_manager,
        rate_limiter=rate_limiter,
        email_client=email_client,
        security_logger=security_logger,
    )

    # 3. Initialize core services
    print("Initializing core services...")
    audit = AuditLogger(postgres)
    event_bus = EventBus()
    extractor = AttributeExtractor(llm)

    customer_service = CustomerService(postgres, audit, event_bus)
    address_service = AddressService(postgres, audit)
    catalog_service = CatalogService(postgres, audit)
    ticket_service = TicketService(postgres, audit, event_bus)
    line_item_service = LineItemService(postgres, audit)
    invoice_service = InvoiceService(postgres, audit, event_bus)
    note_service = NoteService(postgres, audit, event_bus)
    attribute_service = AttributeService(postgres, audit)
    message_service = MessageService(postgres, audit)

    # 3b. Wire event handlers
    event_bus.subscribe("TicketCompleted", handle_ticket_completed(extractor, attribute_service, note_service))
    event_bus.subscribe("TicketCancelled", handle_ticket_cancelled(message_service))
    event_bus.subscribe("InvoicePaid", handle_invoice_paid(message_service))

    # 4. Create routers with dependencies
    print("Creating API routers...")

    services = {
        "customer": customer_service,
        "address": address_service,
        "catalog": catalog_service,
        "ticket": ticket_service,
        "line_item": line_item_service,
        "invoice": invoice_service,
        "note": note_service,
        "attribute": attribute_service,
        "message": message_service,
    }

    data_router = create_data_router(services)
    app.include_router(data_router)

    actions_router = create_actions_router(services)
    app.include_router(actions_router)

    # Auth router
    auth_router = create_auth_router(auth_service)
    app.include_router(auth_router)

    # Auth middleware (needs session_manager, so wired here)
    app.add_middleware(AuthMiddleware, session_manager=session_manager)

    # Store references in app state
    app.state.services = services
    app.state.auth_service = auth_service
    app.state.session_manager = session_manager

    print("Application startup complete!")

    yield

    # ===== SHUTDOWN =====
    print("Shutting down...")
    postgres.close()
    valkey.close()
    print("Shutdown complete.")


# Create FastAPI app
app = FastAPI(
    title="CRM API",
    description="CRM and appointment scheduling for service businesses",
    version="0.1.0",
    lifespan=lifespan
)

# Add middleware (order matters - first added is outermost)
app.add_middleware(RequestIDMiddleware)

# Exception handlers
register_error_handlers(app)

# Static files and templates (for frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 5.2 config.py

**Purpose**: Application configuration management.

### Implementation

```python
from pydantic import BaseModel, Field
import os


class AppConfig(BaseModel):
    """Application configuration."""

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)

    # Database
    db_pool_size: int = Field(default=10)

    # Logging
    log_level: str = Field(default="INFO")

    # Feature flags
    enable_llm_extraction: bool = Field(default=True)


def load_app_config() -> AppConfig:
    """Load configuration from environment variables."""
    return AppConfig(
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8000")),
        debug=os.getenv("APP_DEBUG", "false").lower() == "true",
        db_pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enable_llm_extraction=os.getenv("ENABLE_LLM_EXTRACTION", "true").lower() == "true",
    )
```

---

## 5.3 Running the Application

### Development

```bash
# Ensure environment variables are set
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=your-token

# Run with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
# With Gunicorn + Uvicorn workers
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 5.4 Directory Structure Verification

After all phases, verify the complete structure:

```
crm/
├── main.py                     # Entry point
├── config.py
├── requirements.txt
├── api/
│   ├── base.py                 # Response format, error codes
│   ├── data.py, actions.py
│   ├── middleware.py, errors.py
├── auth/                       # Magic link auth system
│   ├── types.py, exceptions.py, config.py
│   ├── database.py, rate_limiter.py, security_logger.py
│   ├── session.py, service.py
│   └── security_middleware.py, api.py
├── clients/                    # External service clients
│   ├── vault_client.py         # Secrets management
│   ├── postgres_client.py      # PostgreSQL with RLS
│   ├── valkey_client.py, llm_client.py, email_client.py
├── core/
│   ├── audit.py, extraction.py
│   ├── event_bus.py            # Sync in-process event bus
│   ├── events.py               # Frozen dataclass domain events
│   ├── handlers/               # Event handler factories
│   │   ├── ticket_completion_handler.py
│   │   ├── ticket_cancellation_handler.py
│   │   └── invoice_payment_handler.py
│   ├── models/                 # Pydantic models per entity
│   └── services/               # Business logic per entity
├── utils/
│   ├── timezone.py, user_context.py
├── templates/                  # Jinja2 (auth/, calendar/, contacts/, tickets/)
├── static/                     # CSS, JS
├── tests/                      # Test suite (test_*.py)
└── docs/                       # ADR, waterfall, phase docs
```

---

## Phase 5 Verification Checklist

### Application Startup

- [ ] `uvicorn main:app` starts without errors
- [ ] All health checks pass (`GET /health`)
- [ ] No missing dependency errors

### End-to-End Flow

- [ ] Request magic link → receive email → verify → session created
- [ ] Create contact → add address → create ticket
- [ ] Clock in → perform work → clock out
- [ ] Close out with notes → see extracted attributes → confirm
- [ ] Ticket marked completed, cannot be modified

### API Verification

- [ ] All endpoints return consistent response format
- [ ] Authentication required for protected routes
- [ ] Rate limiting works
- [ ] Audit trail captures all changes

### Performance

- [ ] Health check responds in <100ms
- [ ] List endpoints respond in <500ms
- [ ] No N+1 query patterns visible in logs

---

## Post-Implementation

With all phases complete, the system is ready for:

1. **Frontend Development**: Build templates and JavaScript
2. **Integration Testing**: End-to-end test suite
3. **Load Testing**: Verify performance under load
4. **Security Audit**: Review for vulnerabilities
5. **Deployment**: Production infrastructure setup

---

## Next Steps

1. Build frontend templates (start with auth flow, then calendar)
2. Add remaining services not yet implemented
3. Write comprehensive test suite
4. Set up CI/CD pipeline
5. Deploy to staging environment
