"""Structured, exception-based ticket closeout contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CloseoutModel(BaseModel):
    """Strict base model for the structured closeout protocol."""

    model_config = ConfigDict(extra="forbid")


FactSource = Literal[
    "customer_stated",
    "technician_observed",
    "technician_reported_customer_statement",
]
FactCertainty = Literal["confirmed", "likely", "unverified"]
FactPersistence = Literal["durable", "seasonal", "temporary"]


class AppointmentContact(CloseoutModel):
    """Person present for the appointment, distinct from the account holder."""

    name: str = Field(..., min_length=1, max_length=255)
    relationship_to_account: str = Field(..., min_length=1, max_length=255)
    source: FactSource
    certainty: FactCertainty


class ProfileUpdateBase(CloseoutModel):
    """Provenance shared by durable customer-history updates."""

    source: FactSource
    certainty: FactCertainty
    persistence: FactPersistence


class ContactRelationshipProfileUpdate(ProfileUpdateBase):
    """Durable relationship context for a named non-account contact."""

    update_type: Literal["contact_relationship"]
    subject_type: Literal["contact"] = "contact"
    contact_name: str = Field(..., min_length=1, max_length=255)
    relationship: str = Field(..., min_length=1, max_length=255)


class HouseholdDetailProfileUpdate(ProfileUpdateBase):
    """Useful household context associated with the customer or a contact."""

    update_type: Literal["household_detail"]
    subject_type: Literal["customer", "contact"] = "customer"
    detail: str = Field(..., min_length=1, max_length=2000)


class ServicePreferenceProfileUpdate(ProfileUpdateBase):
    """A customer-level service, communication, or scheduling preference."""

    update_type: Literal["service_or_scheduling_preference"]
    subject_type: Literal["customer"] = "customer"
    preference: str = Field(..., min_length=1, max_length=2000)


class SiteInstructionProfileUpdate(ProfileUpdateBase):
    """Address-level preparation, access, or execution instruction."""

    update_type: Literal["site_instruction"]
    subject_type: Literal["address"] = "address"
    instruction: str = Field(..., min_length=1, max_length=2000)


class AssetConditionProfileUpdate(ProfileUpdateBase):
    """Asset condition and handling context for future technicians."""

    update_type: Literal["asset_condition"]
    subject_type: Literal["asset"] = "asset"
    asset: str = Field(..., min_length=1, max_length=500)
    condition: str = Field(..., min_length=1, max_length=2000)
    handling_instruction: str | None = Field(None, max_length=2000)


class ServiceHistoryProfileUpdate(ProfileUpdateBase):
    """Durable customer or asset service-history fact."""

    update_type: Literal["service_history"]
    subject_type: Literal["customer", "asset"] = "customer"
    detail: str = Field(..., min_length=1, max_length=2000)
    asset: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_asset_when_asset_scoped(self) -> "ServiceHistoryProfileUpdate":
        """Keep asset-scoped history attached to an identifiable asset."""
        if self.subject_type == "asset" and not self.asset:
            raise ValueError("asset is required when service_history subject_type is asset")
        return self


class ReferralSourceProfileUpdate(ProfileUpdateBase):
    """Customer referral attribution, including an explicitly unknown source."""

    update_type: Literal["referral_source"]
    subject_type: Literal["customer"] = "customer"
    detail: str = Field(..., min_length=1, max_length=2000)


class RelationshipContextProfileUpdate(ProfileUpdateBase):
    """Other durable context that improves recognition or future interaction."""

    update_type: Literal["durable_relationship_context"]
    subject_type: Literal["customer", "contact", "address", "asset"] = "customer"
    detail: str = Field(..., min_length=1, max_length=2000)
    subject_label: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_label_for_non_customer_subjects(self) -> "RelationshipContextProfileUpdate":
        """Avoid an unresolvable contact, address, or asset fact."""
        if self.subject_type != "customer" and not self.subject_label:
            raise ValueError(
                "subject_label is required when durable_relationship_context is not customer-scoped"
            )
        return self


ProfileUpdate = Annotated[
    ContactRelationshipProfileUpdate
    | HouseholdDetailProfileUpdate
    | ServicePreferenceProfileUpdate
    | SiteInstructionProfileUpdate
    | AssetConditionProfileUpdate
    | ServiceHistoryProfileUpdate
    | ReferralSourceProfileUpdate
    | RelationshipContextProfileUpdate,
    Field(discriminator="update_type"),
]


class CustomerCapture(CloseoutModel):
    """Required customer-side closeout capture, with optional useful profile facts."""

    appointment_contact: AppointmentContact | None = None
    customer_response: Literal[
        "positive_feedback",
        "no_concern_stated",
        "concern_stated",
        "not_reviewed",
        "contact_unavailable",
        "unknown",
    ]
    profile_updates: list[ProfileUpdate]


class FollowUpAction(CloseoutModel):
    """One concrete business or customer action created by closeout."""

    action_type: Literal[
        "create_quote",
        "schedule_return_visit",
        "send_review_request",
        "send_referral_follow_up",
        "send_customer_message",
        "record_customer_callback",
        "track_customer_required_repair",
    ]
    responsible_party: Literal["business", "customer"]
    description: str = Field(..., min_length=1, max_length=4000)
    due_at: datetime | None = None
    channel: Literal["email", "text", "phone", "none"] | None = None


class Escalation(CloseoutModel):
    """Structured disposition and owned action for a material closeout risk."""

    category: Literal[
        "damage",
        "safety_risk",
        "customer_concern_or_dispute",
        "billing_uncertainty",
        "required_return_work",
    ]
    disposition: Literal["resolved", "follow_up_required", "customer_declined"]
    action: FollowUpAction
    resolution_note: str | None = Field(None, min_length=1, max_length=4000)


class ScopeDeviation(CloseoutModel):
    """One exception to the ticket's quoted line-item scope."""

    deviation_type: Literal[
        "added",
        "omitted",
        "partially_completed",
        "substituted",
        "quantity_changed",
        "price_changed",
        "result_limitation",
        "damage",
        "safety_risk",
        "customer_concern",
        "billing_uncertainty",
        "required_return_work",
    ]
    line_item_id: UUID | None = None
    service_id: UUID | None = None
    affected_item: str | None = Field(None, max_length=500)
    description: str = Field(..., min_length=1, max_length=4000)
    reason_code: str | None = Field(None, max_length=100)
    actual_quantity: int | None = Field(None, ge=0)
    final_price_cents: int | None = Field(None, ge=0)
    billing_disposition: Literal[
        "billable",
        "included",
        "complimentary",
        "not_applicable",
    ] | None = None
    customer_acknowledgement: Literal[
        "informed_no_concern",
        "informed_concern",
        "disputed",
        "not_present",
        "not_informed",
    ] | None = None
    future_instruction: str | None = Field(None, max_length=4000)
    escalation: Escalation | None = None

    @model_validator(mode="after")
    def validate_target_and_billing(self) -> "ScopeDeviation":
        """Reject ambiguous deviations before CRM bookkeeping begins."""
        if self.deviation_type == "added":
            if self.service_id is None:
                raise ValueError("added deviations require service_id")
        elif self.deviation_type == "substituted":
            if self.line_item_id is None or self.service_id is None:
                raise ValueError("substituted deviations require line_item_id and replacement service_id")
        elif self.line_item_id is None and not self.affected_item:
            raise ValueError(
                f"{self.deviation_type} deviations require line_item_id or affected_item"
            )

        if self.deviation_type in {"partially_completed", "quantity_changed"}:
            if self.actual_quantity is None:
                raise ValueError(
                    f"{self.deviation_type} deviations require actual_quantity"
                )
        if self.deviation_type in {
            "added",
            "omitted",
            "partially_completed",
            "substituted",
            "quantity_changed",
            "price_changed",
        } and self.billing_disposition is None:
            raise ValueError(
                f"{self.deviation_type} deviations require billing_disposition"
            )
        if self.deviation_type == "price_changed" and self.final_price_cents is None:
            raise ValueError("price_changed deviations require final_price_cents")
        if (
            self.deviation_type == "omitted"
            and self.billing_disposition == "billable"
            and self.final_price_cents is None
        ):
            raise ValueError("billable omitted deviations require final_price_cents")
        if (
            self.billing_disposition in {"complimentary", "included", "not_applicable"}
            and self.final_price_cents not in (None, 0)
        ):
            raise ValueError(
                "complimentary, included, and not_applicable deviations cannot set final_price_cents"
            )

        required_escalation_categories = {
            "damage": "damage",
            "safety_risk": "safety_risk",
            "customer_concern": "customer_concern_or_dispute",
            "billing_uncertainty": "billing_uncertainty",
            "required_return_work": "required_return_work",
        }
        required_category = required_escalation_categories.get(self.deviation_type)
        if required_category and (
            self.escalation is None or self.escalation.category != required_category
        ):
            raise ValueError(
                f"{self.deviation_type} deviations require a {required_category} escalation"
            )
        if self.customer_acknowledgement in {"informed_concern", "disputed"} and (
            self.escalation is None
            or self.escalation.category != "customer_concern_or_dispute"
        ):
            raise ValueError(
                "concerned or disputed deviations require a customer_concern_or_dispute escalation"
            )
        return self


