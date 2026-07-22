"""Canonical transactional workflow for structured ticket closeout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Iterable
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg.types.json import Json

from clients.postgres_client import PostgresClient
from core.audit import AuditAction, AuditLogger, compute_changes
from core.exceptions import NotFoundError, TicketNotCloseableError
from core.models import (
    BillingHoldResolution,
    CloseoutProfileUpdate,
    CloseoutRequest,
    CloseoutResult,
    FollowUpAction,
    FollowUpActionRecord,
    FutureServicePlan,
    LineItem,
    LineItemCreate,
    MessageType,
    NextServiceDisposition,
    PlannedService,
    ScheduledMessageCreate,
    ScopeDeviation,
    Ticket,
    TicketCloseout,
    TicketCreate,
)
from core.services.line_item_service import LineItemService
from core.services.message_service import MessageService
from core.services.ticket_service import TicketService
from utils.timezone import now_utc
from utils.workspace_context import (
    get_current_workspace_id,
    get_current_workspace_timezone,
)


@dataclass
class _LineState:
    """Quoted and final values for one current-ticket line item."""

    quoted: LineItem
    service_id: UUID
    quantity: int
    unit_price_cents: int | None
    total_price_cents: int | None


class TicketCloseoutService:
    """Reconcile one quoted ticket and atomically create its office follow-through."""

    def __init__(
        self,
        postgres: PostgresClient,
        audit: AuditLogger,
        ticket_service: TicketService,
        line_item_service: LineItemService,
        message_service: MessageService,
    ) -> None:
        self.postgres = postgres
        self.audit = audit
        self.ticket_service = ticket_service
        self.line_item_service = line_item_service
        self.message_service = message_service

    def closeout(self, data: CloseoutRequest) -> CloseoutResult:
        """Execute the entire structured closeout command as one transaction."""
        with self.postgres.transaction():
            ticket = self._load_open_ticket(data.ticket_id)
            quoted_line_items = self._load_quoted_line_items(ticket.id)
            self._assert_no_existing_invoice(ticket.id)
            self._validate_deviations(data, quoted_line_items)

            final_lines = self._reconcile_line_items(
                ticket=ticket,
                reconciliation=data.work_reconciliation,
                quoted_line_items=quoted_line_items,
            )
            ticket = self._record_actual_duration(ticket, data.actual_duration_minutes)
            final_subtotal_cents = sum(
                line.total_price_cents or 0 for _, line in final_lines
            )
            closeout = self._create_closeout_record(
                ticket=ticket,
                data=data,
                final_subtotal_cents=final_subtotal_cents,
            )
            self._create_line_item_snapshots(closeout.id, final_lines)
            profile_updates = self._create_profile_updates(closeout, ticket, data)

            future_ticket, service_plan = self._create_next_service(
                closeout=closeout,
                ticket=ticket,
                quoted_line_items=quoted_line_items,
                next_service=data.next_service,
            )
            if future_ticket is not None:
                closeout = self._set_future_ticket(closeout.id, future_ticket.id)

            follow_up_actions = self._create_follow_up_actions(
                closeout=closeout,
                ticket=ticket,
                actions=[
                    *data.follow_up_actions,
                    *[
                        deviation.escalation.action
                        for deviation in data.work_reconciliation.deviations
                        if deviation.escalation is not None
                    ],
                ],
            )
            follow_up_actions.extend(
                self._create_next_service_communications(
                    closeout=closeout,
                    ticket=ticket,
                    future_ticket=future_ticket,
                    next_service=data.next_service,
                )
            )

            closed_ticket = self.ticket_service.close(
                ticket.id,
                suppress_default_service_reminder=True,
                publish_event=False,
            )

        self.ticket_service.publish_completed_event(
            closed_ticket,
            suppress_default_service_reminder=True,
        )
        return CloseoutResult(
            ticket=closed_ticket.model_dump(mode="json"),
            closeout=closeout,
            future_ticket=(
                future_ticket.model_dump(mode="json") if future_ticket is not None else None
            ),
            service_plan=service_plan,
            profile_updates=profile_updates,
            follow_up_actions=follow_up_actions,
        )

    def resolve_billing_hold(self, data: BillingHoldResolution) -> TicketCloseout:
        """Resolve every open billing escalation and unlock its reconciled total for invoicing."""
        with self.postgres.transaction():
            ticket = self.postgres.execute_single(
                """
                SELECT id FROM tickets
                WHERE id = %s AND deleted_at IS NULL
                FOR UPDATE
                """,
                (data.ticket_id,),
            )
            if ticket is None:
                raise NotFoundError(f"Ticket {data.ticket_id} not found")

            row = self.postgres.execute_single(
                """
                SELECT * FROM ticket_closeouts
                WHERE ticket_id = %s
                FOR UPDATE
                """,
                (data.ticket_id,),
            )
            if row is None:
                raise NotFoundError(f"Ticket {data.ticket_id} has no closeout")
            closeout = TicketCloseout.model_validate(row)
            if data.confirmed_total_cents != closeout.final_subtotal_cents:
                raise ValueError(
                    "confirmed_total_cents must equal the closeout final_subtotal_cents; "
                    "billing-hold resolution cannot alter reconciled ticket prices"
                )

            resolved_actions: list[FollowUpAction] = []
            resolved_deviations: list[ScopeDeviation] = []
            for deviation in closeout.work_reconciliation.deviations:
                escalation = deviation.escalation
                if (
                    escalation is not None
                    and escalation.category == "billing_uncertainty"
                    and escalation.disposition != "resolved"
                ):
                    resolved_actions.append(escalation.action)
                    resolved_deviations.append(
                        deviation.model_copy(
                            update={
                                "escalation": escalation.model_copy(
                                    update={
                                        "disposition": "resolved",
                                        "resolution_note": data.resolution_note,
                                    }
                                )
                            }
                        )
                    )
                else:
                    resolved_deviations.append(deviation)
            if not resolved_actions:
                raise ValueError(f"Ticket {data.ticket_id} has no unresolved billing escalation")

            resolved_reconciliation = closeout.work_reconciliation.model_copy(
                update={"deviations": resolved_deviations}
            )
            invoice_ready = closeout.final_subtotal_cents > 0
            updated_row = self.postgres.execute_returning(
                """
                UPDATE ticket_closeouts
                SET work_reconciliation = %s, invoice_ready = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    Json(resolved_reconciliation.model_dump(mode="json")),
                    invoice_ready,
                    closeout.id,
                ),
            )[0]
            updated = TicketCloseout.model_validate(updated_row)
            self._complete_billing_actions(
                closeout=updated,
                actions=resolved_actions,
                resolution_note=data.resolution_note,
            )
            self.audit.log_change(
                entity_type="ticket_closeout",
                entity_id=updated.id,
                action=AuditAction.UPDATE,
                changes={
                    "work_reconciliation": {
                        "old": closeout.work_reconciliation.model_dump(mode="json"),
                        "new": resolved_reconciliation.model_dump(mode="json"),
                    },
                    "invoice_ready": {
                        "old": closeout.invoice_ready,
                        "new": updated.invoice_ready,
                    },
                    "billing_resolution": data.model_dump(mode="json"),
                },
            )
            return updated

    # ------------------------------------------------------------------ reads

    def get_for_ticket(self, ticket_id: UUID) -> TicketCloseout | None:
        """Return the structured closeout aggregate for one ticket."""
        row = self.postgres.execute_single(
            "SELECT * FROM ticket_closeouts WHERE ticket_id = %s",
            (ticket_id,),
        )
        return TicketCloseout.model_validate(row) if row is not None else None

    def list_profile_updates_for_customer(
        self,
        customer_id: UUID,
        limit: int = 100,
    ) -> list[CloseoutProfileUpdate]:
        """Return closeout-sourced profile facts newest first."""
        rows = self.postgres.execute(
            """
            SELECT * FROM ticket_closeout_profile_updates
            WHERE customer_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (customer_id, limit),
        )
        return [self._profile_update_from_row(row) for row in rows]

    def list_follow_up_actions_for_customer(
        self,
        customer_id: UUID,
        limit: int = 100,
    ) -> list[FollowUpActionRecord]:
        """Return open and historical closeout actions for one customer."""
        rows = self.postgres.execute(
            """
            SELECT * FROM ticket_closeout_follow_up_actions
            WHERE customer_id = %s
            ORDER BY status = 'open' DESC, due_at ASC NULLS LAST, created_at DESC
            LIMIT %s
            """,
            (customer_id, limit),
        )
        return [FollowUpActionRecord.model_validate(row) for row in rows]

    def list_follow_up_actions_for_ticket(
        self,
        ticket_id: UUID,
    ) -> list[FollowUpActionRecord]:
        """Return follow-up actions generated by one ticket closeout."""
        rows = self.postgres.execute(
            """
            SELECT action.*
            FROM ticket_closeout_follow_up_actions AS action
            JOIN ticket_closeouts AS closeout ON closeout.id = action.ticket_closeout_id
            WHERE closeout.ticket_id = %s
            ORDER BY action.status = 'open' DESC, action.due_at ASC NULLS LAST, action.created_at DESC
            """,
            (ticket_id,),
        )
        return [FollowUpActionRecord.model_validate(row) for row in rows]

    def list_service_plans_for_customer(
        self,
        customer_id: UUID,
        limit: int = 100,
    ) -> list[FutureServicePlan]:
        """Return non-exact bookings and reminders generated from closeouts."""
        rows = self.postgres.execute(
            """
            SELECT * FROM future_service_plans
            WHERE customer_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (customer_id, limit),
        )
        return [FutureServicePlan.model_validate(row) for row in rows]

    # ------------------------------------------------------------- command core

    def _load_open_ticket(self, ticket_id: UUID) -> Ticket:
        """Lock one nonterminal ticket before reconciling its quoted scope."""
        row = self.postgres.execute_single(
            """
            SELECT * FROM tickets
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (ticket_id,),
        )
        if row is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        ticket = Ticket.model_validate(row)
        if ticket.is_closed:
            raise TicketNotCloseableError(f"Ticket {ticket_id} already closed")
        return ticket

    def _load_quoted_line_items(self, ticket_id: UUID) -> list[LineItem]:
        """Lock the quoted baseline so concurrent scope edits cannot race closeout."""
        rows = self.postgres.execute(
            """
            SELECT * FROM line_items
            WHERE ticket_id = %s AND deleted_at IS NULL
            ORDER BY created_at ASC
            FOR UPDATE
            """,
            (ticket_id,),
        )
        return [LineItem.model_validate(row) for row in rows]

    def _assert_no_existing_invoice(self, ticket_id: UUID) -> None:
        """Do not silently diverge a previously issued invoice from final closeout prices."""
        invoice = self.postgres.execute_single(
            """
            SELECT id FROM invoices
            WHERE ticket_id = %s AND deleted_at IS NULL AND status <> 'void'
            LIMIT 1
            """,
            (ticket_id,),
        )
        if invoice is not None:
            raise ValueError(
                f"Ticket {ticket_id} already has invoice {invoice['id']}; reconcile it before closeout"
            )

    def _validate_deviations(
        self,
        data: CloseoutRequest,
        quoted_line_items: list[LineItem],
    ) -> None:
        """Ensure each stated exception can be reconciled against the loaded quote."""
        quoted_ids = {line_item.id for line_item in quoted_line_items}
        addressed_line_ids: set[UUID] = set()
        for deviation in data.work_reconciliation.deviations:
            line_item_id = deviation.line_item_id
            if line_item_id is not None:
                if line_item_id not in quoted_ids:
                    raise ValueError(
                        f"deviation line_item_id {line_item_id} does not belong to ticket {data.ticket_id}"
                    )
                if line_item_id in addressed_line_ids:
                    raise ValueError(
                        f"line item {line_item_id} has multiple deviations; combine them into one record"
                    )
                addressed_line_ids.add(line_item_id)

            if (
                deviation.deviation_type
                in {
                    "omitted",
                    "partially_completed",
                    "substituted",
                    "quantity_changed",
                    "price_changed",
                }
                and line_item_id is None
                and data.work_reconciliation.quoted_scope_status != "not_completed"
            ):
                raise ValueError(
                    f"{deviation.deviation_type} requires line_item_id unless quoted_scope_status is not_completed"
                )

    def _reconcile_line_items(
        self,
        *,
        ticket: Ticket,
        reconciliation,
        quoted_line_items: list[LineItem],
    ) -> list[tuple[LineItem | None, LineItem]]:
        """Apply only stated exceptions, leaving the quoted baseline intact otherwise."""
        states = {
            line_item.id: _LineState(
                quoted=line_item,
                service_id=line_item.service_id,
                quantity=line_item.quantity,
                unit_price_cents=line_item.unit_price_cents,
                total_price_cents=line_item.total_price_cents,
            )
            for line_item in quoted_line_items
        }
        if reconciliation.quoted_scope_status == "not_completed":
            for state in states.values():
                state.quantity = 0
                state.total_price_cents = 0

        additions: list[LineItem] = []
        for deviation in reconciliation.deviations:
            if deviation.deviation_type == "added":
                additions.append(self._create_added_line_item(ticket, deviation))
                continue
            if deviation.line_item_id is None:
                continue
            state = states[deviation.line_item_id]
            self._apply_deviation(state, deviation)

        reconciled: list[tuple[LineItem | None, LineItem]] = []
        for state in states.values():
            reconciled.append((state.quoted, self._persist_line_state(state)))
        reconciled.extend((None, line_item) for line_item in additions)
        return reconciled

    def _apply_deviation(self, state: _LineState, deviation: ScopeDeviation) -> None:
        """Mutate one final line state from a single validated scope exception."""
        if deviation.deviation_type == "omitted":
            state.quantity = 0
            state.total_price_cents = self._resolved_total_price(state, deviation)
            return

        if deviation.deviation_type in {"partially_completed", "quantity_changed"}:
            assert deviation.actual_quantity is not None
            state.quantity = deviation.actual_quantity
            state.total_price_cents = self._resolved_total_price(state, deviation)
            return

        if deviation.deviation_type == "substituted":
            assert deviation.service_id is not None
            assert deviation.billing_disposition is not None
            state.service_id = deviation.service_id
            if (
                deviation.billing_disposition == "billable"
                and deviation.final_price_cents is None
            ):
                replacement_unit_price_cents, replacement_total_price_cents = self._catalog_price(
                    deviation.service_id,
                    quantity=state.quantity,
                )
                state.unit_price_cents = replacement_unit_price_cents
                state.total_price_cents = replacement_total_price_cents
            else:
                # An explicit final total or non-billable substitution has no reliable
                # per-unit price; retaining the quoted service's unit price is false.
                state.unit_price_cents = None
                state.total_price_cents = self._resolved_total_price(
                    state,
                    deviation,
                )
            return

        if deviation.deviation_type == "price_changed":
            state.total_price_cents = self._resolved_total_price(state, deviation)
            return

        if deviation.deviation_type == "result_limitation":
            if deviation.final_price_cents is not None:
                state.total_price_cents = deviation.final_price_cents
            elif deviation.billing_disposition in {"complimentary", "not_applicable"}:
                state.total_price_cents = 0

    def _resolved_total_price(
        self,
        state: _LineState,
        deviation: ScopeDeviation,
    ) -> int | None:
        """Resolve final billing without inventing a price for an ambiguous change."""
        if deviation.billing_disposition in {"complimentary", "not_applicable"}:
            return 0
        if deviation.billing_disposition == "included":
            return state.quoted.total_price_cents
        if deviation.final_price_cents is not None:
            return deviation.final_price_cents
        if state.unit_price_cents is not None:
            return state.quantity * state.unit_price_cents
        if state.quantity == state.quoted.quantity:
            return state.quoted.total_price_cents
        raise ValueError(
            f"line item {state.quoted.id} has no unit price; {deviation.deviation_type} "
            "requires final_price_cents"
        )

    def _create_added_line_item(self, ticket: Ticket, deviation: ScopeDeviation) -> LineItem:
        """Create a new current-ticket line for an explicitly added service."""
        assert deviation.service_id is not None
        assert deviation.billing_disposition is not None
        quantity = deviation.actual_quantity if deviation.actual_quantity is not None else 1
        if deviation.billing_disposition in {"complimentary", "included", "not_applicable"}:
            total_price_cents: int | None = 0
        else:
            total_price_cents = deviation.final_price_cents

        line_item = self.line_item_service.create(
            ticket.id,
            LineItemCreate(
                service_id=deviation.service_id,
                description=deviation.affected_item,
                quantity=quantity,
                total_price_cents=total_price_cents,
                notes=deviation.description,
            ),
        )
        if line_item.total_price_cents is None:
            raise ValueError(
                f"added service {deviation.service_id} has no final or catalog price; "
                "supply final_price_cents"
            )
        return line_item

    def _persist_line_state(self, state: _LineState) -> LineItem:
        """Write a final reconciled line only when it differs from the quote."""
        quoted = state.quoted
        if (
            state.service_id == quoted.service_id
            and state.quantity == quoted.quantity
            and state.unit_price_cents == quoted.unit_price_cents
            and state.total_price_cents == quoted.total_price_cents
        ):
            return quoted

        row = self.postgres.execute_returning(
            """
            UPDATE line_items
            SET service_id = %s,
                quantity = %s,
                unit_price_cents = %s,
                total_price_cents = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                state.service_id,
                state.quantity,
                state.unit_price_cents,
                state.total_price_cents,
                now_utc(),
                quoted.id,
            ),
        )[0]
        updated = LineItem.model_validate(row)
        changes = compute_changes(
            quoted.model_dump(mode="json"),
            updated.model_dump(mode="json"),
        )
        if changes:
            self.audit.log_change(
                entity_type="line_item",
                entity_id=updated.id,
                action=AuditAction.UPDATE,
                changes=changes,
            )
        return updated

    def _record_actual_duration(self, ticket: Ticket, actual_duration_minutes: int) -> Ticket:
        """Persist actual work time separately from all billable reconciliation."""
        row = self.postgres.execute_returning(
            """
            UPDATE tickets
            SET actual_duration_minutes = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (actual_duration_minutes, now_utc(), ticket.id),
        )[0]
        updated = Ticket.model_validate(row)
        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket.id,
            action=AuditAction.UPDATE,
            changes={
                "actual_duration_minutes": {
                    "old": ticket.actual_duration_minutes,
                    "new": actual_duration_minutes,
                }
            },
        )
        return updated

    # -------------------------------------------------------------- persistence

    def _create_closeout_record(
        self,
        *,
        ticket: Ticket,
        data: CloseoutRequest,
        final_subtotal_cents: int,
    ) -> TicketCloseout:
        """Persist the canonical aggregate before dependent facts and plans."""
        closeout_id = uuid4()
        now = now_utc()
        invoice_ready = final_subtotal_cents > 0 and not any(
            deviation.escalation is not None
            and deviation.escalation.category == "billing_uncertainty"
            and deviation.escalation.disposition != "resolved"
            for deviation in data.work_reconciliation.deviations
        )
        row = self.postgres.execute_returning(
            """
            INSERT INTO ticket_closeouts (
                id, workspace_id, ticket_id, actual_duration_minutes,
                work_reconciliation, customer_capture, next_service,
                technician_summary, final_subtotal_cents, invoice_ready,
                future_ticket_id, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                closeout_id,
                get_current_workspace_id(),
                ticket.id,
                data.actual_duration_minutes,
                Json(data.work_reconciliation.model_dump(mode="json")),
                Json(data.customer_capture.model_dump(mode="json")),
                Json(data.next_service.model_dump(mode="json")),
                data.technician_summary,
                final_subtotal_cents,
                invoice_ready,
                None,
                now,
            ),
        )[0]
        closeout = TicketCloseout.model_validate(row)
        self.audit.log_change(
            entity_type="ticket_closeout",
            entity_id=closeout.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json")},
        )
        return closeout

    def _create_line_item_snapshots(
        self,
        closeout_id: UUID,
        final_lines: Iterable[tuple[LineItem | None, LineItem]],
    ) -> None:
        """Store quoted and final line states for audit-safe future invoicing review."""
        workspace_id = get_current_workspace_id()
        for quoted_line_item, final_line_item in final_lines:
            self.postgres.execute(
                """
                INSERT INTO ticket_closeout_line_items (
                    id, workspace_id, ticket_closeout_id, line_item_id,
                    quoted_line_item, final_line_item, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    workspace_id,
                    closeout_id,
                    final_line_item.id,
                    (
                        Json(quoted_line_item.model_dump(mode="json"))
                        if quoted_line_item is not None
                        else None
                    ),
                    Json(final_line_item.model_dump(mode="json")),
                    now_utc(),
                ),
            )

    def _create_profile_updates(
        self,
        closeout: TicketCloseout,
        ticket: Ticket,
        data: CloseoutRequest,
    ) -> list[CloseoutProfileUpdate]:
        """Persist typed profile facts with their direct source and uncertainty."""
        created: list[CloseoutProfileUpdate] = []
        workspace_id = get_current_workspace_id()
        for update in data.customer_capture.profile_updates:
            payload = update.model_dump(mode="json")
            row = self.postgres.execute_returning(
                """
                INSERT INTO ticket_closeout_profile_updates (
                    id, workspace_id, ticket_closeout_id, customer_id, address_id,
                    update_type, subject_type, subject_label, payload,
                    source, certainty, persistence, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    uuid4(),
                    workspace_id,
                    closeout.id,
                    ticket.customer_id,
                    ticket.address_id,
                    payload["update_type"],
                    payload["subject_type"],
                    self._profile_subject_label(payload),
                    Json(payload),
                    payload["source"],
                    payload["certainty"],
                    payload["persistence"],
                    now_utc(),
                ),
            )[0]
            record = self._profile_update_from_row(row)
            self.audit.log_change(
                entity_type="ticket_closeout_profile_update",
                entity_id=record.id,
                action=AuditAction.CREATE,
                changes={"created": record.model_dump(mode="json")},
            )
            created.append(record)
        return created

    @staticmethod
    def _profile_subject_label(payload: dict[str, object]) -> str | None:
        """Extract an identifier for contact and asset scoped profile facts."""
        for field in ("contact_name", "asset", "subject_label"):
            value = payload.get(field)
            if isinstance(value, str) and value:
                return value
        return None

    def _set_future_ticket(self, closeout_id: UUID, future_ticket_id: UUID) -> TicketCloseout:
        """Attach an exact future booking to the closeout that created it."""
        row = self.postgres.execute_returning(
            """
            UPDATE ticket_closeouts
            SET future_ticket_id = %s
            WHERE id = %s
            RETURNING *
            """,
            (future_ticket_id, closeout_id),
        )[0]
        return TicketCloseout.model_validate(row)

    # ---------------------------------------------------------- future service

    def _create_next_service(
        self,
        *,
        closeout: TicketCloseout,
        ticket: Ticket,
        quoted_line_items: list[LineItem],
        next_service: NextServiceDisposition,
    ) -> tuple[Ticket | None, FutureServicePlan | None]:
        """Create an exact ticket or a durable flexible/reminder service plan."""
        if next_service.disposition in {"declined", "undecided", "not_applicable"}:
            return None, None

        planned_scope = self._planned_scope(next_service, quoted_line_items)
        if next_service.disposition == "book" and next_service.scheduling_mode == "exact":
            assert next_service.timing is not None
            assert next_service.timing.exact_at is not None
            planned_duration = (
                next_service.planned_duration_minutes
                if next_service.planned_duration_minutes is not None
                else ticket.scheduled_duration_minutes
            )
            future_ticket = self.ticket_service.create(
                TicketCreate(
                    customer_id=ticket.customer_id,
                    address_id=ticket.address_id,
                    scheduled_at=next_service.timing.exact_at,
                    scheduled_duration_minutes=planned_duration,
                    is_price_estimated=next_service.pricing_status == "set_later",
                ),
                suppress_automatic_confirmation=next_service.confirmation_channel is not None,
            )
            for planned_service in planned_scope:
                self.line_item_service.create(
                    future_ticket.id,
                    self._line_item_create_for_plan(planned_service, next_service.pricing_status),
                )
            return future_ticket, None

        assert next_service.timing is not None
        plan_id = uuid4()
        now = now_utc()
        row = self.postgres.execute_returning(
            """
            INSERT INTO future_service_plans (
                id, workspace_id, ticket_closeout_id, customer_id, address_id,
                disposition, status, timing, planned_scope,
                planned_duration_minutes, pricing_status, scheduling_mode,
                routing_instruction, confirmation_channel, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                plan_id,
                get_current_workspace_id(),
                closeout.id,
                ticket.customer_id,
                ticket.address_id,
                next_service.disposition,
                "pending" if next_service.disposition == "book" else "reminder",
                Json(next_service.timing.model_dump(mode="json")),
                Json([service.model_dump(mode="json") for service in planned_scope]),
                next_service.planned_duration_minutes,
                next_service.pricing_status,
                next_service.scheduling_mode,
                next_service.routing_instruction,
                next_service.confirmation_channel,
                now,
                now,
            ),
        )[0]
        service_plan = FutureServicePlan.model_validate(row)
        self.audit.log_change(
            entity_type="future_service_plan",
            entity_id=service_plan.id,
            action=AuditAction.CREATE,
            changes={"created": service_plan.model_dump(mode="json")},
        )
        return None, service_plan

    def _planned_scope(
        self,
        next_service: NextServiceDisposition,
        quoted_line_items: list[LineItem],
    ) -> list[PlannedService]:
        """Reuse only quoted scope when no explicit future scope is supplied."""
        if next_service.planned_scope:
            planned_scope = list(next_service.planned_scope)
        else:
            planned_scope = [
                PlannedService(
                    service_id=line_item.service_id,
                    description=line_item.description,
                    quantity=line_item.quantity,
                    unit_price_cents=line_item.unit_price_cents,
                    total_price_cents=line_item.total_price_cents,
                    duration_minutes=line_item.duration_minutes,
                    notes=line_item.notes,
                )
                for line_item in quoted_line_items
            ]
        if next_service.disposition == "book" and not planned_scope:
            raise ValueError(
                "book next_service requires planned_scope when the quoted ticket has no line items"
            )
        if next_service.pricing_status == "set" and any(
            service.unit_price_cents is None and service.total_price_cents is None
            for service in planned_scope
        ):
            raise ValueError(
                "set pricing requires a unit_price_cents or total_price_cents for every planned service"
            )
        if next_service.pricing_status in {"catalog_default", "set_later"}:
            return [
                service.model_copy(
                    update={"unit_price_cents": None, "total_price_cents": None}
                )
                for service in planned_scope
            ]
        return planned_scope

    @staticmethod
    def _line_item_create_for_plan(
        planned_service: PlannedService,
        pricing_status: str | None,
    ) -> LineItemCreate:
        """Apply one pricing policy while creating an exact future ticket line."""
        if pricing_status == "catalog_default":
            unit_price_cents = None
            total_price_cents = None
        elif pricing_status == "set_later":
            unit_price_cents = None
            total_price_cents = None
        else:
            unit_price_cents = planned_service.unit_price_cents
            total_price_cents = planned_service.total_price_cents
        return LineItemCreate(
            service_id=planned_service.service_id,
            description=planned_service.description,
            quantity=planned_service.quantity,
            unit_price_cents=unit_price_cents,
            total_price_cents=total_price_cents,
            duration_minutes=planned_service.duration_minutes,
            notes=planned_service.notes,
        )

    def _create_next_service_communications(
        self,
        *,
        closeout: TicketCloseout,
        ticket: Ticket,
        future_ticket: Ticket | None,
        next_service: NextServiceDisposition,
    ) -> list[FollowUpActionRecord]:
        """Schedule email work or record a human action for the selected channel."""
        channel = next_service.confirmation_channel
        if channel in (None, "none"):
            return []

        if next_service.disposition == "book":
            if channel == "email":
                self.message_service.schedule(
                    ScheduledMessageCreate(
                        customer_id=ticket.customer_id,
                        ticket_id=future_ticket.id if future_ticket is not None else None,
                        message_type=(
                            MessageType.APPOINTMENT_CONFIRMATION
                            if future_ticket is not None
                            else MessageType.CUSTOM
                        ),
                        subject=(
                            "Appointment confirmation"
                            if future_ticket is not None
                            else "Service plan confirmation"
                        ),
                        body=(
                            "Your appointment has been scheduled."
                            if future_ticket is not None
                            else "Your service plan has been recorded."
                        ),
                        scheduled_for=now_utc(),
                    )
                )
                return []
            return [
                self._create_generated_action(
                    closeout=closeout,
                    ticket=ticket,
                    action_type="send_confirmation",
                    description=(
                        "Confirm the scheduled appointment."
                        if future_ticket is not None
                        else "Confirm the flexible service plan."
                    ),
                    due_at=now_utc(),
                    channel=channel,
                )
            ]

        assert next_service.disposition == "remind"
        assert next_service.timing is not None
        due_at = self._reminder_due_at(next_service.timing.exact_at, next_service.timing.window_start)
        if channel == "email":
            self.message_service.schedule(
                ScheduledMessageCreate(
                    customer_id=ticket.customer_id,
                    ticket_id=None,
                    message_type=MessageType.SERVICE_REMINDER,
                    subject="Service reminder",
                    body="It may be time to schedule your next service appointment.",
                    scheduled_for=due_at,
                )
            )
            return []
        return [
            self._create_generated_action(
                closeout=closeout,
                ticket=ticket,
                action_type="send_service_reminder",
                description="Contact the customer with the requested service reminder.",
                due_at=due_at,
                channel=channel,
            )
        ]

    @staticmethod
    def _reminder_due_at(exact_at: datetime | None, window_start) -> datetime:
        """Use an exact time or the start of the requested local date window."""
        if exact_at is not None:
            return exact_at
        assert window_start is not None
        local = datetime.combine(
            window_start,
            time(hour=9),
            tzinfo=ZoneInfo(get_current_workspace_timezone()),
        )
        return local.astimezone(timezone.utc)

    # -------------------------------------------------------------- follow-ups

    def _create_follow_up_actions(
        self,
        *,
        closeout: TicketCloseout,
        ticket: Ticket,
        actions: list[FollowUpAction],
    ) -> list[FollowUpActionRecord]:
        """Persist each distinct concrete office or customer obligation once."""
        return [
            self._create_action(
                closeout=closeout,
                ticket=ticket,
                action_type=action.action_type,
                responsible_party=action.responsible_party,
                description=action.description,
                due_at=action.due_at,
                channel=action.channel,
            )
            for action in self._deduplicate_actions(actions)
        ]

    @staticmethod
    def _deduplicate_actions(actions: list[FollowUpAction]) -> list[FollowUpAction]:
        """Coalesce identical nested and top-level declarations into one obligation."""
        seen: set[tuple[str, str, str, datetime | None, str | None]] = set()
        unique_actions: list[FollowUpAction] = []
        for action in actions:
            key = (
                action.action_type,
                action.responsible_party,
                action.description,
                action.due_at,
                action.channel,
            )
            if key not in seen:
                seen.add(key)
                unique_actions.append(action)
        return unique_actions

    def _complete_billing_actions(
        self,
        *,
        closeout: TicketCloseout,
        actions: list[FollowUpAction],
        resolution_note: str,
    ) -> None:
        """Mark the resolved billing obligations complete alongside the audited hold release."""
        now = now_utc()
        for action in self._deduplicate_actions(actions):
            rows = self.postgres.execute_returning(
                """
                UPDATE ticket_closeout_follow_up_actions
                SET status = 'completed', updated_at = %s
                WHERE ticket_closeout_id = %s
                  AND action_type = %s
                  AND responsible_party = %s
                  AND description = %s
                  AND due_at IS NOT DISTINCT FROM %s
                  AND channel IS NOT DISTINCT FROM %s
                  AND status = 'open'
                RETURNING *
                """,
                (
                    now,
                    closeout.id,
                    action.action_type,
                    action.responsible_party,
                    action.description,
                    action.due_at,
                    action.channel,
                ),
            )
            for row in rows:
                completed_action = FollowUpActionRecord.model_validate(row)
                self.audit.log_change(
                    entity_type="ticket_closeout_follow_up_action",
                    entity_id=completed_action.id,
                    action=AuditAction.UPDATE,
                    changes={
                        "status": {"old": "open", "new": "completed"},
                        "billing_resolution": resolution_note,
                    },
                )

    def _create_generated_action(
        self,
        *,
        closeout: TicketCloseout,
        ticket: Ticket,
        action_type: str,
        description: str,
        due_at: datetime,
        channel: str,
    ) -> FollowUpActionRecord:
        """Persist a required human communication that CRM cannot send directly."""
        return self._create_action(
            closeout=closeout,
            ticket=ticket,
            action_type=action_type,
            responsible_party="business",
            description=description,
            due_at=due_at,
            channel=channel,
        )

    def _create_action(
        self,
        *,
        closeout: TicketCloseout,
        ticket: Ticket,
        action_type: str,
        responsible_party: str,
        description: str,
        due_at: datetime | None,
        channel: str | None,
    ) -> FollowUpActionRecord:
        """Insert and audit one executable closeout obligation."""
        now = now_utc()
        row = self.postgres.execute_returning(
            """
            INSERT INTO ticket_closeout_follow_up_actions (
                id, workspace_id, ticket_closeout_id, customer_id, address_id,
                action_type, responsible_party, description, due_at, channel,
                status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING *
            """,
            (
                uuid4(),
                get_current_workspace_id(),
                closeout.id,
                ticket.customer_id,
                ticket.address_id,
                action_type,
                responsible_party,
                description,
                due_at,
                channel,
                "open",
                now,
                now,
            ),
        )[0]
        action = FollowUpActionRecord.model_validate(row)
        self.audit.log_change(
            entity_type="ticket_closeout_follow_up_action",
            entity_id=action.id,
            action=AuditAction.CREATE,
            changes={"created": action.model_dump(mode="json")},
        )
        return action

    # -------------------------------------------------------------- conversion

    @staticmethod
    def _profile_update_from_row(row: dict) -> CloseoutProfileUpdate:
        """Map the storage payload column to the public typed update field."""
        return CloseoutProfileUpdate.model_validate({
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "ticket_closeout_id": row["ticket_closeout_id"],
            "customer_id": row["customer_id"],
            "address_id": row["address_id"],
            "update": row["payload"],
            "created_at": row["created_at"],
        })

    def _catalog_price(self, service_id: UUID, *, quantity: int) -> tuple[int | None, int]:
        """Resolve a replacement's catalog price or reject a flexible-price ambiguity."""
        row = self.postgres.execute_single(
            """
            SELECT default_price_cents, unit_price_cents
            FROM services
            WHERE id = %s AND deleted_at IS NULL
            """,
            (service_id,),
        )
        if row is None:
            raise NotFoundError(f"Service {service_id} not found")
        if row["default_price_cents"] is not None:
            return None, row["default_price_cents"]
        if row["unit_price_cents"] is not None:
            return row["unit_price_cents"], row["unit_price_cents"] * quantity
        raise ValueError(
            f"replacement service {service_id} has no catalog price; supply final_price_cents"
        )
