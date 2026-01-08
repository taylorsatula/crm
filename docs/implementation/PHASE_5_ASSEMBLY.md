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
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Infrastructure clients
from clients.vault_client import VaultClient
from clients.postgres_client import PostgresClient
from clients.valkey_client import ValkeyClient
from clients.llm_client import LLMClient

# Auth components
from auth.config import AuthConfig, load_auth_config
from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger
from auth.email_service import AuthEmailService
from auth.service import AuthService
from auth.security_middleware import AuthMiddleware
from auth.api import router as auth_router

# Core components
from core.audit import AuditLogger
from core.extraction import AttributeExtractor
from core.services.contact_service import ContactService
from core.services.address_service import AddressService
from core.services.catalog_service import CatalogService
from core.services.ticket_service import TicketService
from core.services.invoice_service import InvoiceService
from core.services.note_service import NoteService
from core.services.attribute_service import AttributeService
from core.services.message_service import MessageService

# API components
from api.middleware import RequestIDMiddleware
from api.errors import http_exception_handler, validation_exception_handler, general_exception_handler
from api.health import create_health_router
from api.data import create_data_router, create_ticket_data_routes
from api.actions import (
    create_actions_router,
    ContactActionHandler,
    TicketActionHandler
)


# Global references for dependency injection
# These are set during lifespan and used by route dependencies
vault: VaultClient = None
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
    global vault, postgres, valkey, auth_config, auth_service

    # ===== STARTUP =====

    # 1. Initialize infrastructure clients
    print("Initializing Vault client...")
    vault = VaultClient()

    print("Initializing PostgreSQL client...")
    postgres = PostgresClient(vault.get_database_url())

    print("Initializing Valkey client...")
    valkey = ValkeyClient(vault.get_valkey_url())

    print("Initializing LLM client...")
    llm_config = vault.get_secret("crm/llm")
    llm = LLMClient(
        local_endpoint=llm_config.get("local_endpoint"),
        remote_provider=llm_config.get("remote_provider"),
        remote_api_key=llm_config.get("remote_api_key"),
        prefer_local=llm_config.get("prefer_local", True)
    )

    # 2. Initialize auth components
    print("Initializing auth system...")
    auth_config = load_auth_config()

    email_creds = vault.get_secret("crm/email")
    auth_email = AuthEmailService(
        config=auth_config,
        smtp_host=email_creds["smtp_host"],
        smtp_port=int(email_creds["smtp_port"]),
        smtp_user=email_creds["smtp_user"],
        smtp_password=email_creds["smtp_password"],
        from_address=email_creds["from_address"]
    )

    auth_db = AuthDatabase(postgres)
    session_manager = SessionManager(valkey, auth_config)
    rate_limiter = RateLimiter(valkey, auth_config)
    security_logger = SecurityLogger(postgres)

    auth_service = AuthService(
        database=auth_db,
        session_manager=session_manager,
        rate_limiter=rate_limiter,
        email_service=auth_email,
        security_logger=security_logger,
        config=auth_config
    )

    # 3. Initialize core services
    print("Initializing core services...")
    audit = AuditLogger(postgres)
    extractor = AttributeExtractor(llm)

    contact_service = ContactService(postgres, audit)
    address_service = AddressService(postgres, audit)
    catalog_service = CatalogService(postgres, audit)
    ticket_service = TicketService(postgres, audit, extractor)
    invoice_service = InvoiceService(postgres, audit)
    note_service = NoteService(postgres, audit)
    attribute_service = AttributeService(postgres, audit)
    message_service = MessageService(postgres, audit)

    # 4. Create routers with dependencies
    print("Creating API routers...")

    # Health router
    health_router = create_health_router(postgres, valkey, vault)
    app.include_router(health_router)

    # Data router
    data_services = {
        "contacts": contact_service,
        "addresses": address_service,
        "services": catalog_service,
        "tickets": ticket_service,
        "invoices": invoice_service,
        "notes": note_service,
        "attributes": attribute_service,
        "messages": message_service,
    }
    data_router = create_data_router(data_services)
    app.include_router(data_router)

    # Ticket-specific data routes
    ticket_data_router = create_ticket_data_routes(ticket_service)
    app.include_router(ticket_data_router)

    # Actions router
    action_handlers = {
        "contact": ContactActionHandler(contact_service, address_service),
        "ticket": TicketActionHandler(ticket_service, None),
        # Add more handlers as implemented
    }
    actions_router = create_actions_router(action_handlers)
    app.include_router(actions_router)

    # Store services in app state for access elsewhere
    app.state.services = data_services
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
# Auth middleware added after routers are created in lifespan

# Exception handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Auth routes (public, before auth middleware check)
app.include_router(auth_router)

# Static files and templates (for frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Add auth middleware after app creation
@app.middleware("http")
async def auth_middleware(request, call_next):
    """
    Authentication middleware.

    Checks session cookie for protected routes.
    """
    from auth.security_middleware import AuthMiddleware

    # Skip for public paths
    public_paths = ["/auth/", "/health", "/static/", "/docs", "/openapi.json"]
    if any(request.url.path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Check session
    from auth.exceptions import SessionExpiredError
    from utils.user_context import set_current_user_id, clear_current_user_id

    token = request.cookies.get("session_token")
    if not token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        session_manager = app.state.session_manager
        session = session_manager.validate_session(token)
        set_current_user_id(session.user_id)
        request.state.user_id = session.user_id
        request.state.session = session
    except SessionExpiredError:
        raise HTTPException(status_code=401, detail="Session expired")

    try:
        response = await call_next(request)
        return response
    finally:
        clear_current_user_id()


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
│   ├── health.py, data.py, actions.py
│   ├── middleware.py, errors.py
├── auth/                       # Magic link auth system
│   ├── types.py, exceptions.py, config.py
│   ├── database.py, rate_limiter.py, security_logger.py
│   ├── session.py, email_service.py, service.py
│   └── security_middleware.py, api.py
├── clients/                    # External service clients
│   ├── vault_client.py         # Secrets management
│   ├── postgres_client.py      # PostgreSQL with RLS
│   ├── valkey_client.py, llm_client.py
├── core/
│   ├── audit.py, extraction.py
│   ├── models/                 # Pydantic models per entity
│   └── services/               # Business logic per entity
├── utils/
│   ├── timezone.py, user_context.py, pagination.py
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
