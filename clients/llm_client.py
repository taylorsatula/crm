"""
Anthropic LLM client with streaming and tool support.

Usage:
    # Non-streaming (extraction, distillation)
    response = client.generate(messages)

    # Streaming with tools (customer conversations)
    for event in client.stream(messages, tools, tool_executor):
        match event:
            case TextEvent(content):
                print(content, end="")
            case ToolExecutingEvent(name, id, args):
                print(f"Calling {name}...")
"""

import logging
from dataclasses import dataclass
from typing import Any, Generator, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from pydantic import BaseModel

from clients.vault_client import get_llm_config

logger = logging.getLogger(__name__)


# === Response Types ===


class LLMResponse(BaseModel):
    """Non-streaming response."""

    content: str
    thinking: str | None = None
    raw_response: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


# === Stream Events ===


@dataclass
class TextEvent:
    """Text chunk from LLM."""

    content: str


@dataclass
class ToolDetectedEvent:
    """Tool call detected in response."""

    tool_name: str
    tool_id: str


@dataclass
class ToolExecutingEvent:
    """Tool execution starting."""

    tool_name: str
    tool_id: str
    arguments: dict


@dataclass
class ToolCompletedEvent:
    """Tool execution succeeded."""

    tool_name: str
    tool_id: str
    result: str


@dataclass
class ToolErrorEvent:
    """Tool execution failed."""

    tool_name: str
    tool_id: str
    error: str


@dataclass
class CompleteEvent:
    """Stream finished."""

    response: Any  # anthropic.types.Message


@dataclass
class ErrorEvent:
    """Stream error."""

    error: str
    details: str | None = None


StreamEvent = (
    TextEvent
    | ToolDetectedEvent
    | ToolExecutingEvent
    | ToolCompletedEvent
    | ToolErrorEvent
    | CompleteEvent
    | ErrorEvent
)


# === Errors ===


class LLMError(Exception):
    """LLM operation error."""


# === Client ===


