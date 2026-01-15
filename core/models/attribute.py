"""Attribute domain models."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttributeCreate(BaseModel):
    """Data required to create an attribute."""

    customer_id: UUID
    key: str = Field(..., min_length=1, max_length=100)
    value: Any
    source_type: str = Field("manual", pattern="^(manual|llm_extracted)$")
    source_note_id: UUID | None = None
    # Confidence only set for llm_extracted, None for manual
    confidence: Decimal | None = Field(None, ge=0, le=1, decimal_places=2)


class Attribute(BaseModel):
    """Full attribute entity as stored."""

    id: UUID
    user_id: UUID
    customer_id: UUID
    key: str
    value: Any
    source_type: str
    source_note_id: UUID | None
    confidence: Decimal | None  # 0.00-1.00, only for llm_extracted
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractedAttributes(BaseModel):
    """Attributes extracted from notes by LLM."""

    attributes: dict[str, Any]
    raw_response: str = Field(..., max_length=10000)
    confidence: Decimal = Field(..., ge=0, le=1, decimal_places=2)
