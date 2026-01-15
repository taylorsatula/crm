"""Tests for LLM client - uses real API calls."""

import pytest


class TestLLMClient:
    """Integration tests for LLMClient using real API."""

    def test_generate_returns_response(self):
        """Basic generation returns content."""
        from clients.llm_client import LLMClient, LLMResponse

        client = LLMClient()
        result = client.generate(
            messages=[{"role": "user", "content": "Reply with exactly: PONG"}]
        )

        assert isinstance(result, LLMResponse)
        assert len(result.content) > 0

    def test_generate_with_system_prompt(self):
        """System prompt influences response."""
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[
                {"role": "system", "content": "You are a pirate. Always say 'Arrr' in your response."},
                {"role": "user", "content": "Hello"}
            ]
        )

        # Pirate should say Arrr (case insensitive check)
        assert "arr" in result.content.lower()

    def test_generate_json_mode(self):
        """JSON mode returns parseable JSON."""
        import json
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[
                {"role": "system", "content": "Return JSON only. No other text."},
                {"role": "user", "content": 'Return a JSON object with key "status" and value "ok"'}
            ],
            response_format={"type": "json_object"}
        )

        # Should be valid JSON
        parsed = json.loads(result.content)
        assert isinstance(parsed, dict)

    def test_extract_attributes_use_case(self):
        """Test the actual use case: extracting attributes from notes."""
        import json
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[
                {
                    "role": "system",
                    "content": """Extract structured attributes from service notes. Return JSON with these possible keys:
- customer_demographic (elderly, young_family, etc)
- pet (object with type and optional name)
- property_notes (important access info)
Only include keys you're confident about."""
                },
                {
                    "role": "user",
                    "content": "Elderly woman, very nice. Dog named Biscuit, keep gate closed."
                }
            ],
            response_format={"type": "json_object"}
        )

        parsed = json.loads(result.content)
        assert isinstance(parsed, dict)
        # Should extract at least something from those obvious hints
        assert len(parsed) > 0


class TestLLMResponse:
    """Tests for LLMResponse model."""

    def test_has_content_attribute(self):
        """LLMResponse has content attribute."""
        from clients.llm_client import LLMResponse

        response = LLMResponse(content="Test content")
        assert response.content == "Test content"


class TestLLMError:
    """Tests for LLMError exception."""

    def test_llm_error_is_exception(self):
        """LLMError can be raised and caught."""
        from clients.llm_client import LLMError

        with pytest.raises(LLMError):
            raise LLMError("Test error")