class WorkReconciliation(CloseoutModel):
    """Aggregate quoted-scope and service-result reconciliation."""

    quoted_scope_status: Literal["completed", "partially_completed", "not_completed"]
    result_status: Literal[
        "achieved",
        "achieved_with_limitations",
        "not_achieved",
        "not_assessed",
    ]
    deviations: list[ScopeDeviation]

    @model_validator(mode="after")
    def validate_aggregate_scope(self) -> "WorkReconciliation":
        """Keep aggregate scope status consistent with supplied exceptions."""
        deviation_types = {deviation.deviation_type for deviation in self.deviations}
        if self.quoted_scope_status == "partially_completed" and not self.deviations:
            raise ValueError("partially_completed quoted scope requires at least one deviation")
        if self.quoted_scope_status == "completed" and deviation_types.intersection(
            {"omitted", "partially_completed", "substituted"}
        ):
            raise ValueError(
                "completed quoted scope cannot include omitted, partially_completed, or substituted deviations"
            )
        return self


class NextServiceTiming(CloseoutModel):
    """Exact or windowed timing for a requested future service."""

    exact_at: datetime | None = None
    window_start: date | None = None
    window_end: date | None = None
    timing_note: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_timing_shape(self) -> "NextServiceTiming":
        """Require an executable exact time or complete date window."""
        has_exact = self.exact_at is not None
        has_window_start = self.window_start is not None
        has_window_end = self.window_end is not None
        if has_exact and (has_window_start or has_window_end):
            raise ValueError("exact_at is mutually exclusive with window_start and window_end")
        if has_window_start != has_window_end:
            raise ValueError("window_start and window_end must be supplied together")
        if not has_exact and not has_window_start:
            raise ValueError("next-service timing requires exact_at or a complete date window")
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("window_end must not precede window_start")
        return self


