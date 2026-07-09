"""Propagate authenticated workspace identity and timezone through a request."""

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_current_workspace_id: ContextVar[UUID | None] = ContextVar(
    "current_workspace_id", default=None
)
_current_workspace_timezone: ContextVar[str | None] = ContextVar(
    "current_workspace_timezone", default=None
)


def get_current_workspace_id() -> UUID:
    """Return the authenticated workspace ID or fail before unscoped work."""
    workspace_id = _current_workspace_id.get()
    if workspace_id is None:
        raise RuntimeError("No workspace context set for tenant-scoped operation")
    return workspace_id


def get_current_workspace_timezone() -> str:
    """Return the authenticated request timezone or fail before local-date work."""
    timezone = _current_workspace_timezone.get()
    if timezone is None:
        raise RuntimeError("No workspace timezone set for tenant-scoped operation")
    return timezone


def set_current_workspace_id(workspace_id: UUID) -> None:
    """Set workspace identity after internal-request authentication."""
    _current_workspace_id.set(workspace_id)


def set_current_workspace_timezone(timezone: str) -> None:
    """Set the validated IANA timezone for the current request."""
    _current_workspace_timezone.set(timezone)


def clear_workspace_context() -> None:
    """Clear request state so pooled execution cannot retain a prior workspace."""
    _current_workspace_id.set(None)
    _current_workspace_timezone.set(None)


@contextmanager
def workspace_context(workspace_id: UUID, timezone: str = "UTC"):
    """Temporarily set workspace context for tests and administrative jobs."""
    prior_workspace_id = _current_workspace_id.get()
    prior_timezone = _current_workspace_timezone.get()
    set_current_workspace_id(workspace_id)
    set_current_workspace_timezone(timezone)
    try:
        yield
    finally:
        _current_workspace_id.set(prior_workspace_id)
        _current_workspace_timezone.set(prior_timezone)
