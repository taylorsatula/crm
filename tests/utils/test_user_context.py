"""Tests for utils/user_context.py - User identity propagation via contextvars."""

from uuid import uuid4

import pytest

from utils.user_context import (
    get_current_user_id,
    set_current_user_id,
    clear_current_user_id,
    user_context,
)


class TestGetCurrentUserId:
    """Tests for get_current_user_id()."""

    def test_raises_without_set(self):
        """Must raise RuntimeError when no context is set."""
        clear_current_user_id()  # Ensure clean state
        with pytest.raises(RuntimeError, match="No user context"):
            get_current_user_id()


class TestSetAndClear:
    """Tests for set_current_user_id() and clear_current_user_id()."""

    def test_set_then_get_returns_uuid(self):
        """Setting then getting should return the same UUID."""
        user_id = uuid4()
        set_current_user_id(user_id)
        assert get_current_user_id() == user_id
        clear_current_user_id()

    def test_clear_then_get_raises(self):
        """Clearing then getting should raise RuntimeError."""
        set_current_user_id(uuid4())
        clear_current_user_id()
        with pytest.raises(RuntimeError):
            get_current_user_id()


class TestUserContextManager:
    """Tests for user_context() context manager."""

    def test_sets_and_clears(self):
        """Context manager should set inside, clear after."""
        clear_current_user_id()  # Ensure clean state
        user_id = uuid4()

        with user_context(user_id):
            assert get_current_user_id() == user_id

        with pytest.raises(RuntimeError):
            get_current_user_id()

    def test_restores_previous(self):
        """Nested context managers should restore outer context."""
        outer_id = uuid4()
        inner_id = uuid4()

        with user_context(outer_id):
            assert get_current_user_id() == outer_id

            with user_context(inner_id):
                assert get_current_user_id() == inner_id

            assert get_current_user_id() == outer_id

    def test_clears_on_exception(self):
        """Context should be cleared even if exception is raised."""
        clear_current_user_id()
        user_id = uuid4()

        with pytest.raises(ValueError):
            with user_context(user_id):
                assert get_current_user_id() == user_id
                raise ValueError("test exception")

        with pytest.raises(RuntimeError):
            get_current_user_id()
