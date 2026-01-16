"""Tests for Anthropic LLM client - uses real API calls."""

import pytest


class TestLLMClient:
    """Integration tests for LLMClient using real Anthropic API."""

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

    def test_generate_json_output(self):
        """Model follows JSON instructions in system prompt."""
        import json
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[
                {
                    "role": "system",
                    "content": """You are a status reporting assistant.

IMPORTANT: Output raw JSON only. Do not wrap in code fences. Do not include any text before or after the JSON.

Example of correct output:
{"status": "ok"}"""
                },
                {"role": "user", "content": 'What is the current status?'}
            ]
        )

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
                    "content": """You are an assistant that extracts structured attributes from service technician notes.

Possible keys:
- customer_demographic (elderly, young_family, etc)
- pet (object with type and optional name)
- property_notes (important access info)

IMPORTANT: Output raw JSON only. Do not wrap in code fences. Do not include any text before or after the JSON.

Example of correct output:
{"customer_demographic": "elderly", "pet": {"type": "dog", "name": "Max"}}"""
                },
                {
                    "role": "user",
                    "content": "Elderly woman, very nice. Dog named Biscuit, keep gate closed."
                }
            ]
        )

        parsed = json.loads(result.content)
        assert isinstance(parsed, dict)
        # Should extract at least something from those obvious hints
        assert len(parsed) > 0

    def test_json_repair_handles_codefences(self):
        """JSON repair handles model responses with code fences and explanation."""
        import json
        from json_repair import repair_json
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. When asked for JSON, wrap it in markdown code fences and include a brief explanation."
                },
                {"role": "user", "content": 'Give me a JSON object with key "test" and value "success"'}
            ]
        )

        # Model likely returns something like:
        # Here's the JSON:
        # ```json
        # {"test": "success"}
        # ```
        # json_repair should handle this
        repaired = repair_json(result.content)
        parsed = json.loads(repaired)
        assert isinstance(parsed, dict)
        assert "test" in parsed

    def test_generate_includes_usage_stats(self):
        """Response includes token usage statistics."""
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[{"role": "user", "content": "Say hello"}]
        )

        assert result.usage is not None
        assert "input_tokens" in result.usage
        assert "output_tokens" in result.usage
        assert result.usage["input_tokens"] > 0
        assert result.usage["output_tokens"] > 0

    def test_thinking_produces_output(self):
        """Extended thinking produces non-zero thinking output."""
        from clients.llm_client import LLMClient

        client = LLMClient()
        result = client.generate(
            messages=[{"role": "user", "content": "What is 15 * 17?"}],
            thinking=True
        )

        # Thinking should be captured and non-empty
        assert result.thinking is not None
        assert len(result.thinking) > 0
        # The actual response should also exist
        assert len(result.content) > 0


class TestLLMResponse:
    """Tests for LLMResponse model."""

    def test_has_content_attribute(self):
        """LLMResponse has content attribute."""
        from clients.llm_client import LLMResponse

        response = LLMResponse(content="Test content")
        assert response.content == "Test content"

    def test_has_usage_attribute(self):
        """LLMResponse has optional usage attribute."""
        from clients.llm_client import LLMResponse

        response = LLMResponse(
            content="Test",
            usage={"input_tokens": 10, "output_tokens": 5}
        )
        assert response.usage["input_tokens"] == 10
        assert response.usage["output_tokens"] == 5


class TestLLMError:
    """Tests for LLMError exception."""

    def test_llm_error_is_exception(self):
        """LLMError can be raised and caught."""
        from clients.llm_client import LLMError

        with pytest.raises(LLMError):
            raise LLMError("Test error")


class TestStreamEvents:
    """Tests for stream event dataclasses."""

    def test_text_event(self):
        """TextEvent has content."""
        from clients.llm_client import TextEvent

        event = TextEvent(content="Hello")
        assert event.content == "Hello"

    def test_tool_detected_event(self):
        """ToolDetectedEvent has name and id."""
        from clients.llm_client import ToolDetectedEvent

        event = ToolDetectedEvent(tool_name="search", tool_id="toolu_123")
        assert event.tool_name == "search"
        assert event.tool_id == "toolu_123"

    def test_tool_executing_event(self):
        """ToolExecutingEvent has name, id, and arguments."""
        from clients.llm_client import ToolExecutingEvent

        event = ToolExecutingEvent(
            tool_name="search",
            tool_id="toolu_123",
            arguments={"query": "test"}
        )
        assert event.tool_name == "search"
        assert event.arguments == {"query": "test"}

    def test_tool_completed_event(self):
        """ToolCompletedEvent has name, id, and result."""
        from clients.llm_client import ToolCompletedEvent

        event = ToolCompletedEvent(
            tool_name="search",
            tool_id="toolu_123",
            result="Found 5 results"
        )
        assert event.result == "Found 5 results"

    def test_error_event(self):
        """ErrorEvent has error and optional details."""
        from clients.llm_client import ErrorEvent

        event = ErrorEvent(error="API failed", details="Rate limit exceeded")
        assert event.error == "API failed"
        assert event.details == "Rate limit exceeded"
