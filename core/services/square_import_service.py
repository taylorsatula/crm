"""Transactional, idempotent ingestion of Square customer and job history."""

from decimal import Decimal
from uuid import UUID, uuid4

from psycopg.types.json import Json

from clients.postgres_client import PostgresClient
from core.audit import AuditAction, AuditLogger
from core.models.square_import import (
    SquareBookingImport,
    SquareCustomerImport,
    SquareImportBatchRequest,
    SquareImportBatchResult,
    SquareSale,
    SquareSaleImport,
    SquareSaleLine,
    SquareServiceImport,
)
from utils.timezone import now_utc
from utils.workspace_context import get_current_workspace_id


class SquareImportService:
    """Own Square-specific persistence without invoking operational workflows."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def apply_batch(self, request: SquareImportBatchRequest) -> SquareImportBatchResult:
        """Apply a retry-safe import chunk in one workspace-scoped transaction."""
        counts = {
            "customers_created": 0,
            "services_created": 0,
            "tickets_created": 0,
            "sales_created": 0,
            "existing_records": 0,
        }
        with self.postgres.transaction():
            for customer in request.customers:
                _, created = self._ensure_customer(customer, request.import_run_id)
                counts["customers_created" if created else "existing_records"] += 1
            for service in request.services:
                _, created = self._ensure_service(service, request.import_run_id)
                counts["services_created" if created else "existing_records"] += 1
            for booking in request.bookings:
                _, created = self._ensure_booking(booking, request.import_run_id)
                counts["tickets_created" if created else "existing_records"] += 1
            for sale in request.sales:
                _, created = self._ensure_sale(sale, request.import_run_id)
                counts["sales_created" if created else "existing_records"] += 1
        return SquareImportBatchResult(**counts)

    def list_sales_for_customer(self, customer_id: UUID, limit: int = 50) -> list[SquareSale]:
        """Return newest verified Square sales with complete line items."""
        rows = self.postgres.execute(
            """
            SELECT * FROM square_sales
            WHERE customer_id = %s
            ORDER BY occurred_at DESC, id DESC
            LIMIT %s
            """,
            (customer_id, limit),
        )
        sales: list[SquareSale] = []
        for row in rows:
            line_rows = self.postgres.execute(
                """
                SELECT id, square_uid, square_catalog_object_id, name, quantity,
                       base_price_cents, total_price_cents, total_tax_cents,
                       total_discount_cents, total_service_charge_cents
                FROM square_sale_lines
                WHERE sale_id = %s
                ORDER BY ordinal ASC
                """,
                (row["id"],),
            )
            row["lines"] = [SquareSaleLine.model_validate(line) for line in line_rows]
            sales.append(SquareSale.model_validate(row))
        return sales

    def _target_for(self, entity_type: str, square_id: str) -> UUID | None:
        row = self.postgres.execute_single(
            """
            SELECT target_id FROM square_import_links
            WHERE entity_type = %s AND square_id = %s
            """,
            (entity_type, square_id),
        )
        return row["target_id"] if row else None

    def _link(
        self,
        entity_type: str,
        square_id: str,
        target_id: UUID,
        import_run_id: UUID,
    ) -> None:
        self.postgres.execute(
            """
            INSERT INTO square_import_links (
                id, workspace_id, entity_type, square_id, target_id,
                import_run_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                get_current_workspace_id(),
                entity_type,
                square_id,
                target_id,
                import_run_id,
                now_utc(),
            ),
        )

    def _ensure_customer(
        self,
        data: SquareCustomerImport,
        import_run_id: UUID,
    ) -> tuple[UUID, bool]:
        existing = self._target_for("customer", data.square_id)
        if existing:
            return existing, False
        customer_id = uuid4()
        now = now_utc()
        self.postgres.execute(
            """
            INSERT INTO customers (
                id, workspace_id, first_name, last_name, business_name,
                email, phone, address, notes, reference_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                customer_id,
                get_current_workspace_id(),
                data.first_name,
                data.last_name,
                data.business_name,
                data.email,
                data.phone,
                data.address,
                data.notes,
                f"square:{data.square_id}"[:100],
                now,
                now,
            ),
        )
        self._link("customer", data.square_id, customer_id, import_run_id)
        self.audit.log_change(
            "customer",
            customer_id,
            AuditAction.CREATE,
            {"created": data.model_dump(mode="json"), "source": "square"},
        )
        return customer_id, True

    def _ensure_service(
        self,
        data: SquareServiceImport,
        import_run_id: UUID,
    ) -> tuple[UUID, bool]:
        existing = self._target_for("service", data.square_id)
        if existing:
            return existing, False
        service_id = uuid4()
        now = now_utc()
        pricing_type = "fixed" if data.price_cents is not None else "flexible"
        self.postgres.execute(
            """
            INSERT INTO services (
                id, workspace_id, name, description, pricing_type,
                default_price_cents, is_active, display_order, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, true, 0, %s, %s)
            """,
            (
                service_id,
                get_current_workspace_id(),
                data.name,
                data.description,
                pricing_type,
                data.price_cents,
                now,
                now,
            ),
        )
        self._link("service", data.square_id, service_id, import_run_id)
        self.audit.log_change(
            "service",
            service_id,
            AuditAction.CREATE,
            {"created": data.model_dump(mode="json"), "source": "square"},
        )
        return service_id, True

    def _ensure_booking(
        self,
        data: SquareBookingImport,
        import_run_id: UUID,
    ) -> tuple[UUID, bool]:
        existing = self._target_for("booking", data.square_id)
        if existing:
            return existing, False
        customer_id = self._target_for("customer", data.square_customer_id)
        if customer_id is None:
            raise ValueError(f"Square booking {data.square_id} references an unknown customer")

        ticket_id = uuid4()
        now = now_utc()
        closed_at = data.closed_at if data.status in {"completed", "cancelled"} else None
        self.postgres.execute(
            """
            INSERT INTO tickets (
                id, workspace_id, customer_id, address_id, status,
                scheduled_at, scheduled_duration_minutes, confirmation_status,
                notes, closed_at, is_price_estimated, location_type,
                location_label, location_address, source_system,
                source_record_id, financial_match_method, created_at, updated_at
            ) VALUES (
                %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, false,
                %s, %s, %s, 'square', %s, %s, %s, %s
            )
            """,
            (
                ticket_id,
                get_current_workspace_id(),
                customer_id,
                data.status,
                data.start_at,
                data.duration_minutes,
                "confirmed" if data.status == "completed" else "pending",
                data.notes,
                closed_at,
                data.location_type,
                data.location_label,
                Json(data.location_address) if data.location_address else None,
                data.square_id,
                "conservative_customer_service_day" if data.matched_square_order_id else None,
                now,
                now,
            ),
        )
        self._link("booking", data.square_id, ticket_id, import_run_id)
        for segment in data.segments:
            service_id = self._target_for("service", segment.square_service_id)
            if service_id is None:
                service_id, _ = self._ensure_service(
                    SquareServiceImport(
                        square_id=segment.square_service_id,
                        name=segment.name,
                    ),
                    import_run_id,
                )
            self.postgres.execute(
                """
                INSERT INTO line_items (
                    id, workspace_id, ticket_id, service_id, description,
                    quantity, duration_minutes, notes, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    get_current_workspace_id(),
                    ticket_id,
                    service_id,
                    segment.name,
                    segment.duration_minutes,
                    "Imported from Square booking; price supplied only by a matched Square order.",
                    now,
                    now,
                ),
            )
        self.audit.log_change(
            "ticket",
            ticket_id,
            AuditAction.CREATE,
            {"created": data.model_dump(mode="json"), "source": "square"},
        )
        return ticket_id, True

    def _ensure_sale(
        self,
        data: SquareSaleImport,
        import_run_id: UUID,
    ) -> tuple[UUID, bool]:
        existing = self._target_for("sale", data.square_id)
        if existing:
            return existing, False
        customer_id = (
            self._target_for("customer", data.square_customer_id)
            if data.square_customer_id
            else None
        )
        ticket_id = (
            self._target_for("booking", data.matched_square_booking_id)
            if data.matched_square_booking_id
            else None
        )
        sale_id = uuid4()
        now = now_utc()
        self.postgres.execute(
            """
            INSERT INTO square_sales (
                id, workspace_id, customer_id, square_order_id, occurred_at,
                status, currency, subtotal_cents, tax_cents, discount_cents,
                tip_cents, service_charge_cents, total_cents, paid_cents,
                refunded_cents, receipt_url, matched_ticket_id, match_method,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                sale_id,
                get_current_workspace_id(),
                customer_id,
                data.square_id,
                data.occurred_at,
                data.status,
                data.currency,
                data.subtotal_cents,
                data.tax_cents,
                data.discount_cents,
                data.tip_cents,
                data.service_charge_cents,
                data.total_cents,
                data.paid_cents,
                data.refunded_cents,
                data.receipt_url,
                ticket_id,
                data.match_method,
                now,
            ),
        )
        self._link("sale", data.square_id, sale_id, import_run_id)
        for ordinal, line in enumerate(data.lines):
            self.postgres.execute(
                """
                INSERT INTO square_sale_lines (
                    id, workspace_id, sale_id, square_uid,
                    square_catalog_object_id, name, quantity, base_price_cents,
                    total_price_cents, total_tax_cents, total_discount_cents,
                    total_service_charge_cents, ordinal
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    uuid4(),
                    get_current_workspace_id(),
                    sale_id,
                    line.square_uid,
                    line.square_catalog_object_id,
                    line.name,
                    Decimal(line.quantity),
                    line.base_price_cents,
                    line.total_price_cents,
                    line.total_tax_cents,
                    line.total_discount_cents,
                    line.total_service_charge_cents,
                    ordinal,
                ),
            )

        if ticket_id:
            self._replace_ticket_lines_from_sale(ticket_id, data, import_run_id)

        self.audit.log_change(
            "square_sale",
            sale_id,
            AuditAction.CREATE,
            {"created": data.model_dump(mode="json"), "source": "square"},
        )
        return sale_id, True

    def _replace_ticket_lines_from_sale(
        self,
        ticket_id: UUID,
        sale: SquareSaleImport,
        import_run_id: UUID,
    ) -> None:
        """Attach verified order lines to the inferred booking ticket."""
        self.postgres.execute("DELETE FROM line_items WHERE ticket_id = %s", (ticket_id,))
        now = now_utc()
        for line in sale.lines:
            service_square_id = line.square_catalog_object_id or f"adhoc:{line.name}"
            service_id = self._target_for("service", service_square_id)
            if service_id is None:
                service_id, _ = self._ensure_service(
                    SquareServiceImport(
                        square_id=service_square_id,
                        name=line.name,
                        price_cents=line.base_price_cents,
                    ),
                    import_run_id,
                )
            quantity = int(line.quantity) if line.quantity == int(line.quantity) else 1
            self.postgres.execute(
                """
                INSERT INTO line_items (
                    id, workspace_id, ticket_id, service_id, description,
                    quantity, unit_price_cents, total_price_cents, notes,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    get_current_workspace_id(),
                    ticket_id,
                    service_id,
                    line.name,
                    quantity,
                    line.base_price_cents,
                    line.total_price_cents,
                    "Square inferred financial match: customer, service, and local service day.",
                    now,
                    now,
                ),
            )
