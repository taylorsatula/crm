"""
LLM-powered attribute extraction from technician notes.

Uses LLM to extract structured, queryable attributes from free-form
notes entered during ticket close-out.
"""

import json
import logging
from decimal import Decimal
from typing import Any

from json_repair import repair_json

from clients.llm_client import LLMClient
from core.models.attribute import ExtractedAttributes

logger = logging.getLogger(__name__)


class AttributeExtractor:
    """
    Extract structured attributes from free-form technician notes.

    Uses LLM to identify entities and facts that should become
    queryable attributes on the customer record.
    """

    SYSTEM_PROMPT = """You are an assistant that extracts structured information from service technician notes.

Given notes about a customer service visit, extract relevant attributes that would be useful for future visits.

Categories to look for:
- customer_demographic: age indicators (elderly, young family, etc.)
- pet: any pets mentioned (type, name if given)
- property_notes: important property details (gate codes, access instructions, hazards)
- equipment_needed: special equipment requirements
- service_preferences: customer preferences about timing, methods, etc.
- property_details: physical property characteristics

Only include attributes you're confident about. Use snake_case keys. Values should be strings or simple objects.

IMPORTANT: Output raw JSON only. Do not wrap in code fences. Do not include any text before or after the JSON.

Example input: "Elderly woman, very nice. Dog named Biscuit, keep gate closed. Complex sill on 2nd story, brought extension ladder."

Example of correct output:
{"customer_demographic": "elderly", "pet": {"type": "dog", "name": "Biscuit"}, "property_notes": "keep gate closed", "equipment_needed": "extension ladder", "property_details": "complex 2nd story sill"}
"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def extract_attributes(self, notes: str) -> ExtractedAttributes:
        """
        Extract attributes from technician notes.

        This is called synchronously during close-out so the
        technician can review extracted attributes before confirming.

        Args:
            notes: Free-form technician notes

        Returns:
            ExtractedAttributes with parsed attributes and confidence
        """
        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract attributes from these notes:\n\n{notes}"}
            ]
        )

        raw_content = response.content
        attributes = self._parse_json_with_repair(raw_content)

        return ExtractedAttributes(
            attributes=attributes,
            raw_response=raw_content,
            confidence=Decimal("0.80")  # Default confidence for LLM extraction
        )

    def _parse_json_with_repair(self, content: str) -> dict[str, Any]:
        """
        Parse JSON with repair fallback for common LLM errors.

        LLMs sometimes produce malformed JSON (trailing commas, unquoted keys, etc.).
        We use json_repair to fix these common issues before giving up.

        Args:
            content: Raw LLM response

        Returns:
            Parsed dict, or empty dict if unparseable
        """
        # First, try standard JSON parsing
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to repair the JSON
        try:
            repaired = repair_json(content)
            result = json.loads(repaired)
            if isinstance(result, dict):
                return result
            # If repair returned a list or primitive, wrap or ignore
            logger.warning(f"JSON repair returned non-dict: {type(result)}")
            return {}
        except Exception as e:
            logger.warning(f"Could not parse or repair JSON: {e}")
            return {}