class LLMClient:
    """Anthropic API client."""

    DEFAULT_MODEL = "claude-haiku-4-5"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize Anthropic client.

        Args:
            api_key: Anthropic API key. If None, fetched from Vault.
            model: Model name. If None, uses DEFAULT_MODEL.
        """
        if api_key is None:
            config = get_llm_config()
            api_key = config["api_key"]

        self.model = model or self.DEFAULT_MODEL
        self._client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"LLM client initialized with model: {self.model}")

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: str | None = None,
        thinking: bool = True,
        thinking_budget: int = 1024,
    ) -> LLMResponse:
        """
        Non-streaming generation for extraction, distillation, etc.

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": str}]
            temperature: Sampling temperature (0-1), ignored when thinking=True
            max_tokens: Maximum output tokens
            model: Override model for this call (e.g., "claude-sonnet-4-5-20241022")
            thinking: Enable extended thinking (default True)
            thinking_budget: Token budget for thinking (default 1024)

        Returns:
            LLMResponse with content, raw_response, and usage stats

        Raises:
            LLMError: If API call fails
        """
        system_prompt, api_messages = self._prepare_messages(messages)

        try:
            params = {
                "model": model or self.model,
                "messages": api_messages,
                "max_tokens": max_tokens,
            }
            if system_prompt:
                params["system"] = system_prompt

            if thinking:
                # Extended thinking requires temperature=1 and max_tokens > budget_tokens
                # Add thinking budget to max_tokens so user's max_tokens applies to output only
                params["temperature"] = 1
                params["max_tokens"] = max_tokens + thinking_budget
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
            else:
                params["temperature"] = temperature

            response = self._client.messages.create(**params)

            return LLMResponse(
                content=self._extract_text(response),
                thinking=self._extract_thinking(response),
                raw_response={"id": response.id, "model": response.model},
                usage=self._extract_usage(response),
            )
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            raise LLMError(f"LLM API call failed: {e}")

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: str | None = None,
        thinking: bool = True,
        thinking_budget: int = 1024,
    ) -> Generator[StreamEvent, None, None]:
        """
        Streaming generation with tool loop for conversations.

        Args:
            messages: Conversation messages
            tools: Anthropic tool definitions
            tool_executor: fn(tool_name, arguments) -> result_str
            temperature: Sampling temperature, ignored when thinking=True
            max_tokens: Maximum output tokens
            model: Override model for this call (e.g., "claude-sonnet-4-5-20241022")
            thinking: Enable extended thinking (default True)
            thinking_budget: Token budget for thinking (default 1024)

        Yields:
            StreamEvent instances
        """
        system_prompt, api_messages = self._prepare_messages(messages)
        current_messages = api_messages.copy()
        use_model = model or self.model

        while True:
            response = None
            for event in self._stream_response(
                system_prompt, current_messages, tools, temperature, max_tokens, use_model,
                thinking, thinking_budget
            ):
                if isinstance(event, CompleteEvent):
                    response = event.response
                yield event

            if response is None:
                return

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls or not tool_executor:
                return

            # Execute tools in parallel
            tool_results = []
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                futures = {
                    executor.submit(tool_executor, tc["name"], tc["input"]): tc
                    for tc in tool_calls
                }
                for future in as_completed(futures):
                    tc = futures[future]
                    yield ToolExecutingEvent(tc["name"], tc["id"], tc["input"])
                    try:
                        result = future.result()
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tc["id"],
                                "content": result,
                            }
                        )
                        yield ToolCompletedEvent(tc["name"], tc["id"], result)
                    except Exception as e:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tc["id"],
                                "content": f"Error: {e}",
                                "is_error": True,
                            }
                        )
                        yield ToolErrorEvent(tc["name"], tc["id"], str(e))

            current_messages.append(self._build_assistant_message(response))
            current_messages.append({"role": "user", "content": tool_results})

    # === Private ===

    def _prepare_messages(
        self, messages: list[dict]
    ) -> tuple[str | None, list[dict]]:
        """Extract system prompt and prepare for Anthropic API."""
        system_content = None
        api_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                api_messages.append(msg)

        return system_content, api_messages

    def _stream_response(
        self,
        system_prompt: str | None,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        max_tokens: int,
        model: str,
        thinking: bool,
        thinking_budget: int,
    ) -> Generator[StreamEvent, None, None]:
        """Stream a single API call."""
        try:
            params = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if system_prompt:
                params["system"] = system_prompt
            if tools:
                params["tools"] = tools

            if thinking:
                # Extended thinking requires temperature=1 and max_tokens > budget_tokens
                # Add thinking budget to max_tokens so user's max_tokens applies to output only
                params["temperature"] = 1
                params["max_tokens"] = max_tokens + thinking_budget
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
            else:
                params["temperature"] = temperature

            with self._client.messages.stream(**params) as stream:
                for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta" and hasattr(
                            event.delta, "text"
                        ):
                            yield TextEvent(event.delta.text)
                        elif (
                            event.type == "content_block_start"
                            and event.content_block.type == "tool_use"
                        ):
                            yield ToolDetectedEvent(
                                event.content_block.name, event.content_block.id
                            )

                yield CompleteEvent(response=stream.get_final_message())

        except anthropic.APIError as e:
            yield ErrorEvent(str(e), getattr(e, "message", None))

    def _extract_text(self, response) -> str:
        """Extract text content from response."""
        return "".join(b.text for b in response.content if b.type == "text")

    def _extract_thinking(self, response) -> str | None:
        """Extract thinking content from response."""
        thinking_blocks = [b.thinking for b in response.content if b.type == "thinking"]
        if not thinking_blocks:
            return None
        return "".join(thinking_blocks)

    def _extract_usage(self, response) -> dict[str, int] | None:
        """Extract token usage from response."""
        if not response.usage:
            return None
        return {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    def _extract_tool_calls(self, response) -> list[dict]:
        """Extract tool calls from response."""
        return [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in response.content
            if b.type == "tool_use"
        ]

    def _build_assistant_message(self, response) -> dict:
        """Build assistant message for conversation continuation."""
        content = []
        for b in response.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                )
        return {"role": "assistant", "content": content}
