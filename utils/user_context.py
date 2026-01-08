"""Propagate user identity through the call stack using contextvars."""

from contextvars import ContextVar
from uuid import UUID
from contextlib import contextmanager

_current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> UUID:
    """
    Get current user ID from context.

    Raises RuntimeError if no user context is set.
    This is fail-fast behavior - if you're in a code path that
    requires user context and it's not set, that's a bug.
    """
    user_id = _current_user_id.get()
    if user_id is None:
        raise RuntimeError(
            "No user context set. This usually means you're calling "
            "user-scoped code outside of an authenticated request."
        )
    return user_id


def set_current_user_id(user_id: UUID) -> None:
    """
    Set current user ID in context.

    Called by auth middleware after validating session.
    """
    _current_user_id.set(user_id)


def clear_current_user_id() -> None:
    """
    Clear user context.

    Called by auth middleware after request completes.
    Must be called in finally block to prevent context leakage.
    """
    _current_user_id.set(None)


@contextmanager
def user_context(user_id: UUID):
    """
    Context manager for temporarily setting user context.

    Useful for:
    - Tests
    - Background jobs that iterate over users
    - Admin operations on behalf of a user

    Example:
        with user_context(some_user_id):
            # All operations here use some_user_id for RLS
            contacts = contact_service.list()
    """
    previous = _current_user_id.get()
    set_current_user_id(user_id)
    try:
        yield
    finally:
        if previous is None:
            clear_current_user_id()
        else:
            set_current_user_id(previous)