class PlannedService(CloseoutModel):
    """One explicit future service when the quoted baseline is not reused unchanged."""

    service_id: UUID
    description: str | None = Field(None, max_length=500)
    quantity: int = Field(default=1, ge=1)
    unit_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int | None = Field(None, ge=0)
    duration_minutes: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=1000)


class NextServiceDisposition(CloseoutModel):
    """Final decision for future service after this ticket closes."""

    disposition: Literal["book", "remind", "declined", "undecided", "not_applicable"]
    timing: NextServiceTiming | None = None
    planned_scope: list[PlannedService] = Field(default_factory=list)
    planned_duration_minutes: int | None = Field(None, ge=1)
    pricing_status: Literal["set", "catalog_default", "set_later"] | None = None
    scheduling_mode: Literal["exact", "date_window", "route_flexible"] | None = None
    routing_instruction: str | None = Field(None, max_length=2000)
    confirmation_channel: Literal["email", "text", "phone", "none"] | None = None

    @model_validator(mode="after")
    def validate_disposition_details(self) -> "NextServiceDisposition":
        """Require only the details necessary to execute the stated disposition."""
        has_plan_detail = any(
            (
                self.timing is not None,
                bool(self.planned_scope),
                self.planned_duration_minutes is not None,
                self.pricing_status is not None,
                self.scheduling_mode is not None,
                self.routing_instruction is not None,
                self.confirmation_channel is not None,
            )
        )
        if self.disposition in {"declined", "undecided", "not_applicable"}:
            if has_plan_detail:
                raise ValueError(f"{self.disposition} next_service cannot include plan details")
            return self

        if self.timing is None:
            raise ValueError(f"{self.disposition} next_service requires timing")
        if self.disposition == "remind":
            if self.planned_scope or self.planned_duration_minutes is not None:
                raise ValueError("remind next_service cannot include planned scope or duration")
            if self.pricing_status is not None or self.scheduling_mode is not None:
                raise ValueError("remind next_service cannot include pricing_status or scheduling_mode")
            if self.routing_instruction is not None:
                raise ValueError("remind next_service cannot include routing_instruction")
            if self.confirmation_channel in (None, "none"):
                raise ValueError("remind next_service requires email, text, or phone confirmation_channel")
            return self

        if self.pricing_status is None or self.scheduling_mode is None:
            raise ValueError("book next_service requires pricing_status and scheduling_mode")
        if self.scheduling_mode == "exact" and self.timing.exact_at is None:
            raise ValueError("exact booking requires timing.exact_at")
        if self.scheduling_mode in {"date_window", "route_flexible"} and self.timing.window_start is None:
            raise ValueError(
                f"{self.scheduling_mode} booking requires timing.window_start and timing.window_end"
            )
        if self.scheduling_mode == "route_flexible" and not self.routing_instruction:
            raise ValueError("route_flexible booking requires routing_instruction")
        if self.pricing_status in {"catalog_default", "set_later"} and any(
            service.unit_price_cents is not None or service.total_price_cents is not None
            for service in self.planned_scope
        ):
            raise ValueError(
                f"{self.pricing_status} booking cannot include explicit planned-service prices"
            )
        if self.pricing_status == "set" and any(
            service.unit_price_cents is None and service.total_price_cents is None
            for service in self.planned_scope
        ):
            raise ValueError("set pricing requires a unit_price_cents or total_price_cents for every planned service")
        return self


