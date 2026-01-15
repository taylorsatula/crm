"""Tests for universal audit trail."""

import pytest
from uuid import uuid4


class TestAuditAction:
    """Tests for AuditAction enum."""

    def test_has_create_update_delete(self):
        """AuditAction has required values."""
        from core.audit import AuditAction

        assert AuditAction.CREATE.value == "create"
        assert AuditAction.UPDATE.value == "update"
        assert AuditAction.DELETE.value == "delete"


class TestComputeChanges:
    """Tests for compute_changes utility function."""

    def test_detects_changed_fields(self):
        """Different values for same key detected."""
        from core.audit import compute_changes

        old = {"name": "Alice", "email": "alice@test.com"}
        new = {"name": "Alice", "email": "alice@new.com"}

        changes = compute_changes(old, new)

        assert "email" in changes
        assert changes["email"]["old"] == "alice@test.com"
        assert changes["email"]["new"] == "alice@new.com"
        assert "name" not in changes  # Unchanged

    def test_detects_added_fields(self):
        """New fields in 'new' dict detected."""
        from core.audit import compute_changes

        old = {"name": "Alice"}
        new = {"name": "Alice", "phone": "555-1234"}

        changes = compute_changes(old, new)

        assert "phone" in changes
        assert changes["phone"]["old"] is None
        assert changes["phone"]["new"] == "555-1234"

    def test_detects_removed_fields(self):
        """Fields in 'old' but not 'new' detected."""
        from core.audit import compute_changes

        old = {"name": "Alice", "phone": "555-1234"}
        new = {"name": "Alice"}

        changes = compute_changes(old, new)

        assert "phone" in changes
        assert changes["phone"]["old"] == "555-1234"
        assert changes["phone"]["new"] is None

    def test_excludes_updated_at_by_default(self):
        """updated_at not reported as change."""
        from core.audit import compute_changes
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        old = {"name": "Alice", "updated_at": now}
        new = {"name": "Alice", "updated_at": datetime.now(timezone.utc)}

        changes = compute_changes(old, new)

        assert "updated_at" not in changes

    def test_custom_exclude_fields(self):
        """Can exclude additional fields."""
        from core.audit import compute_changes

        old = {"name": "Alice", "internal_id": 1}
        new = {"name": "Bob", "internal_id": 2}

        changes = compute_changes(old, new, exclude_fields={"updated_at", "internal_id"})

        assert "name" in changes
        assert "internal_id" not in changes

    def test_empty_when_no_changes(self):
        """Returns empty dict when values identical."""
        from core.audit import compute_changes

        old = {"name": "Alice", "email": "alice@test.com"}
        new = {"name": "Alice", "email": "alice@test.com"}

        changes = compute_changes(old, new)

        assert changes == {}


class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_log_change_creates_entry(self, db, as_test_user):
        """Create audit entry for entity change."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)
        entity_id = uuid4()

        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.CREATE,
            changes={"created": {"name": "Test Customer"}}
        )

        # Verify entry exists (audit_log has no RLS)
        entries = db.execute(
            "SELECT * FROM audit_log WHERE entity_id = %s",
            (entity_id,)
        )
        assert len(entries) == 1
        assert entries[0]["entity_type"] == "customer"
        assert entries[0]["action"] == "create"

    def test_log_change_uses_context_user(self, db, as_test_user, test_user_id):
        """Defaults to current user context."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)
        entity_id = uuid4()

        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.CREATE,
            changes={"created": {}}
        )

        entries = db.execute(
            "SELECT user_id FROM audit_log WHERE entity_id = %s",
            (entity_id,)
        )
        assert entries[0]["user_id"] == test_user_id

    def test_log_change_explicit_user_overrides(self, db, as_test_user, test_user_b_id):
        """Explicit user_id overrides context."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)
        entity_id = uuid4()

        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.UPDATE,
            changes={"name": {"old": "A", "new": "B"}},
            user_id=test_user_b_id
        )

        entries = db.execute(
            "SELECT user_id FROM audit_log WHERE entity_id = %s",
            (entity_id,)
        )
        assert entries[0]["user_id"] == test_user_b_id

    def test_log_change_stores_changes_as_json(self, db, as_test_user):
        """Changes stored as JSONB."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)
        entity_id = uuid4()
        changes_data = {
            "name": {"old": "Alice", "new": "Bob"},
            "email": {"old": None, "new": "bob@test.com"}
        }

        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.UPDATE,
            changes=changes_data
        )

        entries = db.execute(
            "SELECT changes FROM audit_log WHERE entity_id = %s",
            (entity_id,)
        )
        # JSONB comes back as dict
        assert entries[0]["changes"] == changes_data

    def test_get_entity_history_returns_ordered(self, db, as_test_user):
        """History returned newest-first."""
        from core.audit import AuditLogger, AuditAction
        import time

        logger = AuditLogger(db)
        entity_id = uuid4()

        # Create multiple entries
        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.CREATE,
            changes={"created": {"name": "V1"}}
        )
        time.sleep(0.01)  # Ensure different timestamps
        logger.log_change(
            entity_type="customer",
            entity_id=entity_id,
            action=AuditAction.UPDATE,
            changes={"name": {"old": "V1", "new": "V2"}}
        )

        history = logger.get_entity_history("customer", entity_id)

        assert len(history) == 2
        # Newest first
        assert history[0]["action"] == "update"
        assert history[1]["action"] == "create"

    def test_get_entity_history_filters_by_entity(self, db, as_test_user):
        """History only for requested entity."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)
        entity_a = uuid4()
        entity_b = uuid4()

        logger.log_change("customer", entity_a, AuditAction.CREATE, {"created": {}})
        logger.log_change("customer", entity_b, AuditAction.CREATE, {"created": {}})

        history_a = logger.get_entity_history("customer", entity_a)
        history_b = logger.get_entity_history("customer", entity_b)

        assert len(history_a) == 1
        assert len(history_b) == 1
        assert history_a[0]["entity_id"] == entity_a
        assert history_b[0]["entity_id"] == entity_b

    def test_get_user_activity_respects_limit(self, db, as_test_user):
        """Activity limited to specified count."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)

        # Create 5 entries
        for i in range(5):
            logger.log_change(
                entity_type="customer",
                entity_id=uuid4(),
                action=AuditAction.CREATE,
                changes={"created": {"index": i}}
            )

        activity = logger.get_user_activity(limit=3)

        assert len(activity) == 3

    def test_get_user_activity_filters_by_user(self, db, as_test_user, as_test_user_b, test_user_id, test_user_b_id):
        """Activity only for requested user."""
        from core.audit import AuditLogger, AuditAction

        logger = AuditLogger(db)

        # User A creates entry
        logger.log_change(
            entity_type="customer",
            entity_id=uuid4(),
            action=AuditAction.CREATE,
            changes={"created": {}},
            user_id=test_user_id
        )

        # User B creates entry
        logger.log_change(
            entity_type="customer",
            entity_id=uuid4(),
            action=AuditAction.CREATE,
            changes={"created": {}},
            user_id=test_user_b_id
        )

        activity_a = logger.get_user_activity(user_id=test_user_id)
        activity_b = logger.get_user_activity(user_id=test_user_b_id)

        assert len(activity_a) == 1
        assert len(activity_b) == 1
        assert activity_a[0]["user_id"] == test_user_id
        assert activity_b[0]["user_id"] == test_user_b_id
