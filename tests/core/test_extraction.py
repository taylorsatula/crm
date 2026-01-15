"""Tests for AttributeExtractor."""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch


class TestAttributeExtractor:
    """Tests for AttributeExtractor.extract_attributes."""

    def test_extracts_attributes_from_notes(self):
        """Extracts structured attributes from technician notes."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content='{"pet": {"type": "dog", "name": "Biscuit"}, "customer_demographic": "elderly"}',
            raw_response=None
        )

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Elderly woman with dog named Biscuit")

        assert result.attributes["pet"]["type"] == "dog"
        assert result.attributes["pet"]["name"] == "Biscuit"
        assert result.attributes["customer_demographic"] == "elderly"

    def test_repairs_malformed_json(self):
        """Uses jsonrepair to fix common LLM JSON errors."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        # LLM returns JSON with trailing comma (common error)
        mock_llm.generate.return_value = LLMResponse(
            content='{"pet": "dog", "notes": "friendly",}',  # Invalid trailing comma
            raw_response=None
        )

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Has a friendly dog")

        # Should successfully repair and parse
        assert result.attributes["pet"] == "dog"
        assert result.attributes["notes"] == "friendly"

    def test_repairs_unquoted_keys(self):
        """Repairs JSON with unquoted keys."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        # LLM returns JSON with unquoted keys
        mock_llm.generate.return_value = LLMResponse(
            content='{pet: "cat", age: "young"}',  # Unquoted keys
            raw_response=None
        )

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Young cat")

        assert result.attributes.get("pet") == "cat"

    def test_returns_empty_dict_on_unrepairable_json(self):
        """Returns empty attributes when JSON cannot be repaired."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        # Completely malformed - not salvageable
        mock_llm.generate.return_value = LLMResponse(
            content="I couldn't extract any attributes from those notes.",
            raw_response=None
        )

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Some notes")

        assert result.attributes == {}
        assert "couldn't extract" in result.raw_response

    def test_includes_raw_response(self):
        """Raw response is captured for debugging."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        raw = '{"property_notes": "gate code 1234"}'
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=raw, raw_response=None)

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Gate code is 1234")

        assert result.raw_response == raw

    def test_passes_correct_messages_to_llm(self):
        """Verifies system prompt and user message format."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{}', raw_response=None)

        extractor = AttributeExtractor(mock_llm)
        extractor.extract_attributes("Customer has 2 large dogs")

        # Verify call structure
        mock_llm.generate.assert_called_once()
        call_kwargs = mock_llm.generate.call_args.kwargs
        messages = call_kwargs["messages"]

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "extracts structured information" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"
        assert "Customer has 2 large dogs" in messages[1]["content"]

    def test_requests_json_response_format(self):
        """Requests JSON output format from LLM."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{}', raw_response=None)

        extractor = AttributeExtractor(mock_llm)
        extractor.extract_attributes("Test notes")

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}

    def test_confidence_is_decimal(self):
        """Confidence is returned as Decimal."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMResponse

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content='{"pet": "cat"}',
            raw_response=None
        )

        extractor = AttributeExtractor(mock_llm)
        result = extractor.extract_attributes("Has a cat")

        assert isinstance(result.confidence, Decimal)
        assert Decimal("0") <= result.confidence <= Decimal("1")


class TestExtractionWithRealLLM:
    """Integration tests with real LLM API.

    These tests call the actual LLM API to verify extraction works end-to-end.
    They're slower and require API credentials but validate real behavior.
    """

    @pytest.fixture
    def extractor(self):
        """Create extractor with real LLM client."""
        from core.extraction import AttributeExtractor
        from clients.llm_client import LLMClient

        llm = LLMClient()
        return AttributeExtractor(llm)

    def test_extracts_pet_info(self, extractor):
        """Extracts pet information from notes."""
        result = extractor.extract_attributes(
            "Nice elderly couple. They have a golden retriever named Max who is very friendly."
        )

        # Should extract pet info
        assert "pet" in result.attributes or any("dog" in str(v).lower() for v in result.attributes.values())

    def test_extracts_property_details(self, extractor):
        """Extracts property-related information."""
        result = extractor.extract_attributes(
            "Gate code is 4521. Park on the left side, not in front of garage. "
            "Brought extension ladder for the high windows on 2nd floor."
        )

        # Should extract something useful about property or equipment
        assert len(result.attributes) > 0
        raw_lower = result.raw_response.lower()
        # At minimum the response should mention gate or ladder
        assert "gate" in raw_lower or "ladder" in raw_lower or "4521" in raw_lower

    def test_handles_empty_notes(self, extractor):
        """Returns empty or minimal attributes for empty notes."""
        result = extractor.extract_attributes("")

        # Should handle gracefully
        assert result.raw_response is not None
