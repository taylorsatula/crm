"""
Lead service for CRM quoting pipeline.

Owns the lead entity: create, read, update, transition status, and conversion
to a customer. All operations scoped to the current workspace via RLS.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.event_bus import EventBus
from core.exceptions import NotFoundError
from core.models import Lead, LeadCreate, LeadUpdate, LeadStatus

from utils.workspace_context import get_current_workspace_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

# Columns that can appear in a lead update (besides status transitions)
_UPDATABLE_COLUMNS = {
    "raw_notes", "name", "phone", "email", "address",
    "service_interest", "lead_source", "urgency", "property_details",
    "reminder_at", "reminder_note",
}

# Valid lead status transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"contacted", "archived"},
    "contacted": {"qualified", "archived"},
    "qualified": {"converted", "archived"},
    "converted": set(),
    "archived": set(),
}


@dataclass(frozen=True)
class LeadPage:
    leads: list[Lead]
    next_cursor: str | None


class LeadService:
    """Service for lead operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger, event_bus: EventBus):
        self.postgres = postgres
        self.audit = audit
        self.event_bus = event_bus

    def create(self, data: LeadCreate) -> Lead:
        """Create a new lead in 'new' status."""
        workspace_id = get_current_workspace_id()
        lead_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO leads (
                id, workspace_id, status, raw_notes, name, phone, email, address,
                service_interest, lead_source, urgency, property_details,
                reminder_at, reminder_note,
                created_at, updated_at
            ) VALUES (
                %s, %s, 'new', %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                lead_id, workspace_id, data.raw_notes,
                data.name, data.phone, data.email, data.address,
                data.service_interest, data.lead_source, data.urgency,
                data.property_details,
                data.reminder_at, data.reminder_note,
                now, now,
            ),
        )[0]

        lead = Lead.model_validate(row)
        self.audit.log_change(
            entity_type="lead",
            entity_id=lead.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)},
        )
        return lead

    def get_by_id(self, lead_id: UUID) -> Lead | None:
        """Fetch one lead by id, scoped by RLS and not deleted."""
        row = self.postgres.execute_single(
            "SELECT * FROM leads WHERE id = %s AND deleted_at IS NULL",
            (lead_id,),
        )
        if row is None:
            return None
        return Lead.model_validate(row)

    def update(self, lead_id: UUID, data: LeadUpdate) -> Lead:
        """
        Update lead fields. If status is included, validate the transition.
        """
        current = self.get_by_id(lead_id)
        if current is None:
            raise NotFoundError(f"Lead {lead_id} not found")

        if current.status == LeadStatus.CONVERTED:
            raise ValueError(f"Lead {lead_id} is already converted and cannot be modified")
        if current.status == LeadStatus.ARCHIVED:
            raise ValueError(f"Lead {lead_id} is archived and cannot be modified")

        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current

        # Handle status transition separately
        if "status" in updates:
            target = updates.pop("status")
            if isinstance(target, str):
                target_str = target
            else:
                target_str = target.value
            self._transition(current, target_str)
            current = self.get_by_id(current.id)
            if not updates:
                return current

        # Filter to valid columns only
        valid = {k: v for k, v in updates.items() if k in _UPDATABLE_COLUMNS}
        for k in updates:
            if k not in _UPDATABLE_COLUMNS:
                logger.warning(f"Attempted to update unknown lead field '{k}' on lead {lead_id}")

        if not valid:
            return current

        set_parts = []
        params: list = []
        for field, value in valid.items():
            # Convert enum to raw string for DB
            if hasattr(value, "value"):
                value = value.value
            set_parts.append(f"{field} = %s")
            params.append(value)

        set_parts.append("updated_at = %s")
        params.append(now_utc())
        params.append(lead_id)

        row = self.postgres.execute_returning(
            f"UPDATE leads SET {', '.join(set_parts)} WHERE id = %s AND deleted_at IS NULL RETURNING *",
            tuple(params),
        )[0]

        updated = Lead.model_validate(row)
        changes = compute_changes(current.model_dump(mode="json"), updated.model_dump(mode="json"))
        if changes:
            self.audit.log_change(
                entity_type="lead",
                entity_id=lead_id,
                action=AuditAction.UPDATE,
                changes=changes,
            )
        return updated

    def transition(self, lead_id: UUID, target_status: str) -> Lead:
        """
        Explicit status transition. Validates the transition is legal.
        Returns the updated lead.
        """
        current = self.get_by_id(lead_id)
        if current is None:
            raise NotFoundError(f"Lead {lead_id} not found")
        self._transition(current, target_status)
        return self.get_by_id(lead_id)

    def _transition(self, lead: Lead, target_status: str) -> None:
        """Validate and execute a status transition on a lead row (SQL-level)."""
        current_str = lead.status.value if hasattr(lead.status, "value") else lead.status
        allowed = _VALID_TRANSITIONS.get(current_str, set())
        if target_status not in allowed:
            raise ValueError(
                f"Invalid lead transition '{current_str}' → '{target_status}'. "
                f"Allowed: {', '.join(sorted(allowed)) or '(none)'}"
            )

        now = now_utc()
        extra_sets = ""
        params: list = []

        if target_status == "converted":
            # Conversion requires customer creation — done via a separate flow.
            # Here we only record the transition timestamps. The caller must
            # supply converted_customer_id via update() after customer creation.
            raise ValueError(
                "Use convert_lead() to transition to 'converted' — it creates "
                "the customer record atomically."
            )
        elif target_status == "archived":
            extra_sets = ""  # archived is terminal, no extra fields needed

        params.append(target_status)
        params.append(now)
        params.append(lead.id)

        self.postgres.execute_returning(
            f"UPDATE leads SET status = %s, updated_at = %s {extra_sets} WHERE id = %s RETURNING id",
            tuple(params),
        )

        self.audit.log_change(
            entity_type="lead",
            entity_id=lead.id,
            action=AuditAction.UPDATE,
            changes={"status": {"from": current_str, "to": target_status}},
        )

    def convert_lead(self, lead_id: UUID, customer_id: UUID) -> Lead:
        """
        Transition a qualified lead to 'converted', stamp converted_at and
        converted_customer_id. Caller has already created the customer.
        """
        current = self.get_by_id(lead_id)
        if current is None:
            raise NotFoundError(f"Lead {lead_id} not found")
        if current.status == LeadStatus.CONVERTED:
            raise ValueError(f"Lead {lead_id} is already converted")
        if current.status == LeadStatus.ARCHIVED:
            raise ValueError(f"Lead {lead_id} is archived and cannot be converted")
        if current.status != LeadStatus.QUALIFIED:
            raise ValueError(
                f"Lead {lead_id} must be 'qualified' before conversion; "
                f"current status is '{current.status.value}'"
            )

        now = now_utc()
        self.postgres.execute_returning(
            """
            UPDATE leads
            SET status = 'converted', converted_at = %s, converted_customer_id = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now, customer_id, now, lead_id),
        )

        self.audit.log_change(
            entity_type="lead",
            entity_id=lead_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"from": "qualified", "to": "converted"},
                "converted_at": str(now),
                "converted_customer_id": str(customer_id),
            },
        )
        return self.get_by_id(lead_id)

    def delete(self, lead_id: UUID) -> bool:
        """Soft delete a lead."""
        current = self.get_by_id(lead_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE leads SET deleted_at = %s, updated_at = %s WHERE id = %s RETURNING id
            """,
            (now_utc(), now_utc(), lead_id),
        )

        self.audit.log_change(
            entity_type="lead",
            entity_id=lead_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")},
        )
        return True

    def list_page(
        self,
        status: str | None,
        search: str | None,
        limit: int,
        cursor: str | None,
    ) -> LeadPage:
        """
        Cursor-paginated lead listing ordered by (created_at DESC, id DESC).
        Optionally filter by status and fuzzy-match on name/email/phone.
        """
        if limit < 1:
            raise ValueError("Lead page limit must be positive")

        conditions = ["deleted_at IS NULL"]
        params: list = []

        if status:
            conditions.append("status = %s")
            params.append(status)

        if search:
            terms = search.split()
            columns = "(name ILIKE %s OR email ILIKE %s OR phone ILIKE %s OR service_interest ILIKE %s)"
            term_clauses = []
            for term in terms:
                if term:
                    pattern = f"%{term}%"
                    term_clauses.append(columns)
                    params.extend([pattern] * 4)
            if term_clauses:
                conditions.append(f"({') AND ('.join(term_clauses)})")

        if cursor is not None:
            from core.services.customer_service import _decode_customer_cursor
            created_at, id_ = _decode_customer_cursor(cursor)
            conditions.append("(created_at, id) < (%s, %s)")
            params.extend([created_at, id_])

        params.append(limit + 1)
        rows = self.postgres.execute(
            f"""
            SELECT * FROM leads
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        leads = [Lead.model_validate(row) for row in rows]
        has_more = len(leads) > limit
        selected = leads[:limit]
        next_cursor = None
        if has_more and selected:
            from core.services.customer_service import _encode_customer_cursor
            next_cursor = _encode_customer_cursor(selected[-1].created_at, selected[-1].id)
        return LeadPage(leads=selected, next_cursor=next_cursor)