class CloseoutRequest(CloseoutModel):
    """Canonical command for closing a service appointment ticket."""

    ticket_id: UUID
    actual_duration_minutes: int = Field(..., ge=1)
    work_reconciliation: WorkReconciliation
    customer_capture: CustomerCapture
    next_service: NextServiceDisposition
    follow_up_actions: list[FollowUpAction]
    technician_summary: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def require_customer_concern_escalation(self) -> "CloseoutRequest":
        """Customer-stated concern must have a structured owned disposition."""
        if self.customer_capture.customer_response != "concern_stated":
            return self
        if not any(
            deviation.escalation is not None
            and deviation.escalation.category == "customer_concern_or_dispute"
            for deviation in self.work_reconciliation.deviations
        ):
            raise ValueError(
                "customer_response concern_stated requires a customer_concern_or_dispute escalation"
            )
        return self


class BillingHoldResolution(CloseoutModel):
    """Office confirmation that unlocks invoicing at the existing final total."""

    ticket_id: UUID
    confirmed_total_cents: int = Field(..., ge=0)
    resolution_note: str = Field(..., min_length=1, max_length=4000)


class TicketCloseout(CloseoutModel):
    """Persisted structured closeout aggregate."""

    id: UUID
    workspace_id: UUID
    ticket_id: UUID
    actual_duration_minutes: int
    work_reconciliation: WorkReconciliation
    customer_capture: CustomerCapture
    next_service: NextServiceDisposition
    technician_summary: str | None
    final_subtotal_cents: int
    invoice_ready: bool
    future_ticket_id: UUID | None
    created_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CloseoutProfileUpdate(CloseoutModel):
    """Persisted closeout-sourced customer-history fact."""

    id: UUID
    workspace_id: UUID
    ticket_closeout_id: UUID
    customer_id: UUID
    address_id: UUID | None
    update: ProfileUpdate
    created_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class FutureServicePlan(CloseoutModel):
    """Persisted non-exact booking or reminder plan."""

    id: UUID
    workspace_id: UUID
    ticket_closeout_id: UUID
    customer_id: UUID
    address_id: UUID | None
    disposition: Literal["book", "remind"]
    status: Literal["pending", "reminder"]
    timing: NextServiceTiming
    planned_scope: list[PlannedService]
    planned_duration_minutes: int | None
    pricing_status: Literal["set", "catalog_default", "set_later"] | None
    scheduling_mode: Literal["date_window", "route_flexible"] | None
    routing_instruction: str | None
    confirmation_channel: Literal["email", "text", "phone", "none"] | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class FollowUpActionRecord(CloseoutModel):
    """Persisted executable follow-up action, including generated communications."""

    id: UUID
    workspace_id: UUID
    ticket_closeout_id: UUID
    customer_id: UUID
    address_id: UUID | None
    action_type: Literal[
        "create_quote",
        "schedule_return_visit",
        "send_review_request",
        "send_referral_follow_up",
        "send_customer_message",
        "record_customer_callback",
        "track_customer_required_repair",
        "send_service_reminder",
        "send_confirmation",
    ]
    responsible_party: Literal["business", "customer"]
    description: str
    due_at: datetime | None
    channel: Literal["email", "text", "phone", "none"] | None
    status: Literal["open", "completed", "cancelled"]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CloseoutResult(CloseoutModel):
    """Records created by one canonical closeout command."""

    ticket: dict[str, object]
    closeout: TicketCloseout
    future_ticket: dict[str, object] | None
    service_plan: FutureServicePlan | None
    profile_updates: list[CloseoutProfileUpdate]
    follow_up_actions: list[FollowUpActionRecord]
